"""Optional demo execution in the existing service, without changing research registration."""
import asyncio
import contextlib
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends
from fastapi.responses import HTMLResponse

from hft_research.archive import process_trade_segment
from hft_research.sidecar import TradeTapeSidecar
from market_shrunk_cap5_production.runner import RUNNER_NAME as MARKET_SHRUNK_CAP5_RUNNER_NAME
from market_shrunk_cap5_production.runner import Runner as MarketShrunkCap5ProductionRunner
from market_shrunk_production.runner import RUNNER_NAME as MARKET_SHRUNK_RUNNER_NAME
from market_shrunk_production.runner import Runner as MarketShrunkProductionRunner
from production_execution.runner import Runner as ProductionRunner
from research_lab.app import authenticated
from research_lab.app import create_app as research_app
from walk_forward_study.runner import ParameterRunner

from .runner import Runner
from .study_worker import (
    candidate_work_ready,
    latest_candidate_status,
    latest_conservative_anchor_status,
    latest_edge_status,
    latest_market_anchor_status,
    latest_moderate_disagreement_status,
)


def create_app(record=True):
    app = research_app(record=record)
    original = app.router.lifespan_context
    runner = None
    task = None
    production_runner = None
    production_task = None
    candidate_task = None
    candidate_process = None
    candidate_worker_status = {'study': '003', 'state': 'starting'}
    parameter = None
    parameter_task = None
    hft_trade_tape = None
    hft_trade_task = None
    hft_trade_archive_task = None
    hft_trade_archive_status = {'state': 'disabled'}
    hft_trade_start_error = None

    async def hft_trade_archive_loop():
        nonlocal hft_trade_archive_status
        while True:
            try:
                result = (
                    await asyncio.to_thread(process_trade_segment, hft_trade_tape.root)
                    if hft_trade_tape.store.has_sealed()
                    else {'state': 'idle'}
                )
                hft_trade_archive_status = {**result, 'updated_ns': time.time_ns()}
                await asyncio.sleep(1 if result['state'] == 'complete' else 5)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                hft_trade_archive_status = {
                    'state': 'waiting_io',
                    'error': f'{type(exc).__name__}: {exc}',
                    'updated_ns': time.time_ns(),
                }
                if 'HFT trade archive budget reached' in str(exc):
                    hft_trade_archive_status['state'] = 'stopped_archive_budget'
                    if hft_trade_task:
                        hft_trade_task.cancel()
                    return
                await asyncio.sleep(5)

    async def candidate_supervisor():
        nonlocal candidate_process, candidate_worker_status
        while True:
            try:
                ready = await asyncio.to_thread(candidate_work_ready)
                if not ready:
                    candidate_worker_status = latest_candidate_status()
                    await asyncio.sleep(2)
                    continue
                candidate_process = await asyncio.create_subprocess_exec(
                    sys.executable, '-m', 'demo_execution.study_worker',
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await candidate_process.communicate()
                if candidate_process.returncode:
                    candidate_worker_status = {
                        'study': '003', 'state': 'worker_error',
                        'error': stderr.decode()[-500:],
                    }
                    await asyncio.sleep(30)
                else:
                    try:
                        candidate_worker_status = json.loads(stdout.decode().splitlines()[-1])
                    except (ValueError, IndexError):
                        candidate_worker_status = latest_candidate_status()
                candidate_process = None
            except asyncio.CancelledError:
                if candidate_process and candidate_process.returncode is None:
                    candidate_process.terminate()
                    with contextlib.suppress(ProcessLookupError):
                        await candidate_process.wait()
                raise
            except Exception as exc:
                candidate_worker_status = {
                    'study': '003', 'state': 'worker_error',
                    'error': f'{type(exc).__name__}: {exc}',
                }
                await asyncio.sleep(30)

    @asynccontextmanager
    async def lifespan(application):
        nonlocal runner, task, production_runner, production_task
        nonlocal candidate_task, parameter, parameter_task
        nonlocal hft_trade_tape, hft_trade_task, hft_trade_archive_task
        nonlocal hft_trade_start_error
        async with original(application):
            if os.environ.get('LAB_DEMO_ENABLED') == '1' and os.environ.get('LAB_PRODUCTION_ENABLED') == '1':
                raise RuntimeError('Demo and production execution cannot run at the same time')
            if os.environ.get('LAB_DEMO_ENABLED') == '1':
                runner = Runner(production_state_provider=lambda: application.state.research_recorder.state)
                task = asyncio.create_task(runner.run())
            if os.environ.get('LAB_PRODUCTION_ENABLED') == '1':
                production_runners = {
                    MARKET_SHRUNK_RUNNER_NAME: MarketShrunkProductionRunner,
                    MARKET_SHRUNK_CAP5_RUNNER_NAME: MarketShrunkCap5ProductionRunner,
                }
                runner_class = production_runners.get(
                    os.environ.get('LAB_PRODUCTION_RUNNER'), ProductionRunner
                )
                production_runner = runner_class(
                    state_provider=lambda: application.state.research_recorder.state
                )
                production_task = asyncio.create_task(production_runner.run())
            if os.environ.get('LAB_CANDIDATE_STUDY_ENABLED') == '1':
                candidate_task = asyncio.create_task(candidate_supervisor())
            if os.environ.get('LAB_PARAMETER_STUDY_ENABLED') == '1':
                parameter = ParameterRunner()
                parameter_task = asyncio.create_task(parameter.run())
            if os.environ.get('LAB_HFT_TRADE_TAPE_ENABLED') == '1':
                try:
                    hft_trade_tape = TradeTapeSidecar(
                        Path(os.environ.get('LAB_HFT_TRADE_TAPE_DIR', '/data/hft-trades-v1')),
                        watch_provider=lambda: set(application.state.research_recorder.watch),
                    )
                    hft_trade_task = asyncio.create_task(hft_trade_tape.run())
                    hft_trade_archive_task = asyncio.create_task(hft_trade_archive_loop())
                except Exception as exc:
                    hft_trade_start_error = f'{type(exc).__name__}: {exc}'
            try:
                yield
            finally:
                backgrounds = (
                    hft_trade_archive_task, hft_trade_task,
                    parameter_task, candidate_task, production_task, task,
                )
                for background in backgrounds:
                    if background:
                        background.cancel()
                for background in backgrounds:
                    if not background:
                        continue
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await background
                if parameter:
                    parameter.close()

    app.router.lifespan_context = lifespan

    @app.get('/api/demo/status', dependencies=[Depends(authenticated)])
    async def status():
        if not runner:
            return {'environment': 'demo', 'state': 'disabled'}
        return {**runner.status, 'runner_active': bool(task and not task.done())}

    @app.get('/api/production/status', dependencies=[Depends(authenticated)])
    async def production_status():
        if not production_runner:
            return {'environment': 'production', 'state': 'disabled'}
        return {
            **production_runner.status,
            'runner_active': bool(production_task and not production_task.done()),
        }

    @app.get('/api/hft-trade-tape/status', dependencies=[Depends(authenticated)])
    async def hft_trade_tape_status():
        if not hft_trade_tape:
            enabled = os.environ.get('LAB_HFT_TRADE_TAPE_ENABLED') == '1'
            return {
                'study': '028',
                'state': 'failed' if enabled else 'disabled',
                'error': hft_trade_start_error,
                'production_orders_authorized': False,
                'demo_orders_authorized': False,
            }
        return {
            **hft_trade_tape.snapshot(),
            'runner_active': bool(hft_trade_task and not hft_trade_task.done()),
            'archive_job': hft_trade_archive_status,
        }

    @app.get('/api/candidate-study/status', dependencies=[Depends(authenticated)])
    async def candidate_status():
        if os.environ.get('LAB_CANDIDATE_STUDY_ENABLED') != '1':
            return {'study': '003', 'state': 'disabled'}
        saved = await asyncio.to_thread(latest_candidate_status)
        if candidate_worker_status.get('state') == 'worker_error':
            saved = candidate_worker_status
        return {**saved, 'runner_active': bool(candidate_process and candidate_process.returncode is None)}

    @app.get('/api/parameter-study/status', dependencies=[Depends(authenticated)])
    async def parameter_status():
        if not parameter:
            return {'study': '004', 'state': 'disabled'}
        return {**parameter.status,
                'runner_active': bool(parameter_task and not parameter_task.done())}

    @app.get('/api/edge-validation/status', dependencies=[Depends(authenticated)])
    async def edge_validation_status():
        if os.environ.get('LAB_CANDIDATE_STUDY_ENABLED') != '1':
            return {'study': 'edge-validation-001', 'state': 'disabled'}
        return await asyncio.to_thread(latest_edge_status)

    @app.get('/api/market-anchor/status', dependencies=[Depends(authenticated)])
    async def market_anchor_status():
        return await asyncio.to_thread(latest_market_anchor_status)

    @app.get('/api/conservative-anchor/status', dependencies=[Depends(authenticated)])
    async def conservative_anchor_status():
        return await asyncio.to_thread(latest_conservative_anchor_status)

    @app.get('/api/moderate-disagreement/status', dependencies=[Depends(authenticated)])
    async def moderate_disagreement_status():
        return await asyncio.to_thread(latest_moderate_disagreement_status)

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

    @app.get('/production', dependencies=[Depends(authenticated)])
    async def production_dashboard():
        return HTMLResponse('''<!doctype html><html lang="en"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1"><title>Production execution</title>
        <style>body{font:16px system-ui;max-width:900px;margin:40px auto;padding:0 20px;background:#101820;
        color:#edf4f7}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#192934;padding:20px;
        border-radius:12px}a{color:#7bd8ea}</style><h1>Conservative Market Anchor · production</h1>
        <p>Real-money BTC 15-minute execution · $1 maximum per market · fixed sizing</p>
        <p><a href="/">Research dashboard</a> · <a href="/edge-validation">Edge validation</a></p>
        <pre id="status">Loading…</pre><script>
        async function refresh(){try{let r=await fetch('/api/production/status');if(!r.ok)throw new Error(r.status);
        document.getElementById('status').textContent=JSON.stringify(await r.json(),null,2);}
        catch(e){document.getElementById('status').textContent='Status unavailable: '+e.message;}}
        refresh();setInterval(refresh,5000);</script></html>''')

    return app
