import React, { useState } from "react";
import type { Channel } from "./types";
import { mutate } from "./api";
import { Modal, Field, Toggle, errorText } from "./ui";

export default function ChannelForm({
  value,
  close,
  saved,
  notify,
}: {
  value: Channel | "new";
  close: () => void;
  saved: () => void;
  notify: (s: string) => void;
}) {
  const existing = value === "new" ? null : value;
  const [name, setName] = useState(existing?.name || ""),
    [providers, setProviders] = useState(
      existing?.providers.join(", ") || "opencode",
    ),
    [credentials, setCredentials] = useState(""),
    [aliases, setAliases] = useState(
      JSON.stringify(existing?.aliases || {}, null, 2),
    ),
    [proxy, setProxy] = useState(""),
    [enabled, setEnabled] = useState(existing?.enabled ?? true),
    [free, setFree] = useState(existing?.free_only ?? true),
    [training, setTraining] = useState(existing?.allow_training ?? false),
    [priority, setPriority] = useState(existing?.priority || 0),
    [timeout, setTimeout] = useState(existing?.timeout_seconds || 180),
    [concurrency, setConcurrency] = useState(existing?.max_concurrency || 2),
    [busy, setBusy] = useState(false);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await mutate(
        "/api/channels" + (existing ? "/" + existing.id : ""),
        {
          name,
          providers: providers
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
          credentials: credentials.trim() ? JSON.parse(credentials) : null,
          aliases: JSON.parse(aliases),
          proxy_url: proxy,
          enabled,
          free_only: free,
          allow_training: training,
          priority,
          timeout_seconds: timeout,
          max_concurrency: concurrency,
        },
        existing ? "PUT" : "POST",
      );
      saved();
      notify("渠道已保存，请同步模型目录");
    } catch (e) {
      notify(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title={existing ? "编辑渠道" : "添加渠道"} close={close}>
      <form onSubmit={save}>
        <div className="modal-body">
          <Field label="渠道名称">
            <input
              required
              maxLength={80}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如 OpenCode Zen"
            />
          </Field>
          <Field
            label="提供商 ID"
            hint="多个 ID 用英文逗号分隔，如 opencode, openai, anthropic。"
          >
            <input
              required
              value={providers}
              onChange={(e) => setProviders(e.target.value)}
            />
          </Field>
          <Field
            label="上游 API Key（JSON）"
            hint={
              existing
                ? "留空保留现有密钥；填写 {} 清除。密钥不回显。"
                : '免费渠道可留空。示例：{"openai":"你的上游密钥"}。'
            }
          >
            <textarea
              className="mono"
              rows={3}
              value={credentials}
              onChange={(e) => setCredentials(e.target.value)}
              placeholder="{}"
              autoComplete="off"
              spellCheck={false}
            />
          </Field>
          <Field
            label="模型别名（JSON）"
            hint='示例：{"my-model":"opencode/真实模型ID"}；必须指向同步目录中的模型。'
          >
            <textarea
              className="mono"
              rows={3}
              value={aliases}
              onChange={(e) => setAliases(e.target.value)}
              spellCheck={false}
            />
          </Field>
          <div className="form-grid">
            <Field label="优先级">
              <input
                type="number"
                min={0}
                max={1000}
                value={priority}
                onChange={(e) => setPriority(+e.target.value)}
              />
            </Field>
            <Field label="超时（秒）">
              <input
                type="number"
                min={10}
                max={600}
                value={timeout}
                onChange={(e) => setTimeout(+e.target.value)}
              />
            </Field>
            <Field label="渠道并发">
              <input
                type="number"
                min={1}
                max={16}
                value={concurrency}
                onChange={(e) => setConcurrency(+e.target.value)}
              />
            </Field>
          </div>
          <Field
            label="出站代理"
            hint="可选，仅 OpenCode 出站使用；留空保留，填写 - 清除。"
          >
            <input
              type="text"
              value={proxy}
              onChange={(e) => setProxy(e.target.value)}
              placeholder={
                existing?.proxy_configured
                  ? "已有代理，留空保留"
                  : "http://proxy-host:port"
              }
            />
          </Field>
          <Toggle label="启用此渠道" checked={enabled} onChange={setEnabled} />
          <Toggle
            label="仅使用目录中输入 / 输出价格为零的模型"
            checked={free}
            onChange={setFree}
          />
          <Toggle
            label="已核对免费提供商的数据政策，允许其使用对话改进 / 训练模型"
            checked={training}
            onChange={setTraining}
          />
          <p className="footnote">
            免费模型调用前需要勾选数据政策确认。不同提供商的可用性取决于上游账号和额度。
          </p>
        </div>
        <div className="modal-footer">
          <button type="button" className="button secondary" onClick={close}>
            取消
          </button>
          <button className="button" disabled={busy}>
            {busy ? "保存中…" : "保存渠道"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
