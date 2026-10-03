"""Test-only ACP peer. Exercises actual subprocess stdio without external models."""

import asyncio
import json
import sys
import uuid


def send(value):
    sys.stdout.write(json.dumps(value) + "\n")
    sys.stdout.flush()


async def main():
    permissions, tasks = {}, {}

    async def prompt(message):
        sid = message["params"]["sessionId"]
        text = message["params"]["prompt"][0]["text"]
        permission_id = "permission-" + sid
        future = asyncio.get_running_loop().create_future()
        permissions[permission_id] = future
        send(
            {
                "jsonrpc": "2.0",
                "id": permission_id,
                "method": "session/request_permission",
                "params": {"sessionId": sid, "options": []},
            }
        )
        reply = await future
        assert reply["result"]["outcome"]["outcome"] == "cancelled"
        if text == "fail":
            send(
                {
                    "id": message["id"],
                    "error": {"code": -32000, "message": "FreeTierError: secret-must-not-leak"},
                }
            )
            return
        for fragment in [text[:1], text[1:]]:
            await asyncio.sleep(0.02)
            send(
                {
                    "method": "session/update",
                    "params": {
                        "sessionId": sid,
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": fragment},
                        },
                    },
                }
            )
        if text == "wait":
            await asyncio.sleep(60)
        send(
            {
                "id": message["id"],
                "result": {
                    "stopReason": "end_turn",
                    "usage": {"inputTokens": 2, "outputTokens": 3, "totalTokens": 5},
                },
            }
        )

    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break
        message = json.loads(line)
        if "method" not in message:
            permissions.pop(message["id"]).set_result(message)
            continue
        method, params = message["method"], message.get("params", {})
        result = {}
        if method == "session/new":
            result = {"sessionId": "s-" + uuid.uuid4().hex}
        elif method == "session/set_config_option":
            result = {
                "configOptions": [{"id": params["configId"], "currentValue": params["value"]}]
            }
        elif method == "session/prompt":
            tasks[params["sessionId"]] = asyncio.create_task(prompt(message))
            continue
        elif method == "session/cancel":
            task = tasks.pop(params["sessionId"], None)
            if task:
                task.cancel()
            continue
        if "id" in message:
            send({"jsonrpc": "2.0", "id": message["id"], "result": result})


if __name__ == "__main__":
    asyncio.run(main())
