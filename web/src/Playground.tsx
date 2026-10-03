import React, { useState, useEffect } from "react";
import { FlaskConical, ArrowUpRight } from "lucide-react";
import { sse } from "./api";
import { Field, Badge, Empty, number, errorText } from "./ui";

export default function Playground({
  models,
  notify,
  refresh,
}: {
  models: string[];
  notify: (s: string) => void;
  refresh: () => void;
}) {
  const [key, setKey] = useState(""),
    [model, setModel] = useState(models[0] || ""),
    [system, setSystem] = useState("请简洁地用中文回答。"),
    [prompt, setPrompt] = useState(""),
    [reply, setReply] = useState(""),
    [thought, setThought] = useState(""),
    [busy, setBusy] = useState(false),
    [usage, setUsage] = useState<any>(null),
    [controller, setController] = useState<AbortController | null>(null);
  useEffect(() => {
    if (!model && models.length) setModel(models[0]);
  }, [models, model]);
  useEffect(() => () => controller?.abort(), [controller]);
  async function send(e: React.FormEvent) {
    e.preventDefault();
    const abort = new AbortController();
    setController(abort);
    setBusy(true);
    setReply("");
    setThought("");
    setUsage(null);
    try {
      const response = await fetch("/v1/chat/completions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + key,
        },
        body: JSON.stringify({
          model,
          messages: [
            ...(system ? [{ role: "system", content: system }] : []),
            { role: "user", content: prompt },
          ],
          stream: true,
          stream_options: { include_usage: true },
        }),
        signal: abort.signal,
      });
      if (!response.ok) {
        const data = await response.json();
        throw Error(data.error?.message || "请求失败");
      }
      for await (const event of sse(response.body!)) {
        if (event.error) throw Error(event.error.message);
        const delta = event.choices?.[0]?.delta;
        if (delta?.content) setReply((x) => x + delta.content);
        if (delta?.reasoning_content)
          setThought((x) => x + delta.reasoning_content);
        if (event.usage) setUsage(event.usage);
      }
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError"))
        notify(errorText(e));
    } finally {
      setBusy(false);
      setController(null);
      refresh();
    }
  }
  return (
    <div className="playground-grid">
      <section className="panel">
        <div className="panel-heading">
          <h2>调用配置</h2>
          <FlaskConical size={18} />
        </div>
        <form onSubmit={send} className="panel-body">
          <Field label="API Key" hint="只保留在本页内存中，离开页面即清除。">
            <input
              required
              type="password"
              autoComplete="off"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="sk-acp-…"
            />
          </Field>
          <Field label="模型">
            <select
              required
              value={model}
              onChange={(e) => setModel(e.target.value)}
            >
              <option value="">选择模型</option>
              {models.map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </Field>
          <Field label="系统提示词">
            <textarea
              rows={3}
              value={system}
              onChange={(e) => setSystem(e.target.value)}
            />
          </Field>
          <Field label="消息">
            <textarea
              required
              rows={5}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="输入一条测试消息…"
            />
          </Field>
          <div className="row-actions">
            <button className="button" disabled={busy || !models.length}>
              {busy ? "生成中…" : "发送请求"}
              <ArrowUpRight size={16} />
            </button>
            {busy && (
              <button
                type="button"
                className="button secondary"
                onClick={() => controller?.abort()}
              >
                停止生成
              </button>
            )}
          </div>
        </form>
      </section>
      <section className="panel reply-panel">
        <div className="panel-heading">
          <h2>模型回复</h2>
          <Badge ok={!!usage}>
            {busy ? "接收流式输出" : usage ? "调用完成" : "等待请求"}
          </Badge>
        </div>
        {reply || thought ? (
          <div className="response-body">
            {thought && (
              <details>
                <summary>推理输出</summary>
                <pre>{thought}</pre>
              </details>
            )}
            <pre>{reply || "等待正文…"}</pre>
          </div>
        ) : (
          <Empty
            title="开始一次真实调用"
            detail="输出将逐段显示，Token 采用官方 ACP 返回值。"
          />
        )}
        {usage && (
          <div className="usage-strip">
            输入 {number(usage.prompt_tokens)} · 输出{" "}
            {number(usage.completion_tokens)} · 总计{" "}
            {number(usage.total_tokens)}
          </div>
        )}
      </section>
    </div>
  );
}
