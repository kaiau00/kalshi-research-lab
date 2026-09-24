"""Optional demo execution in the existing service, without changing research registration."""
import asyncio
import contextlib
import os
from contextlib import asynccontextmanager

from fastapi import Depends
from fastapi.responses import HTMLResponse

from research_lab.app import authenticated
from research_lab.app import create_app as research_app

from .runner import Runner


def create_app(record=True):
    app = research_app(record=record)
    original = app.router.lifespan_context
    runner = None
    task = None

    @asynccontextmanager
    async def lifespan(application):
        nonlocal runner, task
        async with original(application):
            if os.environ.get('LAB_DEMO_ENABLED') == '1':
                runner = Runner()
                task = asyncio.create_task(runner.run())
            try:
                yield
            finally:
                if task:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task

    app.router.lifespan_context = lifespan

    @app.get('/api/demo/status', dependencies=[Depends(authenticated)])
    async def status():
        if not runner:
            return {'environment': 'demo', 'state': 'disabled'}
        return {**runner.status, 'runner_active': bool(task and not task.done())}

    @app.get('/demo', dependencies=[Depends(authenticated)])
    async def dashboard():
        return HTMLResponse('''<!doctype html><html lang="en"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1"><title>Fair value — Kalshi demo</title>
        <style>body{font:16px system-ui;max-width:900px;margin:40px auto;padding:0 20px;background:#101820;
        color:#edf4f7}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#192934;padding:20px;
        border-radius:12px}a{color:#7bd8ea}</style><h1>Fair value · Kalshi demo</h1>
        <p>$125 practice bankroll · $1 maximum per market · BTC 15-minute markets</p>
        <p>Exchange-reported demo execution. Demo liquidity and profits do not establish real-market returns.</p>
        <p><a href="/">Research dashboard</a></p><pre id="status">Loading…</pre><script>
        async function refresh(){try{let r=await fetch('/api/demo/status');if(!r.ok)throw new Error(r.status);
        document.getElementById('status').textContent=JSON.stringify(await r.json(),null,2);}
        catch(e){document.getElementById('status').textContent='Status unavailable: '+e.message;}}
        refresh();setInterval(refresh,5000);</script></html>''')

    return app
