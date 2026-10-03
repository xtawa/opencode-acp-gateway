import React from "react";
import type { Log } from "./types";
import { Empty, Badge, when, number, statusName } from "./ui";

export default function LogTable({
  items,
  title,
}: {
  items: Log[];
  title?: string;
}) {
  return (
    <section className="panel table-panel">
      {title && (
        <div className="panel-heading">
          <h2>{title}</h2>
        </div>
      )}
      {items.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>时间 / 请求 ID</th>
                <th>模型</th>
                <th>状态</th>
                <th>耗时</th>
                <th>首字延迟</th>
                <th>Token</th>
              </tr>
            </thead>
            <tbody>
              {items.map((l) => (
                <tr key={l.id}>
                  <td>
                    {when(l.started)}
                    <small className="cell-sub mono">
                      {l.id.slice(0, 23)}…
                    </small>
                  </td>
                  <td>
                    <code>{l.model}</code>
                  </td>
                  <td>
                    <Badge ok={l.status === "success"}>
                      {statusName[l.status] || l.status}
                    </Badge>
                    {l.code && (
                      <small className="cell-sub danger-text">{l.code}</small>
                    )}
                  </td>
                  <td>
                    {l.duration_ms == null
                      ? "—"
                      : (l.duration_ms / 1000).toFixed(2) + "s"}
                  </td>
                  <td>
                    {l.ttft_ms == null
                      ? "—"
                      : (l.ttft_ms / 1000).toFixed(2) + "s"}
                  </td>
                  <td>{number(l.total_tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty
          title="暂无调用记录"
          detail="通过 API Key 发起请求后，这里将显示状态与用量。"
        />
      )}
    </section>
  );
}
