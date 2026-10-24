from fastapi.testclient import TestClient

from hft_demo.app import create_app


class FakeRunner:
    def __init__(self):
        self.status = {"state": "watching", "environment": "Kalshi Demo"}

    async def run(self):
        import asyncio

        await asyncio.Event().wait()

    def snapshot(self):
        return self.status


def test_dashboard_and_status_require_basic_auth(monkeypatch):
    monkeypatch.setenv("LAB_DASHBOARD_PASSWORD", "secret")
    with TestClient(create_app(runner_factory=FakeRunner)) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/status").status_code == 401
        response = client.get("/api/status", auth=("lab", "secret"))
        assert response.status_code == 200
        assert response.json()["runner_active"] is True
        page = client.get("/", auth=("lab", "secret"))
        assert "KALSHI DEMO ONLY" in page.text


def test_stopped_runner_keeps_last_status_available(monkeypatch):
    class StoppedRunner(FakeRunner):
        async def run(self):
            return

    monkeypatch.setenv("LAB_DASHBOARD_PASSWORD", "secret")
    with TestClient(create_app(runner_factory=StoppedRunner)) as client:
        import time

        for _ in range(20):
            if client.get("/healthz").status_code == 503:
                break
            time.sleep(0.01)
        response = client.get("/api/status", auth=("lab", "secret"))
        assert response.status_code == 200
        assert response.json()["runner_active"] is False
