import { describe, it, expect } from "vitest";
import { sse } from "./api";
describe("SSE decoder", () => {
  it("preserves UTF-8 split across network chunks and handles multiple events", async () => {
    const bytes = new TextEncoder().encode(
      'data: {"text":"你好"}\n\ndata: {"usage":12}\n\ndata: [DONE]\n\n',
    );
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        for (const b of bytes) c.enqueue(new Uint8Array([b]));
        c.close();
      },
    });
    const results = [];
    for await (const event of sse(body)) results.push(event);
    expect(results).toEqual([{ text: "你好" }, { usage: 12 }]);
  });
  it("reports malformed upstream data", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(new TextEncoder().encode("data: invalid\n\n"));
        c.close();
      },
    });
    await expect(
      (async () => {
        for await (const ignored of sse(body)) void ignored;
      })(),
    ).rejects.toThrow();
  });
});
