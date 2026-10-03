import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowUpRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  Database,
  FlaskConical,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
  Trash2,
  X,
  Zap,
  Link2,
} from "lucide-react";
import { api, mutate, setCsrf } from "./api";
import "./style.css";

import type { Channel, Model, Key, Log } from "./types";
import { Empty, Badge, Modal, number, when, errorText, statusName } from "./ui";
import Auth from "./Auth";
import LogTable from "./LogTable";
import ChannelForm from "./ChannelForm";
import KeyForm from "./KeyForm";
import Playground from "./Playground";
import SettingsPage from "./SettingsPage";
const pages = [
  { id: "overview", name: "运行概览", Icon: LayoutDashboard },
  { id: "channels", name: "渠道管理", Icon: Link2 },
  { id: "models", name: "模型目录", Icon: Database },
  { id: "keys", name: "API Key", Icon: KeyRound },
  { id: "logs", name: "调用日志", Icon: Activity },
  { id: "playground", name: "在线测试", Icon: FlaskConical },
  { id: "settings", name: "系统设置", Icon: Settings },
];

function App() {
  const [account, setAccount] = useState<string | null>(null),
    [initialized, setInitialized] = useState(true),
    [checking, setChecking] = useState(true),
    [page, setPage] = useState("overview"),
    [theme, setTheme] = useState(localStorage.getItem("acp-theme") || "light"),
    [nav, setNav] = useState(false),
    [toast, setToast] = useState(""),
    [revision, setRevision] = useState(0);
  const [channels, setChannels] = useState<Channel[]>([]),
    [keys, setKeys] = useState<Key[]>([]),
    [overview, setOverview] = useState<any>(null),
    [logs, setLogs] = useState<Log[]>([]),
    [logTotal, setLogTotal] = useState(0),
    [logPage, setLogPage] = useState(0),
    [filter, setFilter] = useState(""),
    [query, setQuery] = useState(""),
    [config, setConfig] = useState<any>(null),
    [audit, setAudit] = useState<any[]>([]),
    [loading, setLoading] = useState(false);
  const [channelModal, setChannelModal] = useState<Channel | "new" | null>(
      null,
    ),
    [keyModal, setKeyModal] = useState<Key | "new" | null>(null),
    [createdKey, setCreatedKey] = useState<string | null>(null),
    [busy, setBusy] = useState("");
  const notify = (text: string) => setToast(text);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("acp-theme", theme);
  }, [theme]);
  useEffect(() => {
    if (toast) {
      const id = setTimeout(() => setToast(""), 6000);
      return () => clearTimeout(id);
    }
  }, [toast]);
  useEffect(() => {
    (async () => {
      try {
        const setup = await api("/api/setup");
        setInitialized(setup.initialized);
        if (setup.initialized) {
          try {
            const me = await api("/api/me");
            setAccount(me.username);
            setCsrf(me.csrf_token);
          } catch {}
        }
      } catch (e) {
        notify(errorText(e));
      } finally {
        setChecking(false);
      }
    })();
  }, []);
  useEffect(() => {
    if (!account) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const [cs, ks, ov, ls, settings, au] = await Promise.all([
          api("/api/channels"),
          api("/api/keys"),
          api("/api/overview"),
          api(
            "/api/logs?limit=20&offset=" + logPage * 20 + "&status=" + filter,
          ),
          api("/api/settings"),
          api("/api/audit"),
        ]);
        if (!cancelled) {
          setChannels(cs.items);
          setKeys(ks.items);
          setOverview(ov);
          setLogs(ls.items);
          setLogTotal(ls.total);
          setConfig(settings);
          setAudit(au.items);
        }
      } catch (e) {
        if (!cancelled) notify(errorText(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [account, revision, logPage, filter]);
  useEffect(() => {
    if (!account) return;
    const id = setInterval(() => setRevision((x) => x + 1), 15000);
    return () => clearInterval(id);
  }, [account]);
  const refresh = () => setRevision((x) => x + 1);
  async function action(id: string, fn: () => Promise<unknown>) {
    setBusy(id);
    try {
      await fn();
      refresh();
    } catch (e) {
      notify(errorText(e));
    } finally {
      setBusy("");
    }
  }
  const models = channels
    .flatMap((c) =>
      c.models.map((m) => ({ ...m, channel: c.name, enabled: c.enabled })),
    )
    .filter((m) => m.id.toLowerCase().includes(query.toLowerCase()));
  if (checking)
    return (
      <div className="auth-page">
        <span className="loading">正在连接网关…</span>
      </div>
    );
  if (!account)
    return (
      <Auth
        initialized={initialized}
        onLogin={(data) => {
          setAccount(data.username);
          setCsrf(data.csrf_token);
          setInitialized(true);
        }}
        notify={notify}
        toast={toast}
      />
    );
  return (
    <div className="shell">
      <aside className={"sidebar " + (nav ? "open" : "")}>
        <div className="wordmark">
          ACP <span>Gateway</span>
          <Badge ok>控制台</Badge>
        </div>
        <div className="nav-label">工作空间</div>
        <nav aria-label="主导航">
          {pages.map(({ id, name, Icon }) => (
            <button
              key={id}
              className={page === id ? "selected" : ""}
              onClick={() => {
                setPage(id);
                setQuery("");
                setNav(false);
              }}
            >
              <Icon size={18} />
              {name}
              {id === "channels" && <small>{channels.length}</small>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <ShieldCheck size={18} />
          <div>
            独立部署<small>OpenCode · 官方 ACP</small>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header>
          <div className="header-left">
            <button
              className="icon-button mobile-menu"
              aria-label="导航菜单"
              onClick={() => setNav(!nav)}
            >
              <Menu size={20} />
            </button>
            <span>工作空间</span>
            <ChevronRight size={14} />
            <b>{pages.find((p) => p.id === page)?.name}</b>
          </div>
          <div className="header-actions">
            <span className="connection">
              <i />
              网关在线
            </span>
            <button
              className="icon-button"
              aria-label="切换主题"
              onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            >
              {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
            </button>
            <span className="avatar">{account[0].toUpperCase()}</span>
            <button
              className="icon-button"
              aria-label="退出登录"
              onClick={() =>
                action("logout", async () => {
                  await mutate("/api/logout");
                  setAccount(null);
                  setCsrf("");
                })
              }
            >
              <LogOut size={17} />
            </button>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">{page.toUpperCase()}</div>
              <h1>{pages.find((p) => p.id === page)?.name}</h1>
              <p>
                {
                  (
                    {
                      overview: "查看网关运行状态、访问趋势与用量。",
                      channels: "连接 OpenCode 提供商，统一管理模型访问。",
                      models: "同步官方目录，按渠道配置别名与访问范围。",
                      keys: "为应用创建独立凭据，控制访问范围和限额。",
                      logs: "查看调用状态与真实用量，不保存对话内容。",
                      playground: "用你的 API Key 发起真实流式调用。",
                      settings: "检查部署状态、安全设置和接口支持范围。",
                    } as any
                  )[page]
                }
              </p>
            </div>
            <button
              className="button secondary"
              onClick={refresh}
              disabled={loading}
            >
              <RefreshCw size={16} className={loading ? "spin" : ""} />
              刷新
            </button>
          </div>
          {page === "overview" && (
            <>
              <div className="metrics">
                {[
                  {
                    label: "累计请求",
                    value: number(overview?.requests),
                    Icon: Activity,
                    sub: `${number(overview?.active || 0)} 个请求运行中`,
                  },
                  {
                    label: "调用成功率",
                    value: overview?.requests
                      ? (
                          ((overview.success || 0) / overview.requests) *
                          100
                        ).toFixed(1) + "%"
                      : "—",
                    Icon: ShieldCheck,
                    sub: `${number(overview?.success || 0)} 次成功调用`,
                  },
                  {
                    label: "累计 Token",
                    value: number(overview?.total_tokens),
                    Icon: Zap,
                    sub: "包含缓存与推理用量",
                  },
                  {
                    label: "可用渠道",
                    value: number(overview?.enabled_channels),
                    Icon: Link2,
                    sub: `共 ${channels.length} 个渠道`,
                  },
                ].map(({ label, value, Icon, sub }) => (
                  <section className="metric" key={label}>
                    <div>
                      {label}
                      <Icon size={18} />
                    </div>
                    <strong>{value}</strong>
                    <small>{sub}</small>
                  </section>
                ))}
              </div>
              <div className="overview-grid">
                <section className="panel">
                  <div className="panel-heading">
                    <h2>请求趋势</h2>
                    <span className="subtle">最近 7 天 · UTC</span>
                  </div>
                  {overview?.trend?.length ? (
                    <div className="chart">
                      {overview.trend.map((d: any) => (
                        <div className="bar-group" key={d.day}>
                          <span>{d.requests}</span>
                          <div className="bar-track">
                            <div
                              className="bar"
                              style={{
                                height: Math.max(
                                  4,
                                  (d.requests /
                                    Math.max(
                                      ...overview.trend.map(
                                        (x: any) => x.requests,
                                      ),
                                    )) *
                                    140,
                                ),
                              }}
                            />
                          </div>
                          <small>{d.day.slice(5)}</small>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <Empty
                      title="尚无调用数据"
                      detail="首次发起 API 调用后，趋势与用量将自动更新。"
                    />
                  )}
                </section>
                <section className="panel start-panel">
                  <div className="panel-heading">
                    <h2>连接你的应用</h2>
                    <ArrowUpRight size={18} />
                  </div>
                  <ol>
                    <li>
                      <b>配置渠道</b>
                      <small>选择提供商并同步模型</small>
                    </li>
                    <li>
                      <b>创建 API Key</b>
                      <small>设定应用访问范围与调用限额</small>
                    </li>
                    <li>
                      <b>发起调用</b>
                      <small>OpenAI 兼容客户端即可接入</small>
                    </li>
                  </ol>
                  <button
                    className="button"
                    onClick={() =>
                      setPage(channels.length ? "keys" : "channels")
                    }
                  >
                    开始配置
                    <ChevronRight size={15} />
                  </button>
                </section>
              </div>
              <LogTable items={logs.slice(0, 6)} title="最近请求" />
            </>
          )}
          {page === "channels" && (
            <>
              <div className="toolbar">
                <span className="subtle">
                  {channels.length} 个渠道 · 保存后请同步模型
                </span>
                <button
                  className="button"
                  onClick={() => setChannelModal("new")}
                >
                  <Plus size={16} />
                  添加渠道
                </button>
              </div>
              <section className="panel table-panel">
                {channels.length ? (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>渠道</th>
                          <th>提供商</th>
                          <th>状态</th>
                          <th>模型</th>
                          <th>最近同步</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {channels.map((c) => (
                          <tr key={c.id}>
                            <td>
                              <b>{c.name}</b>
                              <small className="cell-sub mono">{c.id}</small>
                            </td>
                            <td>
                              {c.providers.join(", ")}
                              <small className="cell-sub">
                                {c.free_only ? "仅免费模型" : "全部模型"} ·
                                优先级 {c.priority}
                              </small>
                            </td>
                            <td>
                              <Badge ok={c.enabled}>
                                {c.enabled ? "启用" : "停用"}
                              </Badge>
                              {c.last_error && (
                                <small className="cell-sub danger-text">
                                  {c.last_error}
                                </small>
                              )}
                            </td>
                            <td>{c.models.length}</td>
                            <td className="subtle">{when(c.synced_at)}</td>
                            <td>
                              <div className="row-actions">
                                <button
                                  className="text-button"
                                  disabled={!!busy}
                                  onClick={() =>
                                    action(c.id, () =>
                                      mutate("/api/channels/" + c.id + "/sync"),
                                    )
                                  }
                                >
                                  {busy === c.id ? "同步中…" : "同步"}
                                </button>
                                <button
                                  className="text-button"
                                  onClick={() => setChannelModal(c)}
                                >
                                  编辑
                                </button>
                                <button
                                  className="icon-button danger-text"
                                  aria-label={"删除 " + c.name}
                                  disabled={!!busy}
                                  onClick={() => {
                                    if (
                                      confirm(
                                        "删除此渠道？历史调用日志会保留。",
                                      )
                                    )
                                      action(c.id, () =>
                                        mutate(
                                          "/api/channels/" + c.id,
                                          undefined,
                                          "DELETE",
                                        ),
                                      );
                                  }}
                                >
                                  <Trash2 size={15} />
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <Empty
                    title="添加第一个渠道"
                    detail="支持官方 OpenCode 提供商；免费模型可不填写上游密钥。"
                    action={
                      <button
                        className="button"
                        onClick={() => setChannelModal("new")}
                      >
                        <Plus size={16} />
                        添加渠道
                      </button>
                    }
                  />
                )}
              </section>
            </>
          )}
          {page === "models" && (
            <>
              <div className="toolbar">
                <label className="search">
                  <Search size={16} />
                  <input
                    placeholder="搜索模型 ID"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
                <span className="subtle">{models.length} 个模型条目</span>
              </div>
              <section className="panel table-panel">
                {models.length ? (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>模型 ID</th>
                          <th>提供商 / 渠道</th>
                          <th>上下文</th>
                          <th>访问状态</th>
                          <th>能力</th>
                        </tr>
                      </thead>
                      <tbody>
                        {models.map((m, i) => (
                          <tr key={m.id + i}>
                            <td>
                              <code>{m.id}</code>
                              <small className="cell-sub">
                                {m.name}
                                {m.id !== m.upstream &&
                                  " · 别名 → " + m.upstream}
                              </small>
                            </td>
                            <td>
                              {m.provider}
                              <small className="cell-sub">{m.channel}</small>
                            </td>
                            <td>{number(m.context)}</td>
                            <td>
                              <Badge ok={m.enabled}>
                                {m.enabled ? "可访问" : "渠道停用"}
                              </Badge>
                            </td>
                            <td>
                              {m.free && <Badge ok>免费目录</Badge>}{" "}
                              <span className="subtle">
                                {m.reasoning ? "文本 · 推理" : "文本"}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <Empty
                    title="暂无已同步模型"
                    detail="到渠道管理同步模型目录，再创建调用密钥。"
                  />
                )}
              </section>
              <p className="footnote">
                目录可见不代表上游调用一定可用。实际权限与免费额度以渠道测试结果为准。
              </p>
            </>
          )}
          {page === "keys" && (
            <>
              <div className="toolbar">
                <span className="subtle">
                  密钥仅创建时显示一次，数据库保存摘要
                </span>
                <button className="button" onClick={() => setKeyModal("new")}>
                  <Plus size={16} />
                  创建 API Key
                </button>
              </div>
              <section className="panel table-panel">
                {keys.length ? (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>名称 / 密钥</th>
                          <th>状态</th>
                          <th>限制</th>
                          <th>模型范围</th>
                          <th>有效期</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {keys.map((k) => (
                          <tr key={k.id}>
                            <td>
                              <b>{k.name}</b>
                              <small className="cell-sub mono">
                                {k.prefix}••••••••
                              </small>
                            </td>
                            <td>
                              <Badge
                                ok={
                                  k.enabled &&
                                  (!k.expires_at ||
                                    k.expires_at > Date.now() / 1000)
                                }
                              >
                                {!k.enabled
                                  ? "已停用"
                                  : k.expires_at &&
                                      k.expires_at <= Date.now() / 1000
                                    ? "已过期"
                                    : "启用"}
                              </Badge>
                            </td>
                            <td>
                              {k.rpm} RPM
                              <small className="cell-sub">
                                每日 {k.daily_requests || "不限"} 次 ·{" "}
                                {k.max_concurrency} 并发
                              </small>
                            </td>
                            <td className="subtle">
                              {k.allowed_models.length
                                ? k.allowed_models.join(", ")
                                : "所有可用模型"}
                            </td>
                            <td className="subtle">{when(k.expires_at)}</td>
                            <td>
                              <div className="row-actions">
                                <button
                                  className="text-button"
                                  onClick={() => setKeyModal(k)}
                                >
                                  编辑
                                </button>
                                <button
                                  className="text-button danger-text"
                                  disabled={!k.enabled || !!busy}
                                  onClick={() => {
                                    if (
                                      confirm(
                                        "停用此密钥？新的调用将立即被拒绝。",
                                      )
                                    )
                                      action(k.id, () =>
                                        mutate(
                                          "/api/keys/" + k.id,
                                          undefined,
                                          "DELETE",
                                        ),
                                      );
                                  }}
                                >
                                  停用
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <Empty
                    title="为应用创建 API Key"
                    detail="每个应用使用独立密钥，便于管理和停用。"
                  />
                )}
              </section>
            </>
          )}
          {page === "logs" && (
            <>
              <div className="toolbar">
                <label className="filter">
                  <SlidersHorizontal size={16} />
                  <select
                    value={filter}
                    onChange={(e) => {
                      setFilter(e.target.value);
                      setLogPage(0);
                    }}
                  >
                    <option value="">全部状态</option>
                    {Object.entries(statusName).map(([v, n]) => (
                      <option key={v} value={v}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
                <span className="subtle">共 {logTotal} 条 · 仅记录元数据</span>
              </div>
              <LogTable items={logs} />
              <div className="pagination">
                <button
                  className="button secondary"
                  disabled={logPage === 0}
                  onClick={() => setLogPage((p) => p - 1)}
                >
                  <ChevronLeft size={15} />
                  上一页
                </button>
                <span>第 {logPage + 1} 页</span>
                <button
                  className="button secondary"
                  disabled={(logPage + 1) * 20 >= logTotal}
                  onClick={() => setLogPage((p) => p + 1)}
                >
                  下一页
                  <ChevronRight size={15} />
                </button>
              </div>
            </>
          )}
          {page === "playground" && (
            <Playground
              models={[
                ...new Set(models.filter((m) => m.enabled).map((m) => m.id)),
              ]}
              notify={notify}
              refresh={refresh}
            />
          )}
          {page === "settings" && (
            <SettingsPage
              config={config}
              audit={audit}
              account={account}
              notify={notify}
              logout={() => {
                setAccount(null);
                setCsrf("");
              }}
            />
          )}
        </main>
        <footer>
          <span>OpenCode ACP Gateway · v{config?.version || "0.1.0"}</span>
          <span>官方 ACP · OpenAI 兼容接口</span>
        </footer>
      </div>
      {toast && (
        <div role="status" className="toast">
          {toast}
          <button
            className="icon-button"
            aria-label="关闭通知"
            onClick={() => setToast("")}
          >
            <X size={15} />
          </button>
        </div>
      )}
      {channelModal && (
        <ChannelForm
          value={channelModal}
          close={() => setChannelModal(null)}
          saved={() => {
            setChannelModal(null);
            refresh();
          }}
          notify={notify}
        />
      )}
      {keyModal && (
        <KeyForm
          value={keyModal}
          close={() => setKeyModal(null)}
          saved={(key) => {
            setKeyModal(null);
            if (key) setCreatedKey(key);
            refresh();
          }}
          notify={notify}
        />
      )}
      {createdKey && (
        <Modal title="API Key 已创建" close={() => setCreatedKey(null)}>
          <div className="modal-body">
            <p>请立即复制并妥善保存。关闭后无法再次查看完整密钥。</p>
            <div className="secret-box">
              <code>{createdKey}</code>
              <button
                className="icon-button"
                aria-label="复制密钥"
                onClick={() =>
                  navigator.clipboard
                    .writeText(createdKey)
                    .then(() => notify("已复制密钥"))
                    .catch(() => notify("复制失败，请手动选择密钥"))
                }
              >
                <Copy size={18} />
              </button>
            </div>
            <p className="subtle">
              Base URL：<code>{location.origin}/v1</code>
            </p>
            <button className="button" onClick={() => setCreatedKey(null)}>
              <Check size={16} />
              我已保存
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
