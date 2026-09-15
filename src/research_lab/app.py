from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import secrets
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .recorder import Recorder
from .research import write_json
from .settings import data_dir, db_path

LOG = logging.getLogger(__name__)
security = HTTPBasic(auto_error=False)


def authenticated(credentials: HTTPBasicCredentials | None = Depends(security)):
    password = os.environ.get('LAB_DASHBOARD_PASSWORD', '')
    if len(password) < 16:
        raise HTTPException(503, 'Set LAB_DASHBOARD_PASSWORD to at least 16 characters')
    if (credentials is None or not secrets.compare_digest(credentials.username.encode(), b'lab')
            or not secrets.compare_digest(credentials.password.encode(), password.encode())):
        raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Basic realm="Research lab"'})


class Jobs:
    def __init__(self):
        self.task = None
        self.last_start = 0
        self.status = {'state': 'idle'}

    def start(self, split='forward'):
        if self.task and not self.task.done():
            raise HTTPException(409, 'A replay is already running')
        if time.monotonic() - self.last_start < 60:
            raise HTTPException(429, 'Wait one minute between replay jobs')
        self.last_start = time.monotonic()
        self.status = {'state': 'running', 'split': split, 'started_ns': time.time_ns()}
        self.task = asyncio.create_task(self.run(split))

    async def run(self, split):
        proc = None
        try:
            output = data_dir() / 'reports'
            proc = await asyncio.create_subprocess_exec(sys.executable, '-m', 'research_lab.cli', 'backtest',
                '--db', str(db_path()), '--output', str(output), '--split', split,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
            if proc.returncode:
                self.status = {'state': 'failed', 'reason': stderr.decode()[-500:]}
            else:
                path = Path(stdout.decode().strip())
                self.status = {'state': 'complete', 'report': path.name, 'completed_ns': time.time_ns()}
                # Only derived reports rotate; raw observations and registration are retained.
                for old in sorted(output.glob('*.json'))[:-20]:
                    old.unlink()
                    old.with_suffix('.html').unlink(missing_ok=True)
            write_json(data_dir() / 'last-job.json', self.status)
        except TimeoutError:
            self.status = {'state': 'failed', 'reason': 'Replay exceeded the 180-second service budget'}
        finally:
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()


def create_app(record=True):
    jobs = Jobs()
    recorder = None
    worker = None

    async def periodic():
        # Start only after data can exist. No external cron or laptop process is required.
        while True:
            await asyncio.sleep(max(300, int(os.environ.get('LAB_REPORT_INTERVAL_SECONDS', '3600'))))
            if recorder and recorder.status['last_benchmark_ns']:
                try:
                    jobs.start('forward')
                except HTTPException:
                    pass

    @asynccontextmanager
    async def lifespan(app):
        nonlocal recorder, worker
        timer = None
        if record:
            recorder = Recorder(db_path())
            worker = asyncio.create_task(recorder.run())
            timer = asyncio.create_task(periodic())
        try:
            yield
        finally:
            for task in (timer, jobs.task, worker):
                if task:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task

    app = FastAPI(title='Kalshi Research Lab', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.get('/healthz')
    async def health():
        healthy = not record or bool(worker and not worker.done())
        return JSONResponse({'process_healthy': healthy}, status_code=200 if healthy else 503)

    @app.get('/readyz')
    async def ready():
        now = time.time_ns()
        valid = bool(recorder and worker and not worker.done() and recorder.state.index
                     and now - recorder.state.index[-1][2] < 3_000_000_000
                     and abs(now / 1e9 - recorder.state.index[-1][0]) < 3
                     and any(b.valid and now - b.at_ns < 2_000_000_000
                             for t, b in recorder.state.books.items() if t in recorder.current))
        return JSONResponse({'data_ready': valid}, status_code=200 if valid else 503)

    @app.get('/', dependencies=[Depends(authenticated)])
    async def home():
        return HTMLResponse(Path(__file__).with_name('dashboard.html').read_text())

    @app.get('/api/status', dependencies=[Depends(authenticated)])
    async def status():
        return {'recorder': recorder.status if recorder else {'mode': 'disabled'},
                'storage': recorder.store.stats() if recorder and worker and not worker.done() else None,
                'quality': recorder.state.quality if recorder else None, 'job': jobs.status,
                'scope': 'BTC only; research and simulated orders only; $100 per strategy',
                'reports': [p.name for p in sorted((data_dir() / 'reports').glob('*.html'), reverse=True)[:20]]}

    @app.post('/api/replay', dependencies=[Depends(authenticated)])
    async def replay(request: Request):
        if request.headers.get('x-research-lab') != '1' or request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, 'Same-origin dashboard request required')
        if int(request.headers.get('content-length', '0')) > 1024:
            raise HTTPException(413, 'Request too large')
        body = await request.json()
        split = body.get('split', 'forward')
        if split not in ('forward', 'train', 'validation'):
            raise HTTPException(400, 'Holdout access requires the explicit CLI workflow')
        jobs.start(split)
        return JSONResponse(jobs.status, status_code=202)

    @app.get('/reports/{name}', dependencies=[Depends(authenticated)])
    async def report(name: str):
        if not re.fullmatch(r'\d+-[a-f0-9]{8}\.(html|json)', name):
            raise HTTPException(404)
        path = data_dir() / 'reports' / name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)

    return app
