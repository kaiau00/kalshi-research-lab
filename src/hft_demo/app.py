"""Dedicated web process for the isolated Study 029 Kalshi Demo service."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .runner import Runner

security = HTTPBasic(auto_error=False)


def authenticated(credentials: HTTPBasicCredentials | None = Depends(security)):
    password = os.environ.get("LAB_DASHBOARD_PASSWORD", "")
    if (
        not password
        or credentials is None
        or not hmac.compare_digest(credentials.username, "lab")
        or not hmac.compare_digest(credentials.password, password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )


def create_app(*, runner_factory=Runner):
    runner = None
    task = None

    @asynccontextmanager
    async def lifespan(application):
        nonlocal runner, task
        runner = runner_factory()
        application.state.hft_runner = runner
        task = asyncio.create_task(runner.run())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    app = FastAPI(title="Kalyx HFT Demo", lifespan=lifespan)

    @app.get("/healthz")
    async def health():
        if task and task.done():
            raise HTTPException(status_code=503, detail="HFT Demo runner stopped")
        return {"ok": True, "service": "hft-demo-study-029"}

    @app.get("/api/status", dependencies=[Depends(authenticated)])
    async def api_status():
        if not runner:
            return {"state": "starting", "runner_active": False}
        return {**runner.snapshot(), "runner_active": bool(task and not task.done())}

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(authenticated)])
    async def dashboard():
        return HTMLResponse(DASHBOARD)

    return app


DASHBOARD = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kalyx · HFT Demo 029</title><style>
:root{color-scheme:dark}body{margin:0;background:#071116;color:#eaf4f3;font:15px ui-monospace,SFMono-Regular,Menlo,monospace}
main{max-width:1180px;margin:34px auto;padding:0 22px}.head{display:flex;justify-content:space-between;align-items:end;gap:20px}
h1{font:700 32px system-ui;margin:0}.demo{color:#63efc2;letter-spacing:.15em}.sub{color:#8ea7a5;margin-top:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:24px 0}.card{background:#102126;border:1px solid #1f3b40;border-radius:12px;padding:16px}
.label{color:#8ea7a5;font-size:12px;text-transform:uppercase}.value{font-size:22px;margin-top:8px;overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0d1b20;border:1px solid #1f3b40;border-radius:12px;padding:18px;max-height:55vh;overflow:auto}
.good{color:#63efc2}.bad{color:#ff7979}</style><main><div class="head"><div><div class="demo">KALSHI DEMO ONLY</div>
<h1>Deterministic Market Maker · Study 029</h1><div class="sub">One-contract post-only quotes · 3-second lifetime · no production order path</div></div>
<div id="stamp">loading</div></div><section class="grid"><div class="card"><div class="label">Runner</div><div class="value" id="runner">—</div></div>
<div class="card"><div class="label">Cash</div><div class="value" id="cash">—</div></div><div class="card"><div class="label">Inventory</div><div class="value" id="inventory">—</div></div>
<div class="card"><div class="label">Resting quotes</div><div class="value" id="orders">—</div></div><div class="card"><div class="label">Filled contracts</div><div class="value" id="fills">—</div></div>
<div class="card"><div class="label">Realized P&amp;L</div><div class="value" id="pnl">—</div></div></section><pre id="raw">Loading…</pre></main><script>
const el=id=>document.getElementById(id);async function refresh(){try{const r=await fetch('/api/status');if(!r.ok)throw Error(r.status);const d=await r.json(),j=d.journal||{};
el('runner').textContent=d.state+(d.runner_active?' · active':' · stopped');el('runner').className='value '+(d.runner_active&&!String(d.state).includes('error')?'good':'bad');
el('cash').textContent=d.cash?'$'+d.cash:'—';el('inventory').textContent=JSON.stringify(j.inventory||{});el('orders').textContent=j.active_orders??0;el('fills').textContent=j.filled_contracts??0;
el('pnl').textContent='$'+(j.realized_net_pnl??'0');el('stamp').textContent=new Date().toLocaleTimeString();el('raw').textContent=JSON.stringify(d,null,2)}catch(e){el('runner').textContent='unavailable';el('runner').className='value bad';el('raw').textContent=String(e)}}refresh();setInterval(refresh,2000)</script></html>"""
