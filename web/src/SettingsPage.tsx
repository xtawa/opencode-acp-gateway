import React, { useState } from "react";
import { KeyRound, ShieldCheck, Zap, Activity, Copy } from "lucide-react";
import { mutate } from "./api";
import { Field, Badge, Empty, when, number, errorText } from "./ui";

export default function SettingsPage({
  config,
  audit,
  account,
  notify,
  logout,
}: {
  config: any;
  audit: any[];
  account: string;
  notify: (s: string) => void;
  logout: () => void;
}) {
  const [password, setPassword] = useState(""),
    [currentPassword, setCurrentPassword] = useState(""),
    [busy, setBusy] = useState(false);
  const copy = () =>
    navigator.clipboard
      .writeText(location.origin + "/v1")
      .then(() => notify("已复制 Base URL"))
      .catch(() => notify("复制失败，请手动复制"));
  return (
    <div className="settings-grid">
      <section className="panel">
        <div className="panel-heading">
          <h2>客户端接入</h2>
          <KeyRound size={18} />
        </div>
        <div className="panel-body">
          <Field label="OpenAI Base URL">
            <div className="copy-row">
              <code>{location.origin}/v1</code>
              <button
                className="icon-button"
                onClick={copy}
                aria-label="复制 Base URL"
              >
                <Copy size={16} />
              </button>
            </div>
          </Field>
          <p className="subtle">
            使用网关创建的 API Key；模型名称从模型目录选择。
          </p>
          <pre className="code-example">{`from openai import OpenAI\n\nclient = OpenAI(\n    base_url="${location.origin}/v1",\n    api_key="YOUR_GATEWAY_KEY",\n)\nresponse = client.chat.completions.create(\n    model="YOUR_MODEL_ID",\n    messages=[{"role": "user", "content": "你好"}],\n)`}</pre>
        </div>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h2>部署状态</h2>
          <ShieldCheck size={18} />
        </div>
        <dl className="settings-list">
          <div>
            <dt>版本</dt>
            <dd>{config?.version}</dd>
          </div>
          <div>
            <dt>Cookie Secure</dt>
            <dd>{config?.secure_cookies ? "启用" : "本地 HTTP 模式"}</dd>
          </div>
          <div>
            <dt>公开 Origin</dt>
            <dd>{config?.public_origin || "跟随当前请求"}</dd>
          </div>
          <div>
            <dt>日志策略</dt>
            <dd>仅元数据</dd>
          </div>
          <div>
            <dt>请求上限</dt>
            <dd>{number(config?.max_body_bytes)} 字节</dd>
          </div>
          <div>
            <dt>计数时区</dt>
            <dd>UTC</dd>
          </div>
        </dl>
        <p className="panel-body footnote">
          通过环境变量配置部署参数；HTTPS 反向代理部署应设置
          GATEWAY_SECURE_COOKIES=true 与 GATEWAY_PUBLIC_ORIGIN。
        </p>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h2>接口能力</h2>
          <Zap size={18} />
        </div>
        <div className="capabilities">
          {Object.entries(config?.compatibility || {}).map(([name, ok]) => (
            <div key={name}>
              <code>{name}</code>
              <Badge ok={!!ok}>{ok ? "支持" : "未提供"}</Badge>
            </div>
          ))}
        </div>
        <p className="panel-body footnote">
          工具调用意图和 JSON 输出通过模型生成并校验。工具 / JSON
          模式先缓冲完成输出再发送流；普通文本实时转发。ACP 未提供每请求
          temperature / max_tokens 映射，网关明确拒绝这些参数。
        </p>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h2>管理员密码</h2>
          <ShieldCheck size={18} />
        </div>
        <form
          className="panel-body"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              await mutate("/api/password", {
                current_password: currentPassword,
                password,
              });
              notify("密码已修改，请重新登录");
              logout();
            } catch (e) {
              notify(errorText(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          <Field label={`${account} 的当前密码`}>
            <input
              required
              maxLength={128}
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
            />
          </Field>
          <Field label="新密码">
            <input
              required
              minLength={12}
              maxLength={128}
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <button className="button secondary" disabled={busy}>
            修改密码并退出所有会话
          </button>
        </form>
      </section>
      <section className="panel audit-panel">
        <div className="panel-heading">
          <h2>管理操作日志</h2>
          <Activity size={18} />
        </div>
        {audit.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>操作</th>
                  <th>对象</th>
                </tr>
              </thead>
              <tbody>
                {audit.slice(0, 20).map((a) => (
                  <tr key={a.id}>
                    <td>{when(a.at)}</td>
                    <td>
                      <code>{a.action}</code>
                    </td>
                    <td className="mono">{a.subject}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="暂无管理操作" />
        )}
      </section>
    </div>
  );
}
