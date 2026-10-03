import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from gateway.acp import deny_request, usage_from_acp
from gateway.errors import GatewayError
from gateway.protocol import build_prompt, decode_message
from gateway.schemas import Chat, Key

from .conftest import FakeRuntime, chat


async def test_initialization_requires_local_bootstrap_and_is_once(client):
    assert (await client.get("/api/setup")).json() == {"initialized": False}
    assert (
        await client.post(
            "/api/setup",
            json={
                "username": "admin",
                "password": "a" * 12,
                "bootstrap_token": "wrong-token-123456",
            },
        )
    ).status_code == 403
    assert (
        await client.post(
            "/api/setup",
            json={
                "username": "admin",
                "password": "a" * 12,
                "bootstrap_token": "fixture-bootstrap-token",
            },
        )
    ).status_code == 200
    assert (await client.post("/api/setup", json={})).status_code == 409


async def test_admin_auth_csrf_and_origin(admin):
    csrf = admin.headers.pop("X-CSRF-Token")
    assert (await admin.post("/api/keys", json={"name": "x"})).status_code == 403
    admin.headers["X-CSRF-Token"] = csrf
    assert (
        await admin.post("/api/keys", headers={"Origin": "http://evil.example"}, json={"name": "x"})
    ).status_code == 403
    assert (await admin.get("/api/keys")).status_code == 200
    assert (await admin.post("/api/logout")).status_code == 200
    assert (await admin.get("/api/me")).status_code == 401
    assert (
        await admin.post(
            "/api/login", json={"username": "admin", "password": "fixture-password-123"}
        )
    ).status_code == 200


async def test_password_change_invalidates_sessions(admin):
    assert (
        await admin.post(
            "/api/password", json={"current_password": "wrong", "password": "new-fixture-password"}
        )
    ).status_code == 403
    assert (await admin.get("/api/me")).status_code == 200
    assert (
        await admin.post(
            "/api/password",
            json={"current_password": "fixture-password-123", "password": "new-fixture-password"},
        )
    ).status_code == 200
    assert (await admin.get("/api/me")).status_code == 401
    assert (
        await admin.post(
            "/api/login", json={"username": "admin", "password": "fixture-password-123"}
        )
    ).status_code == 401
    assert (
        await admin.post(
            "/api/login", json={"username": "admin", "password": "new-fixture-password"}
        )
    ).status_code == 200


async def test_key_required_and_raw_secret_not_retrievable(admin):
    assert (await admin.get("/v1/models")).status_code == 401
    key = (await admin.post("/api/keys", json={"name": "x"})).json()
    assert key["key"].startswith("sk-acp-")
    assert key["key"] not in (await admin.get("/api/keys")).text
    assert key["key"].encode() not in admin.app.state.store.path.read_bytes()
    admin.headers["Authorization"] = "Bearer " + key["key"]
    assert (await admin.get("/v1/models")).status_code == 200
    await admin.delete("/api/keys/" + key["id"])
    assert (await admin.get("/v1/models")).status_code == 401


async def test_channel_credentials_and_proxy_encrypted(admin):
    secret, proxy = "fixture-upstream-secret", "http://user:proxy-secret@127.0.0.1:7890"
    ident = (
        await admin.post(
            "/api/channels",
            json={"name": "x", "credentials": {"opencode": secret}, "proxy_url": proxy},
        )
    ).json()["id"]
    listing = (await admin.get("/api/channels")).text
    assert secret not in listing and "proxy-secret" not in listing
    private = admin.app.state.store.channel(ident)
    assert private["credentials"]["opencode"] == secret and private["proxy_url"] == proxy
    with admin.app.state.store.connection() as db:
        row = dict(db.execute("SELECT * FROM channels").fetchone())
    assert secret not in str(row) and "proxy-secret" not in str(row)
    await admin.put("/api/channels/" + ident, json={"name": "updated", "proxy_url": ""})
    assert admin.app.state.store.channel(ident)["proxy_url"] == proxy
    await admin.put(
        "/api/channels/" + ident, json={"name": "updated", "credentials": {}, "proxy_url": "-"}
    )
    assert admin.app.state.store.channel(ident)["credentials"] == {}
    assert admin.app.state.store.channel(ident).get("proxy_url", "") == ""


async def test_model_catalog_chat_and_metadata_log(ready):
    client, ident, _ = ready
    assert (await client.get("/v1/models")).json()["data"][0]["id"] == "opencode/test"
    content = "unique private content"
    result = await client.post("/v1/chat/completions", json=chat(content))
    assert result.status_code == 200
    body = result.json()
    assert body["choices"][0]["message"]["content"] == content
    assert body["usage"]["total_tokens"] == 20
    logs = (await client.get("/api/logs")).json()
    assert logs["total"] == 1 and logs["items"][0]["status"] == "success"
    assert logs["items"][0]["channel_id"] == ident
    assert (
        content not in json.dumps(logs)
        and content.encode() not in client.app.state.store.path.read_bytes()
    )


async def test_stream_chunks_and_usage(ready):
    client, _, _ = ready
    result = await client.post(
        "/v1/chat/completions",
        json=chat("你好世界", stream=True, stream_options={"include_usage": True}),
    )
    assert result.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(x[6:])
        for x in result.text.split("\n\n")
        if x.startswith("data: ") and x != "data: [DONE]"
    ]
    text = "".join(
        e.get("choices", [{}])[0].get("delta", {}).get("content", "")
        for e in events
        if e["choices"]
    )
    assert text == "你好世界" and events[-1]["usage"]["total_tokens"] == 20
    assert events[-2]["choices"][0]["finish_reason"] == "stop"
    assert result.text.endswith("data: [DONE]\n\n")


@pytest.mark.parametrize("stream", [True, False])
async def test_tools_validate_and_map_function_intents(ready, stream):
    client, _, _ = ready
    result = await client.post(
        "/v1/chat/completions",
        json=chat(
            "weather",
            stream=stream,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                        },
                    },
                }
            ],
            tool_choice="required",
        ),
    )
    assert result.status_code == 200
    assert "tool_calls" in result.text and "杭州" in result.text


async def test_limits_expiry_model_scope_and_concurrent_reservation(ready):
    client, _, key_id = ready
    await client.put("/api/keys/" + key_id, json={"name": "limited", "daily_requests": 1})
    results = await asyncio.gather(
        *(client.post("/v1/chat/completions", json=chat("slow")) for _ in range(3))
    )
    assert sorted(r.status_code for r in results) == [200, 429, 429]
    await client.put("/api/keys/" + key_id, json={"name": "limited", "allowed_models": ["other"]})
    assert (await client.post("/v1/chat/completions", json=chat())).status_code == 403
    assert not (await client.get("/v1/models")).json()["data"]
    await client.put(
        "/api/keys/" + key_id, json={"name": "limited", "expires_at": int(time.time()) - 1}
    )
    assert (await client.get("/v1/models")).status_code == 401


async def test_atomic_reservation_across_threads(ready):
    client, channel_id, key_id = ready
    store = client.app.state.store
    config = Key(name="single", max_concurrency=1).model_dump()
    store.update_key(key_id, config)
    key = {**config, "id": key_id}

    def reserve(i):
        try:
            store.reserve(key, str(i), channel_id, "opencode/test")
            return "ok"
        except GatewayError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=8) as workers:
        result = list(workers.map(reserve, range(8)))
    assert result.count("ok") == 1


async def test_upstream_error_and_timeout_release_quota(ready):
    client, _, _ = ready
    for content in ("error", "timeout"):
        result = await client.post("/v1/chat/completions", json=chat(content))
        assert result.status_code in (502, 504)
    assert client.app.state.store.overview()["active"] == 0
    result = await client.post("/v1/chat/completions", json=chat("error", stream=True))
    assert '"error"' in result.text and '"finish_reason": "stop"' not in result.text


@pytest.mark.parametrize(
    "extra",
    [
        {"temperature": 0.4},
        {"max_tokens": 40},
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
                    ],
                }
            ]
        },
    ],
)
async def test_unsupported_options_rejected(ready, extra):
    client, _, _ = ready
    request = {**chat(), **extra}
    assert (await client.post("/v1/chat/completions", json=request)).status_code == 400


@pytest.mark.parametrize(
    "extra",
    [
        {
            "tools": [
                {"type": "function", "function": {"name": "bad", "parameters": {"type": "invalid"}}}
            ]
        },
        {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"schema": {"type": "invalid"}},
            }
        },
        {"response_format": {"type": "json_schema", "json_schema": []}},
        {"tool_choice": {"type": "function", "function": []}},
    ],
)
async def test_invalid_schemas_return_400_without_consuming_quota(ready, extra):
    client, _, _ = ready
    assert (await client.post("/v1/chat/completions", json={**chat(), **extra})).status_code == 400
    assert client.app.state.store.overview()["requests"] == 0


async def test_channel_edit_rejects_reserved_request_before_runtime_start(ready):
    client, channel_id, key_id = ready
    store = client.app.state.store
    key = next(k for k in store.keys() if k["id"] == key_id)
    store.reserve(key, "queued", channel_id, "opencode/test")
    response = await client.put("/api/channels/" + channel_id, json={"name": "Changed"})
    assert response.status_code == 409
    assert store.channel(channel_id)["name"] == "Fixture"


async def test_free_channel_consent_and_disabled_channel(ready):
    client, ident, _ = ready
    await client.put("/api/channels/" + ident, json={"name": "Fixture", "allow_training": False})
    await client.post("/api/channels/" + ident + "/sync")
    assert (await client.post("/v1/chat/completions", json=chat())).status_code == 403
    await client.put("/api/channels/" + ident, json={"name": "Fixture", "enabled": False})
    await client.post("/api/channels/" + ident + "/sync")
    assert (await client.post("/v1/chat/completions", json=chat())).status_code == 404


async def test_client_history_isolated_per_call(ready):
    client, _, _ = ready
    before = FakeRuntime.closed_sessions
    first, second = await asyncio.gather(
        client.post("/v1/chat/completions", json=chat("one")),
        client.post("/v1/chat/completions", json=chat("two")),
    )
    assert first.json()["choices"][0]["message"]["content"] == "one"
    assert second.json()["choices"][0]["message"]["content"] == "two"
    assert FakeRuntime.closed_sessions == before + 2


async def test_body_size_and_security_headers(client):
    result = await client.post("/api/setup", content=b"x" * (2 * 1024 * 1024 + 1))
    assert result.status_code == 413
    response = await client.get("/api/setup")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"


def test_usage_cache_and_reasoning_are_real():
    usage = usage_from_acp(
        {
            "inputTokens": 5,
            "outputTokens": 7,
            "cachedReadTokens": 11,
            "cachedWriteTokens": 3,
            "thoughtTokens": 2,
            "totalTokens": 28,
        }
    )
    assert (
        usage["prompt_tokens"] == 19
        and usage["completion_tokens"] == 9
        and usage["total_tokens"] == 28
    )
    assert usage_from_acp(None) is None
    with pytest.raises(GatewayError):
        usage_from_acp({"inputTokens": -1, "outputTokens": 2})


def test_role_boundaries_and_invalid_json():
    request = Chat.model_validate(chat("untrusted message"))
    prompt = build_prompt(request)
    assert json.loads(prompt.split("API request JSON:\n")[1])["messages"][0]["role"] == "user"
    json_request = Chat.model_validate(chat(response_format={"type": "json_object"}))
    with pytest.raises(GatewayError):
        decode_message(json_request, "not JSON")


def test_permissions_cancel_and_files_denied():
    assert (
        deny_request({"id": 1, "method": "session/request_permission"})["result"]["outcome"][
            "outcome"
        ]
        == "cancelled"
    )
    assert deny_request({"id": 2, "method": "fs/read_text_file"})["error"]["code"] == -32601
