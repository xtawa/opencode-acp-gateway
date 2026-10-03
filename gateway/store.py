import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet

from .errors import GatewayError
from .security import digest, password_hash


class Store:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = root / "gateway.db"
        keyfile = root / "encryption.key"
        if not keyfile.exists():
            with keyfile.open("xb") as f:
                f.write(Fernet.generate_key())
            keyfile.chmod(0o600)
        self.secret = keyfile.read_bytes()
        self.cipher = Fernet(self.secret)
        with self.connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS admin(id INTEGER PRIMARY KEY CHECK(id=1), username TEXT UNIQUE, password TEXT);
            CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, expires INTEGER);
            CREATE TABLE IF NOT EXISTS channels(id TEXT PRIMARY KEY, config TEXT NOT NULL, credentials TEXT NOT NULL, models TEXT NOT NULL DEFAULT '[]', synced INTEGER, error TEXT);
            CREATE TABLE IF NOT EXISTS api_keys(id TEXT PRIMARY KEY, hash TEXT UNIQUE NOT NULL, prefix TEXT, config TEXT NOT NULL, created INTEGER);
            CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, key_id TEXT, channel_id TEXT, model TEXT, started INTEGER, duration_ms INTEGER, status TEXT, code TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, ttft_ms INTEGER);
            CREATE INDEX IF NOT EXISTS requests_key_time ON requests(key_id,started);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at INTEGER, action TEXT, subject TEXT);
            PRAGMA user_version=1;
            """)
            db.execute(
                "UPDATE requests SET status='interrupted',code='gateway_restarted' WHERE status='running'"
            )
        self.path.chmod(0o600)

    @contextmanager
    def connection(self, immediate=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        if immediate:
            db.execute("BEGIN IMMEDIATE")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def audit(self, action, subject):
        with self.connection() as db:
            db.execute(
                "INSERT INTO audit(at,action,subject) VALUES(?,?,?)",
                (int(time.time()), action, subject),
            )

    def get_admin(self):
        with self.connection() as db:
            row = db.execute("SELECT * FROM admin").fetchone()
            return dict(row) if row else None

    def setup(self, username, password):
        hashed = password_hash(password)
        with self.connection(immediate=True) as db:
            if db.execute("SELECT 1 FROM admin").fetchone():
                raise GatewayError(409, "already_initialized", "Administrator already exists")
            db.execute("INSERT INTO admin VALUES(1,?,?)", (username, hashed))
        self.audit("setup", username)

    def session(self, value):
        with self.connection() as db:
            return bool(
                db.execute(
                    "SELECT 1 FROM sessions WHERE hash=? AND expires>?",
                    (digest(value), int(time.time())),
                ).fetchone()
            )

    def login(self):
        raw = secrets.token_urlsafe(32)
        with self.connection() as db:
            db.execute("DELETE FROM sessions WHERE expires<=?", (int(time.time()),))
            db.execute("INSERT INTO sessions VALUES(?,?)", (digest(raw), int(time.time()) + 86400))
        return raw

    def logout(self, value):
        with self.connection() as db:
            db.execute("DELETE FROM sessions WHERE hash=?", (digest(value),))

    def channels(self, private=False):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM channels").fetchall()
        result = []
        for row in rows:
            config = json.loads(row["config"])
            creds = json.loads(self.cipher.decrypt(row["credentials"].encode()))
            proxy = creds.pop("__proxy_url", "")
            result.append(
                {
                    **config,
                    "id": row["id"],
                    "models": json.loads(row["models"]),
                    "synced_at": row["synced"],
                    "last_error": row["error"],
                    **(
                        {"credentials": creds, "proxy_url": proxy}
                        if private
                        else {
                            "credential_providers": list(creds),
                            "proxy_url": "",
                            "proxy_configured": bool(proxy),
                        }
                    ),
                }
            )
        return result

    def channel(self, ident, private=True):
        channel = next((c for c in self.channels(private) if c["id"] == ident), None)
        if not channel:
            raise GatewayError(404, "channel_not_found", "Channel not found")
        return channel

    def save_channel(self, ident, config):
        value = dict(config)
        credentials = value.pop("credentials", None)
        proxy = value.pop("proxy_url", "")
        with self.connection() as db:
            old = db.execute("SELECT credentials FROM channels WHERE id=?", (ident,)).fetchone()
            old_secrets = json.loads(self.cipher.decrypt(old[0].encode())) if old else {}
            encrypted = (
                old[0]
                if credentials is None and old
                else self.cipher.encrypt(json.dumps(credentials or {}).encode()).decode()
            )
            # Never retain a credential for a provider removed from the configuration.
            filtered = {
                k: v
                for k, v in json.loads(self.cipher.decrypt(encrypted.encode())).items()
                if k in value["providers"]
            }
            # An empty edit preserves the existing proxy; '-' explicitly clears it.
            actual_proxy = proxy if proxy else old_secrets.get("__proxy_url", "")
            if actual_proxy and actual_proxy != "-":
                filtered["__proxy_url"] = actual_proxy
            encrypted = self.cipher.encrypt(json.dumps(filtered).encode()).decode()
            db.execute(
                "INSERT INTO channels(id,config,credentials) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET config=excluded.config,credentials=excluded.credentials,models='[]',synced=NULL,error=NULL",
                (ident, json.dumps(value), encrypted),
            )
        self.audit("channel_saved", ident)

    def sync_channel(self, ident, models=None, error=None):
        with self.connection() as db:
            if models is not None:
                db.execute(
                    "UPDATE channels SET models=?,synced=?,error=NULL WHERE id=?",
                    (json.dumps(models), int(time.time()), ident),
                )
            else:
                db.execute("UPDATE channels SET error=? WHERE id=?", (error, ident))

    def delete_channel(self, ident):
        with self.connection() as db:
            db.execute("DELETE FROM channels WHERE id=?", (ident,))
        self.audit("channel_deleted", ident)

    def keys(self):
        with self.connection() as db:
            rows = db.execute(
                "SELECT id,prefix,config,created FROM api_keys ORDER BY created DESC"
            ).fetchall()
        return [
            {
                **json.loads(r["config"]),
                "id": r["id"],
                "prefix": r["prefix"],
                "created_at": r["created"],
            }
            for r in rows
        ]

    def create_key(self, config):
        raw = "sk-acp-" + secrets.token_urlsafe(32)
        ident = secrets.token_hex(8)
        with self.connection() as db:
            db.execute(
                "INSERT INTO api_keys VALUES(?,?,?,?,?)",
                (ident, digest(raw), raw[:12], json.dumps(config), int(time.time())),
            )
        self.audit("key_created", ident)
        return {"id": ident, "key": raw}

    def update_key(self, ident, config):
        with self.connection() as db:
            if not db.execute(
                "UPDATE api_keys SET config=? WHERE id=?", (json.dumps(config), ident)
            ).rowcount:
                raise GatewayError(404, "key_not_found", "API key not found")
        self.audit("key_updated", ident)

    def revoke_key(self, ident):
        key = next((k for k in self.keys() if k["id"] == ident), None)
        if not key:
            raise GatewayError(404, "key_not_found", "API key not found")
        value = {k: v for k, v in key.items() if k not in {"id", "prefix", "created_at"}}
        value["enabled"] = False
        self.update_key(ident, value)

    def authenticate_key(self, raw):
        with self.connection() as db:
            row = db.execute(
                "SELECT id,config FROM api_keys WHERE hash=?", (digest(raw),)
            ).fetchone()
        if not row:
            raise GatewayError(401, "invalid_api_key", "Invalid API key")
        key = {**json.loads(row["config"]), "id": row["id"]}
        if not key["enabled"] or (key.get("expires_at") and key["expires_at"] <= time.time()):
            raise GatewayError(401, "inactive_api_key", "API key disabled or expired")
        return key

    def reserve(self, key, ident, channel, model):
        now = int(time.time())
        with self.connection(immediate=True) as db:
            # Re-read under the reservation transaction to honor revocation.
            stored = db.execute("SELECT config FROM api_keys WHERE id=?", (key["id"],)).fetchone()
            config = json.loads(stored[0]) if stored else {}
            if not config.get("enabled") or (
                config.get("expires_at") and config["expires_at"] <= now
            ):
                raise GatewayError(401, "inactive_api_key", "API key disabled or expired")
            if config.get("allowed_models") and model not in config["allowed_models"]:
                raise GatewayError(403, "model_forbidden", "API key cannot access this model")
            usage = db.execute(
                "SELECT SUM(started>?) minute,SUM(started>=?) today,SUM(status='running') active,COALESCE(SUM(total_tokens),0) tokens FROM requests WHERE key_id=?",
                (now - 60, now - now % 86400, key["id"]),
            ).fetchone()
            for exceeded, code in [
                ((usage["minute"] or 0) >= config["rpm"], "rate_limit"),
                (
                    config["daily_requests"] and (usage["today"] or 0) >= config["daily_requests"],
                    "daily_quota",
                ),
                ((usage["active"] or 0) >= config["max_concurrency"], "concurrency_limit"),
                (config["token_limit"] and usage["tokens"] >= config["token_limit"], "token_quota"),
            ]:
                if exceeded:
                    raise GatewayError(429, code, "API key limit reached")
            db.execute(
                "INSERT INTO requests(id,key_id,channel_id,model,started,status) VALUES(?,?,?,?,?,'running')",
                (ident, key["id"], channel, model, now),
            )

    def finish(self, ident, status, duration_ms, usage=None, code=None, ttft_ms=None):
        u = usage or {}
        with self.connection() as db:
            db.execute(
                "UPDATE requests SET status=?,duration_ms=?,code=?,prompt_tokens=?,completion_tokens=?,total_tokens=?,ttft_ms=? WHERE id=? AND status='running'",
                (
                    status,
                    duration_ms,
                    code,
                    u.get("prompt_tokens"),
                    u.get("completion_tokens"),
                    u.get("total_tokens"),
                    ttft_ms,
                    ident,
                ),
            )

    def logs(self, limit=50, offset=0, status="", model=""):
        where, args = [], []
        if status:
            where.append("status=?")
            args.append(status)
        if model:
            where.append("model=?")
            args.append(model)
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM requests"
                + clause
                + " ORDER BY started DESC,rowid DESC LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
            total = db.execute("SELECT COUNT(*) FROM requests" + clause, args).fetchone()[0]
        return {"items": [dict(r) for r in rows], "total": total}

    def overview(self):
        with self.connection() as db:
            stats = dict(
                db.execute(
                    "SELECT COUNT(*) requests,SUM(status='success') success,SUM(status='running') active,COALESCE(SUM(total_tokens),0) total_tokens,AVG(duration_ms) avg_latency_ms FROM requests"
                ).fetchone()
            )
            trend = [
                dict(r)
                for r in db.execute(
                    "SELECT strftime('%Y-%m-%d',started,'unixepoch') day,COUNT(*) requests,SUM(status='success') success FROM requests WHERE started>=? GROUP BY day ORDER BY day",
                    (int(time.time()) - 7 * 86400,),
                )
            ]
        return {
            **stats,
            "trend": trend,
            "channels": len(self.channels()),
            "enabled_channels": sum(c["enabled"] for c in self.channels()),
            "keys": len(self.keys()),
        }
