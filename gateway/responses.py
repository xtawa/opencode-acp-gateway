"""Stateless Responses wire format over the existing ACP conversation bridge."""

import json
import time
import uuid
from typing import Any, Literal

from pydantic import Field, model_validator

from .schemas import Chat, Input


def text_content(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise ValueError("Text content required")
    parts = []
    for part in content:
        if (
            not isinstance(part, dict)
            or part.get("type") not in {"input_text", "output_text"}
            or not isinstance(part.get("text"), str)
            or set(part) - {"type", "text", "annotations", "logprobs"}
            or part.get("annotations")
            or part.get("logprobs")
        ):
            raise ValueError("Only plain text is supported")
        parts.append(part["text"])
    return "\n".join(parts)


class Responses(Input):
    model: str = Field(min_length=1, max_length=200)
    input: str | list[dict[str, Any]]
    instructions: str | None = None
    stream: bool = False
    store: Literal[False] = False
    background: Literal[False] = False
    previous_response_id: None = None
    conversation: None = None
    truncation: Literal["disabled"] = "disabled"
    tools: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    tool_choice: str | dict[str, Any] | None = None
    text: dict[str, Any] | None = None
    reasoning: dict[str, Any] | None = None
    include: list[str] = Field(default_factory=list, max_length=0)
    user: str | None = Field(default=None, max_length=200)
    safety_identifier: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_bridge(self):
        if isinstance(self.input, list) and len(self.input) > 1000:
            raise ValueError("Too many input items")
        self.to_chat()
        return self

    def to_chat(self):
        messages = []
        if self.instructions:
            messages.append({"role": "system", "content": self.instructions})
        items = (
            [{"role": "user", "content": self.input}] if isinstance(self.input, str) else self.input
        )
        for item in items:
            kind = item.get("type", "message")
            if kind == "message":
                if set(item) - {"type", "role", "content", "id", "status"} or item.get(
                    "role"
                ) not in {"system", "developer", "user", "assistant"}:
                    raise ValueError("Unsupported message fields")
                messages.append(
                    {"role": item.get("role"), "content": text_content(item.get("content"))}
                )
            elif kind == "function_call":
                if set(item) - {"type", "id", "status", "call_id", "name", "arguments"} or any(
                    not isinstance(item.get(k), str) or not item[k]
                    for k in ("call_id", "name", "arguments")
                ):
                    raise ValueError("Invalid function call")
                json.loads(item["arguments"])
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": item["call_id"],
                                "type": "function",
                                "function": {"name": item["name"], "arguments": item["arguments"]},
                            }
                        ],
                    }
                )
            elif kind == "function_call_output":
                if (
                    set(item) - {"type", "id", "status", "call_id", "output"}
                    or not isinstance(item.get("call_id"), str)
                    or not item["call_id"]
                ):
                    raise ValueError("Invalid function result")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item["call_id"],
                        "content": text_content(item.get("output")),
                    }
                )
            elif kind == "reasoning":
                # Our public summary can be replayed; hidden/encrypted state cannot.
                if set(item) - {"type", "id", "status", "summary"} or not isinstance(
                    item.get("summary"), list
                ):
                    raise ValueError("Unsupported reasoning input")
                for part in item["summary"]:
                    if (
                        not isinstance(part, dict)
                        or set(part) != {"type", "text"}
                        or part.get("type") != "summary_text"
                        or not isinstance(part.get("text"), str)
                    ):
                        raise ValueError("Invalid reasoning summary")
                messages.append(
                    {
                        "role": "assistant",
                        "content": "Previous reasoning summary: "
                        + "\n".join(p["text"] for p in item["summary"]),
                    }
                )
            else:
                raise ValueError("Unsupported input item")
        tools = []
        for tool in self.tools:
            if tool.get("type") != "function" or set(tool) - {
                "type",
                "name",
                "description",
                "parameters",
                "strict",
            }:
                raise ValueError("Only function tools are supported")
            if (
                tool.get("description") is not None and not isinstance(tool["description"], str)
            ) or (tool.get("strict") is not None and not isinstance(tool["strict"], bool)):
                raise ValueError("Invalid function options")
            tools.append(
                {"type": "function", "function": {k: v for k, v in tool.items() if k != "type"}}
            )
        choice = self.tool_choice
        if isinstance(choice, dict):
            if set(choice) != {"type", "name"} or choice.get("type") != "function":
                raise ValueError("Unsupported tool choice")
            choice = {"type": "function", "function": {"name": choice["name"]}}
        fmt = None
        if self.text is not None:
            if set(self.text) - {"format"} or not isinstance(self.text.get("format"), dict):
                raise ValueError("Unsupported text options")
            value = self.text["format"]
            if value.get("type") == "json_schema":
                if set(value) - {"type", "name", "description", "schema", "strict"}:
                    raise ValueError("Unsupported JSON format")
                if (
                    not isinstance(value.get("name"), str)
                    or not value["name"]
                    or (
                        value.get("description") is not None
                        and not isinstance(value["description"], str)
                    )
                    or (value.get("strict") is not None and not isinstance(value["strict"], bool))
                ):
                    raise ValueError("Invalid JSON schema options")
                fmt = {
                    "type": "json_schema",
                    "json_schema": {k: v for k, v in value.items() if k != "type"},
                }
            else:
                if set(value) != {"type"}:
                    raise ValueError("Unsupported text format")
                fmt = value
        effort = None
        if self.reasoning is not None:
            if set(self.reasoning) - {"effort", "summary"} or self.reasoning.get("summary") not in (
                None,
                "auto",
                "concise",
                "detailed",
            ):
                raise ValueError("Unsupported reasoning options")
            effort = self.reasoning.get("effort")
        return Chat.model_validate(
            {
                "model": self.model,
                "messages": messages,
                "stream": self.stream,
                "tools": tools,
                "tool_choice": choice,
                "response_format": fmt,
                "reasoning_effort": effort,
                "user": self.user,
            }
        )


class ResponsesOutput:
    def __init__(self, request, ident, created):
        self.request, self.ident, self.created = request, ident, created
        self.items, self.indices, self.sequence = [], {}, 0

    def event(self, kind, **payload):
        value = {"type": kind, **payload, "sequence_number": self.sequence}
        self.sequence += 1
        return f"event: {kind}\ndata: " + json.dumps(value, ensure_ascii=False) + "\n\n"

    def response(self, status="in_progress", usage=None, error=None, stop=None):
        converted = None
        if usage is not None:
            converted = {
                "input_tokens": usage["prompt_tokens"],
                "output_tokens": usage["completion_tokens"],
                "total_tokens": usage["total_tokens"],
                "input_tokens_details": {
                    "cached_tokens": usage.get("prompt_tokens_details", {}).get("cached_tokens", 0),
                    "cache_write_tokens": usage.get("prompt_tokens_details", {}).get(
                        "cache_write_tokens", 0
                    ),
                },
                "output_tokens_details": {
                    "reasoning_tokens": usage.get("completion_tokens_details", {}).get(
                        "reasoning_tokens", 0
                    )
                },
            }
        return {
            "id": self.ident,
            "access_programs": None,
            "object": "response",
            "created_at": self.created,
            "completed_at": int(time.time()) if status == "completed" else None,
            "status": status,
            "error": error,
            "incomplete_details": {
                "reason": "max_output_tokens" if stop == "max_tokens" else "content_filter"
            }
            if status == "incomplete"
            else None,
            "model": self.request.model,
            "output": self.items,
            "usage": converted,
            "instructions": self.request.instructions,
            "tools": self.request.tools,
            "tool_choice": self.request.tool_choice or "auto",
            "parallel_tool_calls": True,
            "text": self.request.text or {"format": {"type": "text"}},
            "reasoning": self.request.reasoning or {"effort": None, "summary": None},
            "store": False,
            "background": False,
            "previous_response_id": None,
            "max_output_tokens": None,
            "temperature": None,
            "top_p": None,
            "truncation": "disabled",
            "metadata": {},
            "user": self.request.user,
        }

    def start(self):
        return self.event("response.created", response=self.response()) + self.event(
            "response.in_progress", response=self.response()
        )

    def delta(self, delta):
        result = ""
        for field in ("reasoning_content", "content"):
            value = delta.get(field)
            if not value or (
                field == "reasoning_content" and not (self.request.reasoning or {}).get("summary")
            ):
                continue
            reasoning = field == "reasoning_content"
            if field not in self.indices:
                index = self.indices[field] = len(self.items)
                item = (
                    {
                        "id": "rs_" + uuid.uuid4().hex,
                        "type": "reasoning",
                        "summary": [],
                        "status": "in_progress",
                    }
                    if reasoning
                    else {
                        "id": "msg_" + uuid.uuid4().hex,
                        "type": "message",
                        "role": "assistant",
                        "content": [],
                        "status": "in_progress",
                    }
                )
                self.items.append(item)
                result += self.event("response.output_item.added", output_index=index, item=item)
                part = (
                    {"type": "summary_text", "text": ""}
                    if reasoning
                    else {"type": "output_text", "text": "", "annotations": [], "logprobs": []}
                )
                item["summary" if reasoning else "content"].append(part)
                result += self.event(
                    "response.reasoning_summary_part.added"
                    if reasoning
                    else "response.content_part.added",
                    item_id=item["id"],
                    output_index=index,
                    **{"summary_index" if reasoning else "content_index": 0},
                    part=part,
                )
            index = self.indices[field]
            item = self.items[index]
            item["summary" if reasoning else "content"][0]["text"] += value
            result += self.event(
                "response.reasoning_summary_text.delta"
                if reasoning
                else "response.output_text.delta",
                item_id=item["id"],
                output_index=index,
                **{"summary_index" if reasoning else "content_index": 0},
                delta=value,
                **({} if reasoning else {"logprobs": []}),
            )
        return result

    def finish(self, message, usage, stop, buffered=False):
        result = self.delta(message) if buffered else ""
        status = "completed" if stop == "end_turn" else "incomplete"
        for index, item in enumerate(self.items):
            reasoning = item["type"] == "reasoning"
            part = item["summary" if reasoning else "content"][0]
            positions = {
                "item_id": item["id"],
                "output_index": index,
                "summary_index" if reasoning else "content_index": 0,
            }
            result += self.event(
                "response.reasoning_summary_text.done"
                if reasoning
                else "response.output_text.done",
                **positions,
                text=part["text"],
                **({} if reasoning else {"logprobs": []}),
            )
            result += self.event(
                "response.reasoning_summary_part.done"
                if reasoning
                else "response.content_part.done",
                **positions,
                part=part,
            )
            item["status"] = status
            result += self.event("response.output_item.done", output_index=index, item=item)
        for call in message.get("tool_calls", []):
            index = len(self.items)
            item = {
                "type": "function_call",
                "id": "fc_" + uuid.uuid4().hex,
                "call_id": call["id"],
                "name": call["function"]["name"],
                "arguments": "",
                "status": "in_progress",
            }
            self.items.append(item)
            result += self.event("response.output_item.added", output_index=index, item=item)
            item["arguments"] = call["function"]["arguments"]
            result += self.event(
                "response.function_call_arguments.delta",
                item_id=item["id"],
                output_index=index,
                delta=item["arguments"],
            )
            result += self.event(
                "response.function_call_arguments.done",
                item_id=item["id"],
                output_index=index,
                arguments=item["arguments"],
                name=item["name"],
            )
            item["status"] = status
            result += self.event("response.output_item.done", output_index=index, item=item)
        return result + self.event(
            "response." + status, response=self.response(status, usage, stop=stop)
        )

    def result(self, message, usage, stop):
        self.finish(message, usage, stop, buffered=True)
        return self.response("completed" if stop == "end_turn" else "incomplete", usage, stop=stop)

    def error(self, error):
        value = {"code": error.code, "message": error.message}
        return self.event("error", **value, param=None) + self.event(
            "response.failed",
            response=self.response("failed", error={**value, "code": "server_error"}),
        )
