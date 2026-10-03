"""Official stdio ACP, adapted from the existing MaiBot OpenCode plugin.

The HTTP sidecar is used only for health, catalog and history deletion.
Each request gets a distinct ACP session; output is demultiplexed by sessionId.
"""

import asyncio
import json
import os
import secrets
import socket
from contextlib import suppress

import anyio
import httpx

from .errors import GatewayError


def deny_request(message):
    response = {"jsonrpc": "2.0", "id": message["id"]}
    if message["method"] == "session/request_permission":
        response["result"] = {"outcome": {"outcome": "cancelled"}}
    else:
        response["error"] = {
            "code": -32601,
            "message": "Gateway does not expose files or terminals",
        }
    return response


def usage_from_acp(value):
    if not isinstance(value, dict):
        return None
    fields = (
        "inputTokens",
        "outputTokens",
        "cachedReadTokens",
        "cachedWriteTokens",
        "thoughtTokens",
    )
    if any(not isinstance(value.get(k, 0), int) or value.get(k, 0) < 0 for k in fields):
        raise GatewayError(502, "invalid_usage", "ACP returned invalid token usage")
    if "inputTokens" not in value or "outputTokens" not in value:
        return None
    prompt = (
        value["inputTokens"] + value.get("cachedReadTokens", 0) + value.get("cachedWriteTokens", 0)
    )
    completion = value["outputTokens"] + value.get("thoughtTokens", 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "prompt_tokens_details": {"cached_tokens": value.get("cachedReadTokens", 0)},
        "completion_tokens_details": {"reasoning_tokens": value.get("thoughtTokens", 0)},
    }


class Runtime:
    def __init__(self, channel, settings):
        self.channel, self.settings = channel, settings
        self.root = settings.data_dir / "runtimes" / channel["id"]
        self.workspace = self.root / "workspace"
        self.process = self.reader = self.http = None
        self.pending, self.sessions = {}, {}
        self.sequence = 0
        self.ready = False
        self.start_lock, self.send_lock = asyncio.Lock(), asyncio.Lock()
        self.semaphore = asyncio.Semaphore(channel["max_concurrency"])
        self.active = 0
        self.models, self.capabilities = [], {}
        self.version = None

    async def start(self):
        async with self.start_lock:
            if self.ready and self.process.returncode is None and not self.reader.done():
                return
            if self.active:
                raise GatewayError(
                    503, "channel_recovering", "Wait for active requests before restarting channel"
                )
            await self.close()
            self.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
            env = {
                k: v
                for k, v in os.environ.items()
                if k
                in {
                    "PATH",
                    "LANG",
                    "LC_ALL",
                    "LD_LIBRARY_PATH",
                    "SSL_CERT_FILE",
                    "SSL_CERT_DIR",
                    "SYSTEMROOT",
                    "SystemRoot",
                    "WINDIR",
                    "COMSPEC",
                    "PATHEXT",
                }
            }
            for name in (
                "HOME",
                "XDG_CONFIG_HOME",
                "XDG_DATA_HOME",
                "XDG_CACHE_HOME",
                "XDG_STATE_HOME",
                "TMPDIR",
                "TEMP",
                "TMP",
            ):
                directory = self.root / name.lower()
                directory.mkdir(exist_ok=True, mode=0o700)
                env[name] = str(directory.resolve())
            if os.name == "nt":
                env["USERPROFILE"] = env["HOME"]
                for name in ("APPDATA", "LOCALAPPDATA"):
                    directory = self.root / name.lower()
                    directory.mkdir(exist_ok=True, mode=0o700)
                    env[name] = str(directory.resolve())
            password = secrets.token_urlsafe(32)
            config = {
                "enabled_providers": self.channel["providers"],
                "share": "disabled",
                "autoupdate": False,
                "permission": {"*": "ask"},
            }
            credentials = self.channel.get("credentials", {})
            if credentials:
                config["provider"] = {
                    p: {"options": {"apiKey": key}} for p, key in credentials.items()
                }
            env.update(
                {
                    "OPENCODE_SERVER_PASSWORD": password,
                    "OPENCODE_DISABLE_AUTOUPDATE": "true",
                    "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
                    "OPENCODE_CONFIG_CONTENT": json.dumps(config),
                }
            )
            if self.channel.get("proxy_url"):
                env.update(
                    {
                        "HTTPS_PROXY": self.channel["proxy_url"],
                        "HTTP_PROXY": self.channel["proxy_url"],
                        "NO_PROXY": "127.0.0.1,localhost",
                    }
                )
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            self.base_url = f"http://127.0.0.1:{port}"
            try:
                self.process = await asyncio.create_subprocess_exec(
                    self.settings.binary,
                    "acp",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "ERROR",
                    cwd=self.workspace,
                    env=env,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=8 * 1024 * 1024,
                )
                self.reader = asyncio.create_task(self.read_loop())
                self.http = httpx.AsyncClient(
                    base_url=self.base_url, auth=("opencode", password), timeout=10, trust_env=False
                )
                async with asyncio.timeout(60):
                    while True:
                        if self.process.returncode is not None:
                            raise GatewayError(
                                503, "process_exited", "OpenCode exited during startup"
                            )
                        try:
                            health = await self.request("GET", "/global/health")
                            if health.get("healthy"):
                                break
                        except (httpx.HTTPError, GatewayError):
                            pass
                        await asyncio.sleep(0.25)
                initialized = await self.rpc(
                    "initialize",
                    {
                        "protocolVersion": 1,
                        "clientInfo": {"name": "OpenCode ACP Gateway", "version": "0.1.0"},
                        "clientCapabilities": {
                            "fs": {"readTextFile": False, "writeTextFile": False},
                            "terminal": False,
                        },
                    },
                    20,
                )
                if initialized.get("protocolVersion") != 1:
                    raise GatewayError(502, "protocol_mismatch", "Unsupported ACP protocol version")
                self.capabilities = initialized.get("agentCapabilities", {})
                self.version = health.get("version")
                catalog = await self.request("GET", "/provider")
                self.models = []
                for provider in catalog.get("all", []):
                    if provider["id"] not in self.channel["providers"]:
                        continue
                    for ident, model in provider.get("models", {}).items():
                        if model.get("status") == "deprecated":
                            continue
                        cost = model.get("cost", {})
                        free = cost.get("input") == 0 and cost.get("output") == 0
                        if self.channel["free_only"] and not free:
                            continue
                        upstream = provider["id"] + "/" + ident
                        self.models.append(
                            {
                                "id": upstream,
                                "upstream": upstream,
                                "name": model.get("name", ident),
                                "provider": provider["id"],
                                "free": free,
                                "context": model.get("limit", {}).get("context"),
                                "reasoning": model.get("capabilities", {}).get("reasoning", False),
                            }
                        )
                for alias, upstream in self.channel.get("aliases", {}).items():
                    original = next((m for m in self.models if m["upstream"] == upstream), None)
                    if not original:
                        raise GatewayError(
                            400,
                            "invalid_alias",
                            "Alias points to a model outside the channel catalog",
                        )
                    if not any(m["id"] == alias for m in self.models):
                        self.models.append({**original, "id": alias})
                self.ready = True
            except FileNotFoundError as exc:
                await self.close()
                raise GatewayError(
                    503,
                    "binary_missing",
                    "OpenCode executable not found; configure GATEWAY_OPENCODE_BINARY",
                ) from exc
            except TimeoutError as exc:
                await self.close()
                raise GatewayError(504, "startup_timeout", "OpenCode startup timed out") from exc
            except BaseException:
                await self.close()
                raise

    async def request(self, method, path):
        response = await self.http.request(method, path)
        if response.status_code >= 400:
            raise GatewayError(
                502, "sidecar_error", f"OpenCode local API returned HTTP {response.status_code}"
            )
        return response.json()

    async def send(self, message):
        async with self.send_lock:
            if not self.process or self.process.returncode is not None or not self.process.stdin:
                raise GatewayError(503, "process_unavailable", "OpenCode process is unavailable")
            self.process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
            await self.process.stdin.drain()

    async def rpc(self, method, params, timeout=None):
        self.sequence += 1
        ident = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        try:
            await self.send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
            return await asyncio.wait_for(future, timeout or self.channel["timeout_seconds"])
        finally:
            self.pending.pop(ident, None)

    async def read_loop(self):
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    raise GatewayError(503, "process_exited", "OpenCode process exited")
                message = json.loads(line)
                if "method" in message and "id" in message:
                    await self.send(deny_request(message))
                    continue
                if message.get("method") == "session/update":
                    params = message.get("params", {})
                    queue = self.sessions.get(params.get("sessionId"))
                    update = params.get("update", {})
                    kind = update.get("sessionUpdate")
                    if queue and kind in {"agent_message_chunk", "agent_thought_chunk"}:
                        content = update.get("content", {})
                        if content.get("type") == "text":
                            try:
                                queue.put_nowait(
                                    {
                                        "type": "text"
                                        if kind == "agent_message_chunk"
                                        else "reasoning",
                                        "text": content["text"],
                                    }
                                )
                            except asyncio.QueueFull:
                                raise GatewayError(
                                    502, "output_backpressure", "ACP output exceeded client buffer"
                                )
                    continue
                future = self.pending.get(message.get("id"))
                if future and not future.done():
                    if "error" in message:
                        error = message["error"]
                        code = (
                            "upstream_denied"
                            if "FreeTierError" in json.dumps(error)
                            else "acp_error"
                        )
                        future.set_exception(
                            GatewayError(
                                502,
                                code,
                                "OpenCode rejected the ACP request; check channel credentials, model access and upstream limits",
                            )
                        )
                    else:
                        future.set_result(message.get("result", {}))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.ready = False
            safe = (
                exc
                if isinstance(exc, GatewayError)
                else GatewayError(502, "protocol_error", "Invalid ACP response")
            )
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(safe)

    async def generate(self, upstream, prompt, effort=None):
        await self.start()
        async with self.semaphore:
            self.active += 1
            sid, task, queued = None, None, None
            cleanup_ok = True
            try:
                session = await self.rpc(
                    "session/new", {"cwd": str(self.workspace.resolve()), "mcpServers": []}
                )
                sid = session["sessionId"]
                selected = await self.rpc(
                    "session/set_config_option",
                    {"sessionId": sid, "configId": "model", "value": upstream},
                )
                if not any(
                    o["id"] == "model" and o.get("currentValue") == upstream
                    for o in selected.get("configOptions", [])
                ):
                    raise GatewayError(
                        502, "model_mismatch", "OpenCode did not select the requested model"
                    )
                if effort:
                    await self.rpc(
                        "session/set_config_option",
                        {"sessionId": sid, "configId": "effort", "value": effort},
                    )
                queue = asyncio.Queue(maxsize=256)
                self.sessions[sid] = queue
                task = asyncio.create_task(
                    self.rpc(
                        "session/prompt",
                        {"sessionId": sid, "prompt": [{"type": "text", "text": prompt}]},
                    )
                )
                total_bytes = 0
                while True:
                    queued = asyncio.create_task(queue.get())
                    await asyncio.wait({queued, task}, return_when=asyncio.FIRST_COMPLETED)
                    if queued.done():
                        event = queued.result()
                        total_bytes += len(event["text"].encode())
                        if total_bytes > self.settings.max_output_bytes:
                            raise GatewayError(
                                502, "output_too_large", "OpenCode output exceeds configured limit"
                            )
                        yield event
                        queued = None
                    else:
                        queued.cancel()
                        with suppress(asyncio.CancelledError):
                            await queued
                        queued = None
                    if task.done() and queue.empty():
                        result = task.result()
                        stop = result.get("stopReason")
                        if stop not in {"end_turn", "max_tokens", "refusal"}:
                            raise GatewayError(
                                502, "incomplete_response", "OpenCode did not complete the response"
                            )
                        yield {
                            "type": "done",
                            "stop": stop,
                            "usage": usage_from_acp(result.get("usage")),
                        }
                        break
            except TimeoutError as exc:
                raise GatewayError(504, "upstream_timeout", "OpenCode request timed out") from exc
            finally:
                with anyio.CancelScope(shield=True):
                    if queued:
                        queued.cancel()
                        with suppress(asyncio.CancelledError):
                            await queued
                    if task:
                        task.cancel()
                        with suppress(asyncio.CancelledError, Exception):
                            await task
                    if sid:
                        self.sessions.pop(sid, None)
                        try:
                            await self.send(
                                {
                                    "jsonrpc": "2.0",
                                    "method": "session/cancel",
                                    "params": {"sessionId": sid},
                                }
                            )
                            if "close" in self.capabilities.get("sessionCapabilities", {}):
                                await self.rpc("session/close", {"sessionId": sid}, 5)
                            await asyncio.wait_for(self.request("DELETE", f"/session/{sid}"), 5)
                        except Exception:
                            cleanup_ok = False
                            self.ready = False
                    self.active -= 1
                    if not cleanup_ok:
                        # Do not silently claim history deletion. Mark request failed.
                        raise GatewayError(
                            502,
                            "session_cleanup_failed",
                            "Temporary session cleanup failed; channel will restart before reuse",
                        )

    async def close(self):
        self.ready = False
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.reader:
            self.reader.cancel()
            with suppress(asyncio.CancelledError):
                await self.reader
        if self.http:
            await self.http.aclose()
        self.process = self.reader = self.http = None


class Pool:
    def __init__(self, store, settings, factory=Runtime):
        self.store, self.settings, self.factory = store, settings, factory
        self.runtimes = {}

    def get(self, channel):
        if channel["id"] not in self.runtimes:
            self.runtimes[channel["id"]] = self.factory(channel, self.settings)
        return self.runtimes[channel["id"]]

    async def invalidate(self, ident):
        runtime = self.runtimes.get(ident)
        with self.store.connection() as db:
            reserved = db.execute(
                "SELECT 1 FROM requests WHERE channel_id=? AND status='running' LIMIT 1", (ident,)
            ).fetchone()
        if reserved or (
            runtime
            and (
                runtime.active
                or getattr(runtime, "start_lock", None)
                and runtime.start_lock.locked()
            )
        ):
            raise GatewayError(
                409, "channel_busy", "Wait for active requests before changing channel"
            )
        if runtime:
            await runtime.close()
            self.runtimes.pop(ident, None)

    async def sync(self, ident):
        channel = self.store.channel(ident)
        runtime = self.get(channel)
        try:
            await runtime.start()
            self.store.sync_channel(ident, models=runtime.models)
            return {"models": runtime.models, "version": runtime.version}
        except GatewayError as exc:
            self.store.sync_channel(ident, error=exc.code)
            raise

    def select(self, model):
        for channel in sorted(self.store.channels(True), key=lambda c: (-c["priority"], c["id"])):
            if not channel["enabled"]:
                continue
            selected = next((m for m in channel["models"] if m["id"] == model), None)
            if selected:
                if (
                    selected["free"]
                    and selected["provider"] == "opencode"
                    and not channel["allow_training"]
                ):
                    raise GatewayError(
                        403,
                        "training_consent_required",
                        "Review the free provider data policy and enable consent on this channel",
                    )
                return self.get(channel), selected
        raise GatewayError(
            404, "model_not_found", "Model not found; enable and synchronize a channel"
        )

    async def close(self):
        for runtime in self.runtimes.values():
            await runtime.close()
