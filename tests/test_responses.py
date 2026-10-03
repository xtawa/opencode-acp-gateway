import asyncio
import importlib
import json

import pytest
from openai import AsyncOpenAI
from openai.types.responses import Response, ResponseStreamEvent
from pydantic import TypeAdapter

from gateway.protocol import build_prompt
from gateway.responses import Responses

from .conftest import FakeRuntime, chat


def request(content="你好世界", **options):
    return {"model": "opencode/test", "input": content, **options}


def events(result):
    parsed = []
    for block in result.text.strip().split("\n\n"):
        name, data = block.splitlines()
        value = json.loads(data.removeprefix("data: "))
        assert name == "event: " + value["type"]
        # Validate against the official SDK's discriminated event schemas.
        TypeAdapter(ResponseStreamEvent).validate_python(value)
        parsed.append(value)
    assert [e["sequence_number"] for e in parsed] == list(range(len(parsed)))
    return parsed


async def test_responses_auth_and_stateless_metadata(ready):
    client, _, _ = ready
    key = client.headers.pop("Authorization")
    assert (await client.post("/v1/responses", json=request())).status_code == 401
    client.headers["Authorization"] = key
    private = "private text must never reach SQLite"
    result = await client.post("/v1/responses", json=request(private))
    assert result.status_code == 200
    body = Response.model_validate(result.json())
    assert body.status == "completed" and body.output_text == private
    assert body.id.startswith("resp_") and result.headers["X-Request-Id"] == body.id
    assert body.usage.input_tokens == 12 and body.usage.total_tokens == 20
    assert result.json()["store"] is False
    assert private.encode() not in client.app.state.store.path.read_bytes()
    assert (await client.get("/api/settings")).json()["compatibility"]["responses"] is True


async def test_responses_stream_lifecycle_text_reasoning_and_usage(ready):
    client, _, _ = ready
    result = await client.post(
        "/v1/responses", json=request(stream=True, reasoning={"summary": "auto"})
    )
    parsed = events(result)
    assert [p["type"] for p in parsed[:2]] == ["response.created", "response.in_progress"]
    assert parsed[0]["response"]["output"] == []
    text = "".join(e["delta"] for e in parsed if e["type"] == "response.output_text.delta")
    assert text == "你好世界"
    assert parsed[-1]["type"] == "response.completed"
    body = Response.model_validate(parsed[-1]["response"])
    assert body.output_text == text and body.usage.total_tokens == 20
    assert body.output[0].summary[0].text == "简要推理"
    for index, item in enumerate(body.output):
        added = next(
            e
            for e in parsed
            if e["type"] == "response.output_item.added" and e["output_index"] == index
        )
        done = next(
            e
            for e in parsed
            if e["type"] == "response.output_item.done" and e["output_index"] == index
        )
        assert added["item"]["id"] == done["item"]["id"] == item.id
        assert added["item"]["status"] == "in_progress" and done["item"]["status"] == "completed"
    assert "[DONE]" not in result.text


@pytest.mark.parametrize("stream", [False, True])
async def test_responses_function_intents_and_history_roundtrip(ready, stream):
    client, _, _ = ready
    tools = [
        {
            "type": "function",
            "name": "weather",
            "description": "Weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
            "strict": True,
        }
    ]
    result = await client.post(
        "/v1/responses",
        json=request(
            "weather",
            tools=tools,
            tool_choice={"type": "function", "name": "weather"},
            stream=stream,
        ),
    )
    assert result.status_code == 200
    body = events(result)[-1]["response"] if stream else result.json()
    Response.model_validate(body)
    call = next(item for item in body["output"] if item["type"] == "function_call")
    assert call["name"] == "weather" and json.loads(call["arguments"]) == {"city": "杭州"}
    history = [
        {"role": "user", "content": "weather"},
        *body["output"],
        {"type": "function_call_output", "call_id": call["call_id"], "output": "Sunny"},
    ]
    reply = await client.post("/v1/responses", json=request(history))
    assert reply.status_code == 200 and Response.model_validate(reply.json()).output_text == "Sunny"


def test_responses_instructions_roles_and_text_parts_reach_bridge():
    data = Responses.model_validate(
        request(
            [
                {"role": "developer", "content": [{"type": "input_text", "text": "Rule"}]},
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "History", "annotations": []}],
                },
                {"role": "user", "content": [{"type": "input_text", "text": "Question"}]},
            ],
            instructions="System",
            reasoning={"effort": "high"},
        )
    )
    mapped = data.to_chat()
    payload = json.loads(build_prompt(mapped).split("API request JSON:\n")[1])
    assert [m["role"] for m in payload["messages"]] == ["system", "developer", "assistant", "user"]
    assert [m["content"] for m in payload["messages"]] == ["System", "Rule", "History", "Question"]
    assert mapped.reasoning_effort == "high"


@pytest.mark.parametrize("stream", [False, True])
async def test_responses_json_format_validation(ready, stream):
    client, _, _ = ready
    fmt = {
        "format": {
            "type": "json_schema",
            "name": "city",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    }
    result = await client.post(
        "/v1/responses", json=request('{"city":"杭州"}', text=fmt, stream=stream)
    )
    assert result.status_code == 200
    body = events(result)[-1]["response"] if stream else result.json()
    assert json.loads(Response.model_validate(body).output_text) == {"city": "杭州"}
    bad = await client.post("/v1/responses", json=request("invalid JSON", text=fmt, stream=stream))
    if stream:
        parsed = events(bad)
        assert parsed[-1]["type"] == "response.failed"
        assert not any(e["type"] == "response.output_text.delta" for e in parsed)
    else:
        assert bad.status_code == 502


@pytest.mark.parametrize(
    "options",
    [
        {"previous_response_id": "resp_previous"},
        {"store": True},
        {"background": True},
        {"conversation": "conv_one"},
        {"temperature": 0.5},
        {"max_output_tokens": 10},
        {"include": ["reasoning.encrypted_content"]},
        {"tools": [{"type": "web_search"}]},
        {
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_image", "image_url": "https://example.com/a.png"}],
                }
            ]
        },
        {
            "input": [
                {"type": "function_call", "call_id": "call_1", "name": "x", "arguments": "not JSON"}
            ]
        },
        {"tools": [{"type": "function", "name": "bad", "parameters": {"type": "invalid"}}]},
        {"reasoning": {"summary": []}},
        {"text": {"format": {"type": "json_schema", "schema": {"type": "object"}}}},
        {"tools": [{"type": "function", "name": "x", "strict": "true"}]},
    ],
)
async def test_responses_unsupported_fields_rejected_before_quota(ready, options):
    client, _, _ = ready
    result = await client.post("/v1/responses", json=request(**options))
    assert result.status_code == 400
    assert client.app.state.store.overview()["requests"] == 0


async def test_responses_and_chat_share_limits_and_model_scope(ready):
    client, _, key_id = ready
    await client.put("/api/keys/" + key_id, json={"name": "One request", "daily_requests": 1})
    results = await asyncio.gather(
        client.post("/v1/responses", json=request("slow")),
        client.post("/v1/chat/completions", json=chat("slow")),
    )
    assert sorted(r.status_code for r in results) == [200, 429]
    assert client.app.state.store.overview()["active"] == 0
    await client.put(
        "/api/keys/" + key_id, json={"name": "Restricted", "allowed_models": ["other"]}
    )
    assert (await client.post("/v1/responses", json=request())).status_code == 403


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("content,status", [("error", 502), ("timeout", 504)])
async def test_responses_errors_close_sessions_and_release_quota(ready, stream, content, status):
    client, _, _ = ready
    before = FakeRuntime.closed_sessions
    result = await client.post("/v1/responses", json=request(content, stream=stream))
    if stream:
        parsed = events(result)
        assert parsed[-1]["type"] == "response.failed"
        assert not any(e["type"] == "response.completed" for e in parsed)
    else:
        assert result.status_code == status
    assert FakeRuntime.closed_sessions == before + 1
    assert client.app.state.store.overview()["active"] == 0


async def test_responses_cancellation_closes_generator(ready, monkeypatch):
    client, _, _ = ready
    started, closed = asyncio.Event(), asyncio.Event()

    async def generate(self, *args):
        try:
            started.set()
            yield {"type": "text", "text": "partial"}
            await asyncio.Future()
        finally:
            closed.set()

    monkeypatch.setattr(FakeRuntime, "generate", generate)
    task = asyncio.create_task(client.post("/v1/responses", json=request(stream=True)))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set() and client.app.state.store.overview()["active"] == 0
    assert client.app.state.store.logs()["items"][0]["status"] == "cancelled"


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "stop,reason", [("max_tokens", "max_output_tokens"), ("refusal", "content_filter")]
)
async def test_responses_incomplete_and_missing_usage(ready, monkeypatch, stream, stop, reason):
    client, _, _ = ready
    original = FakeRuntime.generate

    async def generate(self, *args):
        async for event in original(self, *args):
            if event["type"] == "done":
                event = {**event, "stop": stop, "usage": None}
            yield event

    monkeypatch.setattr(FakeRuntime, "generate", generate)
    result = await client.post("/v1/responses", json=request(stream=stream))
    body = events(result)[-1]["response"] if stream else result.json()
    parsed = Response.model_validate(body)
    assert parsed.status == "incomplete" and parsed.incomplete_details.reason == reason
    assert parsed.usage is None and parsed.output_text == "你好世界"


async def test_responses_cleanup_failure_never_reports_completion(ready, monkeypatch):
    from gateway.errors import GatewayError

    client, _, _ = ready
    original = FakeRuntime.generate

    async def generate(self, *args):
        async for event in original(self, *args):
            yield event
        raise GatewayError(502, "session_cleanup_failed", "Session cleanup failed")

    monkeypatch.setattr(FakeRuntime, "generate", generate)
    result = await client.post("/v1/responses", json=request(stream=True))
    parsed = events(result)
    assert parsed[-1]["type"] == "response.failed"
    assert parsed[-2]["code"] == "session_cleanup_failed"
    assert not any(e["type"] == "response.completed" for e in parsed)
    assert client.app.state.store.logs()["items"][0]["status"] == "error"


async def test_official_sdk_create_and_stream_accumulator(ready):
    client, _, _ = ready
    # SDK 3 uses httpx2; SDK 2 uses httpx. Both expose the same ASGI transport.
    http = importlib.import_module(
        "httpx2" if int(__import__("openai").__version__.split(".")[0]) >= 3 else "httpx"
    )
    async with AsyncOpenAI(
        api_key=client.headers["Authorization"].removeprefix("Bearer "),
        base_url="http://test/v1",
        http_client=http.AsyncClient(transport=http.ASGITransport(app=client.app)),
        max_retries=0,
        _strict_response_validation=True,
    ) as sdk:
        first, second = await asyncio.gather(
            sdk.responses.create(**request("one")), sdk.responses.create(**request("two"))
        )
        assert first.output_text == "one" and second.output_text == "two" and first.id != second.id
        async with sdk.responses.stream(
            **request("SDK streaming", reasoning={"summary": "auto"})
        ) as stream:
            chunks = [e.delta async for e in stream if e.type == "response.output_text.delta"]
            final = await stream.get_final_response()
        assert "".join(chunks) == final.output_text == "SDK streaming"
        assert final.status == "completed" and final.usage.total_tokens == 20
