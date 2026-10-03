import asyncio
import json

import httpx
import pytest

from gateway.app import create_app
from gateway.config import Settings
from gateway.errors import GatewayError

MODEL = {
    "id": "opencode/test",
    "upstream": "opencode/test",
    "provider": "opencode",
    "free": True,
    "name": "Test",
    "context": 32000,
    "reasoning": True,
}


class FakeRuntime:
    closed_sessions = 0

    def __init__(self, channel, settings):
        self.channel = channel
        self.settings = settings
        self.models = [MODEL]
        self.version = "fixture-only"
        self.active = 0

    async def start(self):
        pass

    async def close(self):
        pass

    async def generate(self, upstream, prompt, effort=None):
        self.active += 1
        try:
            data = json.loads(prompt.split("API request JSON:\n", 1)[1])
            content = data["messages"][-1]["content"] or ""
            if content == "error":
                raise GatewayError(502, "upstream_denied", "Fixture denied")
            if content == "timeout":
                raise TimeoutError()
            if content == "slow":
                await asyncio.sleep(0.1)
            text = content
            if data.get("tools") and data.get("tool_choice") != "none":
                text = json.dumps(
                    {
                        "content": "",
                        "tool_calls": [
                            {
                                "name": data["tools"][0]["function"]["name"],
                                "arguments": {"city": "杭州"},
                            }
                        ],
                    }
                )
            yield {"type": "reasoning", "text": "简要推理"}
            for part in (text[: len(text) // 2], text[len(text) // 2 :]):
                yield {"type": "text", "text": part}
            yield {
                "type": "done",
                "stop": "end_turn",
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            }
        finally:
            self.active -= 1
            FakeRuntime.closed_sessions += 1


@pytest.fixture
async def client(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        bootstrap_token="fixture-bootstrap-token",
        web_dir=tmp_path / "missing-web",
    )
    app = create_app(settings, FakeRuntime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        client.app = app
        yield client


@pytest.fixture
async def admin(client):
    result = await client.post(
        "/api/setup",
        json={
            "username": "admin",
            "password": "fixture-password-123",
            "bootstrap_token": "fixture-bootstrap-token",
        },
    )
    assert result.status_code == 200
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return client


@pytest.fixture
async def ready(admin):
    channel = await admin.post("/api/channels", json={"name": "Fixture", "allow_training": True})
    ident = channel.json()["id"]
    assert (await admin.post(f"/api/channels/{ident}/sync")).status_code == 200
    result = await admin.post("/api/keys", json={"name": "Application"})
    admin.headers["Authorization"] = "Bearer " + result.json()["key"]
    return admin, ident, result.json()["id"]


def chat(content="你好", **options):
    return {"model": MODEL["id"], "messages": [{"role": "user", "content": content}], **options}
