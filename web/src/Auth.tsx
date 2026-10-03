import React, { useState } from "react";
import { ShieldCheck, ArrowUpRight } from "lucide-react";
import { mutate } from "./api";
import { Field, errorText } from "./ui";

export default function Auth({
  initialized,
  onLogin,
  notify,
  toast,
}: {
  initialized: boolean;
  onLogin: (d: any) => void;
  notify: (s: string) => void;
  toast: string;
}) {
  const [username, setUsername] = useState("admin"),
    [password, setPassword] = useState(""),
    [bootstrap, setBootstrap] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      onLogin(
        await mutate(initialized ? "/api/login" : "/api/setup", {
          username,
          password,
          ...(!initialized ? { bootstrap_token: bootstrap } : {}),
        }),
      );
    } catch (e) {
      notify(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-page">
      <div className="auth-brand">
        ACP <span>Gateway</span>
      </div>
      <section className="auth-card">
        <div className="auth-icon">
          <ShieldCheck size={28} />
        </div>
        <h1>{initialized ? "欢迎回来" : "初始化网关"}</h1>
        <p className="subtle">
          {initialized
            ? "登录以管理渠道、访问密钥与调用。"
            : "创建管理员，开始连接你的应用。"}
        </p>
        <form onSubmit={submit}>
          {!initialized && (
            <Field
              label="初始化令牌"
              hint="从部署的数据目录 bootstrap-token 文件读取。"
            >
              <input
                required
                type="password"
                autoComplete="off"
                value={bootstrap}
                onChange={(e) => setBootstrap(e.target.value)}
              />
            </Field>
          )}
          <Field label="用户名">
            <input
              required
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </Field>
          <Field
            label="密码"
            hint={!initialized ? "至少 12 个字符。" : undefined}
          >
            <input
              required
              minLength={12}
              maxLength={128}
              type="password"
              autoComplete={initialized ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <button className="button wide" disabled={busy}>
            {busy ? "请稍候…" : initialized ? "登录控制台" : "创建管理员"}
            <ArrowUpRight size={16} />
          </button>
        </form>
        {toast && (
          <p className="error-box" role="alert">
            {toast}
          </p>
        )}
      </section>
      <small className="auth-foot">
        独立部署 · 访问可控 · 对话不写入网关日志
      </small>
    </div>
  );
}
