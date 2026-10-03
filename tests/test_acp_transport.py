import asyncio
import sys
from contextlib import aclosing
from pathlib import Path

import anyio
import httpx
import pytest

from gateway.acp import Runtime
from gateway.config import Settings
from gateway.errors import GatewayError
from gateway.schemas import Channel


@pytest.fixture
async def runtime(tmp_path):
    config = {**Channel(name="Fixture").model_dump(), "id": "fixture"}
    rt = Runtime(config, Settings(data_dir=tmp_path))
    rt.workspace.mkdir(parents=True)
    rt.capabilities = {"sessionCapabilities": {"close": {}}}
    rt.deleted = []
    rt.cleanup_failure = False

    async def mock_http(request):
        assert request.method == "DELETE"
        if rt.cleanup_failure:
            return httpx.Response(500, json={"error": "fixture"})
        rt.deleted.append(request.url.path)
        return httpx.Response(200, json=True)

    rt.http = httpx.AsyncClient(
        base_url="http://localhost", transport=httpx.MockTransport(mock_http)
    )
    rt.process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        str(Path(__file__).parent / "fixtures/agent.py"),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    rt.reader = asyncio.create_task(rt.read_loop())

    async def already_started():
        pass

    rt.start = already_started
    try:
        yield rt
    finally:
        await rt.close()


async def collect(runtime, text):
    async with aclosing(runtime.generate("opencode/test", text)) as events:
        return [event async for event in events]


async def test_stdio_permissions_demux_and_backend_history_cleanup(runtime):
    a, b = await asyncio.gather(collect(runtime, "first"), collect(runtime, "second"))
    assert "".join(e.get("text", "") for e in a) == "first"
    assert "".join(e.get("text", "") for e in b) == "second"
    assert a[-1]["usage"]["total_tokens"] == 5
    assert len(set(runtime.deleted)) == 2
    assert runtime.active == 0 and runtime.sessions == {} and runtime.pending == {}


async def test_client_closing_stream_cancels_and_deletes_session(runtime):
    generation = runtime.generate("opencode/test", "wait")
    first = await anext(generation)
    assert first["text"] == "w"
    await generation.aclose()
    assert len(runtime.deleted) == 1
    assert runtime.active == 0 and runtime.pending == {} and runtime.sessions == {}


async def test_stream_cleanup_survives_server_disconnect_cancel_scope(runtime):
    async with anyio.create_task_group() as group:

        async def consume():
            async with aclosing(runtime.generate("opencode/test", "wait")) as events:
                async for _ in events:
                    group.cancel_scope.cancel()
                    await anyio.sleep(0)

        group.start_soon(consume)
    assert len(runtime.deleted) == 1
    assert runtime.active == 0 and runtime.pending == {} and runtime.sessions == {}


async def test_rpc_error_sanitized_and_next_request_independent(runtime):
    with pytest.raises(GatewayError) as captured:
        await collect(runtime, "fail")
    assert captured.value.code == "upstream_denied"
    assert "secret-must-not-leak" not in str(captured.value)
    result = await collect(runtime, "next")
    assert result[-1]["type"] == "done"
    assert len(runtime.deleted) == 2


async def test_cleanup_failure_is_explicit(runtime):
    runtime.cleanup_failure = True
    with pytest.raises(GatewayError) as captured:
        await collect(runtime, "normal")
    assert captured.value.code == "session_cleanup_failed"
    assert not runtime.ready and runtime.active == 0
