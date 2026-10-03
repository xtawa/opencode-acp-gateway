import json
from typing import Any, Literal

from jsonschema import Draft202012Validator, SchemaError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def validate_schema(schema):
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError("Invalid JSON Schema") from exc


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(Input):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=128)


class Setup(Credentials):
    bootstrap_token: str = Field(min_length=16, max_length=256)


class PasswordChange(Input):
    current_password: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=128)


class Channel(Input):
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    priority: int = Field(default=0, ge=0, le=1000)
    providers: list[str] = Field(default=["opencode"], min_length=1, max_length=20)
    free_only: bool = True
    allow_training: bool = False
    timeout_seconds: int = Field(default=180, ge=10, le=600)
    max_concurrency: int = Field(default=2, ge=1, le=16)
    proxy_url: str = Field(default="", max_length=1024)
    # Only provider credentials are accepted, never arbitrary executable config.
    credentials: dict[str, str] | None = None
    aliases: dict[str, str] = Field(default_factory=dict)

    @field_validator("providers")
    @classmethod
    def valid_providers(cls, values):
        if any(not p or not all(c.isalnum() or c in "-_" for c in p) for p in values):
            raise ValueError("Invalid provider ID")
        return list(dict.fromkeys(values))

    @field_validator("proxy_url")
    @classmethod
    def valid_proxy(cls, value):
        if value and value != "-" and not value.startswith(("http://", "https://")):
            raise ValueError("Proxy must be an HTTP or HTTPS URL")
        return value

    @model_validator(mode="after")
    def valid_secrets(self):
        if self.credentials is not None:
            if set(self.credentials) - set(self.providers):
                raise ValueError("Credential provider must be enabled")
            if any(not v or len(v) > 8192 for v in self.credentials.values()):
                raise ValueError("Invalid provider credential")
        if any(not k or not v or len(k) > 120 or len(v) > 200 for k, v in self.aliases.items()):
            raise ValueError("Invalid model alias")
        return self


class Key(Input):
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    expires_at: int | None = Field(default=None, ge=1)
    rpm: int = Field(default=60, ge=1, le=10000)
    daily_requests: int = Field(default=1000, ge=0)
    token_limit: int = Field(default=0, ge=0)
    max_concurrency: int = Field(default=2, ge=1, le=32)
    allowed_models: list[str] = Field(default_factory=list, max_length=200)


class Message(Input):
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]] | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None

    @field_validator("content")
    @classmethod
    def text_only(cls, content):
        if isinstance(content, list):
            if any(
                set(p) - {"type", "text"}
                or p.get("type") != "text"
                or not isinstance(p.get("text"), str)
                for p in content
            ):
                raise ValueError("Only text content is currently supported")
            return "\n".join(p["text"] for p in content)
        return content


class Chat(Input):
    model: str = Field(min_length=1, max_length=200)
    messages: list[Message] = Field(min_length=1, max_length=1000)
    stream: bool = False
    stream_options: dict[str, bool] | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    tool_choice: str | dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    reasoning_effort: str | None = Field(default=None, max_length=80)
    user: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_options(self):
        if self.stream_options and set(self.stream_options) - {"include_usage"}:
            raise ValueError("Unsupported stream_options")
        if self.tool_choice not in (None, "auto", "none", "required") and not isinstance(
            self.tool_choice, dict
        ):
            raise ValueError("Invalid tool_choice")
        names = []
        for tool in self.tools:
            if tool.get("type") != "function" or not isinstance(tool.get("function"), dict):
                raise ValueError("Only function tools are supported")
            fn = tool["function"]
            if not isinstance(fn.get("name"), str) or not fn["name"] or fn["name"] in names:
                raise ValueError("Tool names must be nonempty and unique")
            validate_schema(fn.get("parameters", {"type": "object"}))
            names.append(fn["name"])
        if self.tool_choice == "required" and not self.tools:
            raise ValueError("tool_choice=required needs tools")
        if isinstance(self.tool_choice, dict):
            if (
                self.tool_choice.get("type") != "function"
                or not isinstance(self.tool_choice.get("function"), dict)
                or self.tool_choice.get("function", {}).get("name") not in names
            ):
                raise ValueError("Selected tool not found")
        if self.response_format:
            fmt = self.response_format.get("type")
            if fmt not in {"text", "json_object", "json_schema"}:
                raise ValueError("Unsupported response_format")
            if fmt == "json_schema":
                if not isinstance(self.response_format.get("json_schema"), dict):
                    raise ValueError("json_schema must be an object")
                validate_schema(self.response_format.get("json_schema", {}).get("schema"))
        json.dumps(self.model_dump(), ensure_ascii=False)
        return self
