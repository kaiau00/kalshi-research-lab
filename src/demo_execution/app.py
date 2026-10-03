"""Optional demo execution in the existing service, without changing research registration."""
import asyncio
import contextlib
import os
from contextlib import asynccontextmanager

from fastapi import Depends
from fastapi.responses import HTMLResponse

from candidate_study.runner import CandidateRunner
from edge_validation import EdgeValidationReporter
from research_lab.app import authenticated
from research_lab.app import create_app as research_app
from walk_forward_study.runner import ParameterRunner

from .runner import Runner


def create_app(record=True):
    app = research_app(record=record)
    original = app.router.lifespan_context
    runner = None
    task = None
    candidate = None
    candidate_task = None
    parameter = None
    parameter_task = None
    edge_reporter = None

    @asynccontextmanager
    async def lifespan(application):
        nonlocal runner, task, candidate, candidate_task, parameter, parameter_task, edge_reporter
        async with original(application):
            if os.environ.get('LAB_DEMO_ENABLED') == '1':
                runner = Runner(production_state_provider=lambda: application.state.research_recorder.state)
                task = asyncio.create_task(runner.run())
            if os.environ.get('LAB_CANDIDATE_STUDY_ENABLED') == '1':
                candidate = CandidateRunner()
                candidate_task = asyncio.create_task(candidate.run())
                edge_reporter = EdgeValidationReporter(candidate.root)
            if os.environ.get('LAB_PARAMETER_STUDY_ENABLED') == '1':
                parameter = ParameterRunner()
                parameter_task = asyncio.create_task(parameter.run())
            try:
                yield
            finally:
                for background in (parameter_task, candidate_task, task):
                    if background:
                        background.cancel()
                for background in (parameter_task, candidate_task, task):
                    if not background:
                        continue
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await background
                if candidate:
                    candidate.close()
                if parameter:
                    parameter.close()

    app.router.lifespan_context = lifespan

    @app.get('/api/demo/status', dependencies=[Depends(authenticated)])
    async def status():
        if not runner:
            return {'environment': 'demo', 'state': 'disabled'}
        return {**runner.status, 'runner_active': bool(task and not task.done())}

    @app.get('/api/candidate-study/status', dependencies=[Depends(authenticated)])
    async def candidate_status():
        if not candidate:
            return {'study': '003', 'state': 'disabled'}
        return {**candidate.status,
                'runner_active': bool(candidate_task and not candidate_task.done())}

    @app.get('/api/parameter-study/status', dependencies=[Depends(authenticated)])
    async def parameter_status():
        if not parameter:
            return {'study': '004', 'state': 'disabled'}
        return {**parameter.status,
                'runner_active': bool(parameter_task and not parameter_task.done())}

    @app.get('/api/edge-validation/status', dependencies=[Depends(authenticated)])
    async def edge_validation_status():
        if not edge_reporter:
            return {'study': 'edge-validation-001', 'state': 'disabled'}
        return await asyncio.to_thread(edge_reporter.refresh)

    @app.get('/edge-validation', dependencies=[Depends(authenticated)])
    async def edge_validation_dashboard():
        return HTMLResponse('''<!doctype html><html lang="en"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1"><title>Edge validation</title>
        <style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 20px;background:#101820;
        color:#edf4f7}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#192934;padding:20px;
        border-radius:12px}a{color:#7bd8ea}</style><h1>Candidate Study 003 · edge validation</h1>
        <p>Production-data replay · frozen candidates · no order-submission path</p>
        <p><a href="/">Research dashboard</a> · <a href="/demo">Demo status</a></p>
        <pre id="status">Loading…</pre><script>
        async function refresh(){try{let r=await fetch('/api/edge-validation/status');
        if(!r.ok)throw new Error(r.status);document.getElementById('status').textContent=
        JSON.stringify(await r.json(),null,2);}catch(e){document.getElementById('status').textContent=
        'Status unavailable: '+e.message;}}refresh();</script></html>''')

    @app.get('/demo', dependencies=[Depends(authenticated)])
    async def dashboard():
        return HTMLResponse('''<!doctype html><html lang="en"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1"><title>Strategy experiment — Kalshi demo</title>
        <style>body{font:16px system-ui;max-width:900px;margin:40px auto;padding:0 20px;background:#101820;
        color:#edf4f7}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#192934;padding:20px;
        border-radius:12px}a{color:#7bd8ea}</style><h1>Strategy experiment · Kalshi demo</h1>
        <p>Configured practice bankroll · $3 maximum per market · BTC 15-minute markets</p>
        <p>Exchange-reported demo execution. Demo liquidity and profits do not establish real-market returns.</p>
        <p>Actual demo orders remain capped at $3. Risk sizing is compared separately against production
        arrival quotes and never changes or submits an order.</p>
        <p><a href="/">Research dashboard</a> · <a href="/edge-validation">Edge validation</a></p>
        <pre id="status">Loading…</pre><script>
        async function refresh(){try{let r=await fetch('/api/demo/status');if(!r.ok)throw new Error(r.status);
        document.getElementById('status').textContent=JSON.stringify(await r.json(),null,2);}
        catch(e){document.getElementById('status').textContent='Status unavailable: '+e.message;}}
        refresh();setInterval(refresh,5000);</script></html>''')

    return app
