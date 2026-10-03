import asyncio
import hmac
import json
import secrets
import time
import uuid
from collections import defaultdict, deque
from contextlib import aclosing, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import __version__
from .acp import Pool
from .config import Settings
from .errors import GatewayError
from .protocol import build_prompt, decode_message
from .responses import Responses, ResponsesOutput
from .schemas import Channel, Chat, Credentials, Key, PasswordChange, Setup
from .security import csrf_token, password_ok
from .store import Store


def create_app(settings=None, runtime_factory=None):
    settings = settings or Settings.from_env()
    store = Store(settings.data_dir)
    pool = Pool(store, settings, **({"factory": runtime_factory} if runtime_factory else {}))
    bootstrap_path = settings.data_dir / "bootstrap-token"
    if not store.get_admin() and not settings.bootstrap_token and not bootstrap_path.exists():
        with bootstrap_path.open("x") as f:
            f.write(secrets.token_urlsafe(32))
        bootstrap_path.chmod(0o600)
    login_attempts = defaultdict(deque)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await pool.close()

    app = FastAPI(
        title="OpenCode ACP Gateway",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.store, app.state.pool = store, pool

    @app.exception_handler(GatewayError)
    async def error_handler(request, error):
        return JSONResponse(
            error.payload(),
            status_code=error.status,
            headers={"Retry-After": "60"} if error.status == 429 else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, error):
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_request",
                    "message": "Invalid request fields",
                    "type": "invalid_request_error",
                }
            },
            status_code=400,
        )

    @app.middleware("http")
    async def security_headers(request, call_next):
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > settings.max_body_bytes:
            return JSONResponse(
                {"error": {"code": "body_too_large", "message": "Request exceeds body limit"}},
                status_code=413,
            )
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "same-origin",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'",
            }
        )
        if request.url.path.startswith(("/api/", "/v1/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    async def parse(request, schema):
        size, chunks = 0, []
        async for chunk in request.stream():
            size += len(chunk)
            if size > settings.max_body_bytes:
                raise GatewayError(413, "body_too_large", "Request exceeds body limit")
            chunks.append(chunk)
        try:
            return schema.model_validate_json(b"".join(chunks))
        except (ValidationError, ValueError) as exc:
            # Pydantic errors contain input values; never return them to logs/client.
            raise GatewayError(
                400,
                "invalid_request",
                "Invalid request or unsupported fields; check API documentation",
            ) from exc

    def origin_ok(request):
        origin = request.headers.get("origin")
        expected = settings.public_origin or str(request.base_url).rstrip("/")
        if origin and origin != expected:
            raise GatewayError(403, "origin_rejected", "Request origin rejected")

    def admin(request):
        cookie = request.cookies.get("acp_session", "")
        if not cookie or not store.session(cookie):
            raise GatewayError(401, "login_required", "Administrator login required")
        if request.method not in {"GET", "HEAD"}:
            origin_ok(request)
            expected = csrf_token(cookie, store.secret)
            if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), expected):
                raise GatewayError(403, "csrf_rejected", "CSRF token required")
        return cookie

    def api_key(request):
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise GatewayError(401, "api_key_required", "Authorization: Bearer API_KEY is required")
        return store.authenticate_key(authorization[7:])

    def login_limit(request):
        ident = request.client.host if request.client else "unknown"
        now = time.monotonic()
        attempts = login_attempts[ident]
        while attempts and attempts[0] < now - 300:
            attempts.popleft()
        if len(attempts) >= 10:
            raise GatewayError(429, "login_rate_limit", "Too many login attempts; retry later")
        attempts.append(now)
        if len(login_attempts) > 10000:
            login_attempts.clear()

    def set_session(response, raw):
        response.set_cookie(
            "acp_session",
            raw,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="strict",
            max_age=86400,
            path="/",
        )

    @app.get("/healthz")
    async def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/setup")
    async def setup_status():
        return {"initialized": bool(store.get_admin())}

    @app.post("/api/setup")
    async def setup(request: Request):
        origin_ok(request)
        login_limit(request)
        if store.get_admin():
            raise GatewayError(409, "already_initialized", "Administrator already exists")
        data = await parse(request, Setup)
        expected = settings.bootstrap_token or bootstrap_path.read_text()
        if not hmac.compare_digest(data.bootstrap_token, expected):
            raise GatewayError(403, "invalid_bootstrap_token", "Invalid bootstrap token")
        store.setup(data.username, data.password)
        bootstrap_path.unlink(missing_ok=True)
        raw = store.login()
        response = JSONResponse(
            {"username": data.username, "csrf_token": csrf_token(raw, store.secret)}
        )
        set_session(response, raw)
        return response

    @app.post("/api/login")
    async def login(request: Request):
        origin_ok(request)
        login_limit(request)
        data = await parse(request, Credentials)
        account = store.get_admin()
        if (
            not account
            or not hmac.compare_digest(data.username, account["username"])
            or not password_ok(data.password, account["password"])
        ):
            raise GatewayError(401, "invalid_credentials", "Invalid username or password")
        raw = store.login()
        response = JSONResponse(
            {"username": account["username"], "csrf_token": csrf_token(raw, store.secret)}
        )
        set_session(response, raw)
        store.audit("login", account["username"])
        return response

    @app.get("/api/me")
    async def me(request: Request):
        cookie = admin(request)
        return {
            "username": store.get_admin()["username"],
            "csrf_token": csrf_token(cookie, store.secret),
        }

    @app.post("/api/logout")
    async def logout(request: Request):
        store.logout(admin(request))
        response = JSONResponse({"ok": True})
        response.delete_cookie("acp_session", path="/")
        return response

    @app.post("/api/password")
    async def change_password(request: Request):
        admin(request)
        data = await parse(request, PasswordChange)
        if not password_ok(data.current_password, store.get_admin()["password"]):
            raise GatewayError(403, "password_mismatch", "Current password is incorrect")
        from .security import password_hash

        with store.connection() as db:
            db.execute("UPDATE admin SET password=? WHERE id=1", (password_hash(data.password),))
            db.execute("DELETE FROM sessions")
        store.audit("password_changed", store.get_admin()["username"])
        return {"ok": True}

    @app.get("/api/overview")
    async def overview(request: Request):
        admin(request)
        return store.overview()

    @app.get("/api/settings")
    async def configuration(request: Request):
        admin(request)
        return {
            "version": __version__,
            "secure_cookies": settings.secure_cookies,
            "public_origin": settings.public_origin,
            "max_body_bytes": settings.max_body_bytes,
            "usage_timezone": "UTC",
            "log_policy": "metadata_only",
            "compatibility": {
                "chat_completions": True,
                "streaming": True,
                "function_intents": True,
                "json_output": True,
                "reasoning": True,
                "temperature": False,
                "max_tokens": False,
                "vision": False,
                "embeddings": False,
                "responses": True,
            },
        }

    @app.get("/api/audit")
    async def audit(request: Request):
        admin(request)
        with store.connection() as db:
            return {
                "items": [
                    dict(r) for r in db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 100")
                ]
            }

    @app.get("/api/channels")
    async def channels(request: Request):
        admin(request)
        return {"items": store.channels()}

    @app.post("/api/channels")
    async def add_channel(request: Request):
        admin(request)
        data = await parse(request, Channel)
        if len(store.channels()) >= 20:
            raise GatewayError(400, "channel_limit", "Maximum 20 channels")
        ident = secrets.token_hex(8)
        store.save_channel(ident, data.model_dump())
        return {"id": ident}

    @app.put("/api/channels/{ident}")
    async def update_channel(ident: str, request: Request):
        admin(request)
        store.channel(ident)
        data = await parse(request, Channel)
        await pool.invalidate(ident)
        store.save_channel(ident, data.model_dump())
        return {"ok": True}

    @app.delete("/api/channels/{ident}")
    async def delete_channel(ident: str, request: Request):
        admin(request)
        store.channel(ident)
        await pool.invalidate(ident)
        store.delete_channel(ident)
        return {"ok": True}

    @app.post("/api/channels/{ident}/sync")
    async def sync_channel(ident: str, request: Request):
        admin(request)
        return await pool.sync(ident)

    @app.post("/api/channels/{ident}/test")
    async def test_channel(ident: str, request: Request):
        admin(request)
        data = await parse(request, Chat)
        channel = store.channel(ident)
        selected = next((m for m in channel["models"] if m["id"] == data.model), None)
        if not selected:
            raise GatewayError(404, "model_not_found", "Model not synchronized on this channel")
        if (
            selected["free"]
            and selected["provider"] == "opencode"
            and not channel["allow_training"]
        ):
            raise GatewayError(
                403, "training_consent_required", "Review and accept the free provider data policy"
            )
        text, reasoning, done = [], [], None
        async for event in pool.get(channel).generate(
            selected["upstream"], build_prompt(data), data.reasoning_effort
        ):
            if event["type"] == "done":
                done = event
            else:
                (text if event["type"] == "text" else reasoning).append(event["text"])
        return {
            "message": decode_message(data, "".join(text), "".join(reasoning)),
            "usage": done["usage"],
            "stop": done["stop"],
        }

    @app.get("/api/keys")
    async def keys(request: Request):
        admin(request)
        return {"items": store.keys()}

    @app.post("/api/keys")
    async def create_key(request: Request):
        admin(request)
        data = await parse(request, Key)
        return store.create_key(data.model_dump())

    @app.put("/api/keys/{ident}")
    async def update_key(ident: str, request: Request):
        admin(request)
        data = await parse(request, Key)
        store.update_key(ident, data.model_dump())
        return {"ok": True}

    @app.delete("/api/keys/{ident}")
    async def revoke_key(ident: str, request: Request):
        admin(request)
        store.revoke_key(ident)
        return {"ok": True}

    @app.get("/api/logs")
    async def logs(
        request: Request, limit: int = 50, offset: int = 0, status: str = "", model: str = ""
    ):
        admin(request)
        return store.logs(max(1, min(limit, 200)), max(0, offset), status, model)

    @app.get("/v1/models")
    async def models(request: Request):
        key = api_key(request)
        available = {}
        for channel in store.channels():
            if channel["enabled"]:
                for model in channel["models"]:
                    if not key["allowed_models"] or model["id"] in key["allowed_models"]:
                        available[model["id"]] = {
                            "id": model["id"],
                            "object": "model",
                            "created": 0,
                            "owned_by": model["provider"],
                        }
        return {"object": "list", "data": list(available.values())}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        key = api_key(request)
        data = await parse(request, Chat)
        return await complete(request, key, data)

    @app.post("/v1/responses")
    async def responses(request: Request):
        key = api_key(request)
        data = await parse(request, Responses)
        return await complete(request, key, data.to_chat(), data)

    async def complete(request, key, data, responses_data=None):
        if key["allowed_models"] and data.model not in key["allowed_models"]:
            raise GatewayError(403, "model_forbidden", "API key cannot access this model")
        runtime, selected = pool.select(data.model)
        ident = ("resp_" if responses_data else "chatcmpl-") + uuid.uuid4().hex
        started = time.monotonic()
        store.reserve(key, ident, runtime.channel["id"], data.model)
        created = int(time.time())
        base = {"id": ident, "created": created, "model": data.model}
        output = ResponsesOutput(responses_data, ident, created) if responses_data else None

        def chunk(delta, finish=None, usage=None):
            if output:
                return output.delta(delta)
            payload = {
                **base,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            if usage is not None:
                payload["usage"] = usage
                payload["choices"] = []
            return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

        async def execute(streaming=False):
            text, reasoning, done, ttft = [], [], None, None
            structured = bool(data.tools and data.tool_choice != "none") or bool(
                data.response_format and data.response_format["type"] != "text"
            )
            succeeded = False
            try:
                async with asyncio.timeout(runtime.channel["timeout_seconds"] + 65):
                    async with aclosing(
                        runtime.generate(
                            selected["upstream"], build_prompt(data), data.reasoning_effort
                        )
                    ) as generation:
                        async for event in generation:
                            if await request.is_disconnected():
                                raise asyncio.CancelledError()
                            if event["type"] == "done":
                                done = event
                                continue
                            if ttft is None:
                                ttft = int((time.monotonic() - started) * 1000)
                            (text if event["type"] == "text" else reasoning).append(event["text"])
                            if streaming and not structured:
                                yield chunk(
                                    {
                                        "content"
                                        if event["type"] == "text"
                                        else "reasoning_content": event["text"]
                                    }
                                )
                if not done:
                    raise GatewayError(
                        502, "empty_response", "ACP did not return a completion result"
                    )
                message = decode_message(data, "".join(text), "".join(reasoning))
                finish = (
                    "tool_calls"
                    if message.get("tool_calls")
                    else {"max_tokens": "length", "refusal": "content_filter"}.get(
                        done["stop"], "stop"
                    )
                )
                if structured and done["stop"] != "end_turn":
                    raise GatewayError(
                        502, "incomplete_json", "Structured response did not complete"
                    )
                duration = int((time.monotonic() - started) * 1000)
                store.finish(ident, "success", duration, done["usage"], ttft_ms=ttft)
                succeeded = True
                if streaming:
                    if output:
                        yield output.finish(message, done["usage"], done["stop"], structured)
                        return
                    if structured:
                        delta = {k: v for k, v in message.items() if k != "role"}
                        if "tool_calls" in delta:
                            delta["tool_calls"] = [
                                {"index": i, **c} for i, c in enumerate(delta["tool_calls"])
                            ]
                        yield chunk(delta)
                    yield chunk({}, finish)
                    if data.stream_options and data.stream_options.get("include_usage"):
                        if done["usage"] is not None:
                            yield chunk({}, usage=done["usage"])
                    yield "data: [DONE]\n\n"
                else:
                    if output:
                        yield output.result(message, done["usage"], done["stop"])
                        return
                    response = {
                        **base,
                        "object": "chat.completion",
                        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                    }
                    if done["usage"] is not None:
                        response["usage"] = done["usage"]
                    yield response
            except asyncio.CancelledError:
                store.finish(
                    ident,
                    "cancelled",
                    int((time.monotonic() - started) * 1000),
                    code="client_disconnected",
                    ttft_ms=ttft,
                )
                raise
            except Exception as exc:
                error = (
                    exc
                    if isinstance(exc, GatewayError)
                    else GatewayError(
                        504 if isinstance(exc, TimeoutError) else 502,
                        "upstream_timeout" if isinstance(exc, TimeoutError) else "upstream_error",
                        "OpenCode request failed",
                    )
                )
                store.finish(
                    ident,
                    "error",
                    int((time.monotonic() - started) * 1000),
                    code=error.code,
                    ttft_ms=ttft,
                )
                if streaming:
                    if output:
                        yield output.error(error)
                    else:
                        yield "data: " + json.dumps(error.payload()) + "\n\n"
                        yield "data: [DONE]\n\n"
                else:
                    raise error from exc
            finally:
                if not succeeded:
                    store.finish(
                        ident,
                        "cancelled",
                        int((time.monotonic() - started) * 1000),
                        code="request_abandoned",
                        ttft_ms=ttft,
                    )

        if data.stream:

            async def events():
                try:
                    yield output.start() if output else chunk({"role": "assistant", "content": ""})
                    async with aclosing(execute(True)) as execution:
                        async for event in execution:
                            yield event
                finally:
                    store.finish(
                        ident,
                        "cancelled",
                        int((time.monotonic() - started) * 1000),
                        code="client_disconnected",
                    )

            return StreamingResponse(
                events(),
                media_type="text/event-stream",
                headers={"X-Accel-Buffering": "no", "X-Request-Id": ident},
            )
        async for response in execute():
            return JSONResponse(response, headers={"X-Request-Id": ident})

    if settings.web_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=settings.web_dir / "assets"), name="assets")

        @app.get("/{path:path}")
        async def frontend(path: str):
            if path.startswith(("api/", "v1/")):
                raise GatewayError(404, "endpoint_not_found", "Endpoint not found")
            return FileResponse(settings.web_dir / "index.html")

    return app
