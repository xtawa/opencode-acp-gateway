import React, { useState } from "react";
import type { Key } from "./types";
import { mutate } from "./api";
import { Modal, Field, Toggle, errorText } from "./ui";

export default function KeyForm({
  value,
  close,
  saved,
  notify,
}: {
  value: Key | "new";
  close: () => void;
  saved: (key?: string) => void;
  notify: (s: string) => void;
}) {
  const existing = value === "new" ? null : value;
  const [name, setName] = useState(existing?.name || ""),
    [enabled, setEnabled] = useState(existing?.enabled ?? true),
    [rpm, setRpm] = useState(existing?.rpm || 60),
    [daily, setDaily] = useState(existing?.daily_requests ?? 1000),
    [limit, setLimit] = useState(existing?.token_limit || 0),
    [concurrency, setConcurrency] = useState(existing?.max_concurrency || 2),
    [models, setModels] = useState(existing?.allowed_models.join("\n") || ""),
    [expires, setExpires] = useState(
      existing?.expires_at
        ? new Date(
            existing.expires_at * 1000 - new Date().getTimezoneOffset() * 60000,
          )
            .toISOString()
            .slice(0, 16)
        : "",
    ),
    [busy, setBusy] = useState(false);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const result = await mutate(
        "/api/keys" + (existing ? "/" + existing.id : ""),
        {
          name,
          enabled,
          rpm,
          daily_requests: daily,
          token_limit: limit,
          max_concurrency: concurrency,
          allowed_models: models
            .split("\n")
            .map((x) => x.trim())
            .filter(Boolean),
          expires_at: expires
            ? Math.floor(new Date(expires).getTime() / 1000)
            : null,
        },
        existing ? "PUT" : "POST",
      );
      saved(result.key);
    } catch (e) {
      notify(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title={existing ? "编辑 API Key" : "创建 API Key"} close={close}>
      <form onSubmit={save}>
        <div className="modal-body">
          <Field label="名称">
            <input
              required
              value={name}
              maxLength={80}
              onChange={(e) => setName(e.target.value)}
              placeholder="如 AstrBot"
            />
          </Field>
          <div className="form-grid">
            <Field label="每分钟请求">
              <input
                type="number"
                min={1}
                max={10000}
                value={rpm}
                onChange={(e) => setRpm(+e.target.value)}
              />
            </Field>
            <Field label="每日请求上限">
              <input
                type="number"
                min={0}
                value={daily}
                onChange={(e) => setDaily(+e.target.value)}
              />
            </Field>
            <Field label="最大并发">
              <input
                type="number"
                min={1}
                max={32}
                value={concurrency}
                onChange={(e) => setConcurrency(+e.target.value)}
              />
            </Field>
          </div>
          <Field
            label="累计 Token 阈值"
            hint="0 表示不限。达到阈值后拒绝新请求，已在运行的请求会完成并计入用量。"
          >
            <input
              type="number"
              min={0}
              value={limit}
              onChange={(e) => setLimit(+e.target.value)}
            />
          </Field>
          <Field
            label="允许的模型"
            hint="每行一个完整模型 ID / 别名；留空允许所有已启用模型。"
          >
            <textarea
              rows={3}
              className="mono"
              value={models}
              onChange={(e) => setModels(e.target.value)}
            />
          </Field>
          <Field
            label="到期时间"
            hint="留空永不过期；每日请求按 UTC 日期重置，失败请求也计入次数。"
          >
            <input
              type="datetime-local"
              value={expires}
              onChange={(e) => setExpires(e.target.value)}
            />
          </Field>
          <Toggle label="启用此密钥" checked={enabled} onChange={setEnabled} />
        </div>
        <div className="modal-footer">
          <button type="button" className="button secondary" onClick={close}>
            取消
          </button>
          <button className="button" disabled={busy}>
            {busy ? "保存中…" : existing ? "保存修改" : "创建密钥"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
