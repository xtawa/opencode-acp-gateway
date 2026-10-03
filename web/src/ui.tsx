import React, { useEffect, useRef } from "react";
import { Database, X } from "lucide-react";
export const number = (n: number | null | undefined) =>
  n == null ? "—" : new Intl.NumberFormat("zh-CN").format(n);
export const when = (ts: number | null) =>
  ts ? new Date(ts * 1000).toLocaleString("zh-CN") : "—";
export const errorText = (e: unknown) =>
  e instanceof Error ? e.message : "请求失败";
export const statusName: Record<string, string> = {
  success: "成功",
  running: "运行中",
  error: "失败",
  cancelled: "已取消",
  interrupted: "已中断",
};
export function Empty({
  title,
  detail,
  action,
}: {
  title: string;
  detail?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <Database size={28} />
      <strong>{title}</strong>
      {detail && <p>{detail}</p>}
      {action}
    </div>
  );
}
export function Badge({
  ok,
  children,
}: {
  ok: boolean;
  children: React.ReactNode;
}) {
  return (
    <span className={"badge " + (ok ? "good" : "neutral")}>{children}</span>
  );
}
export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
export function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (x: boolean) => void;
}) {
  return (
    <label className="toggle">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}
export function Modal({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: React.ReactNode;
}) {
  const closeRef = useRef(close);
  closeRef.current = close;
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const fn = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRef.current();
      if (e.key === "Tab") {
        const items = Array.from(
          dialogRef.current?.querySelectorAll<HTMLElement>(
            "button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), a[href]",
          ) || [],
        );
        const first = items[0],
          last = items.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener("keydown", fn);
    const active = document.activeElement as HTMLElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const timer = setTimeout(
      () =>
        (
          dialogRef.current?.querySelector<HTMLElement>(
            "input, textarea, select",
          ) || dialogRef.current?.querySelector<HTMLElement>("button")
        )?.focus(),
      0,
    );
    return () => {
      window.removeEventListener("keydown", fn);
      clearTimeout(timer);
      document.body.style.overflow = overflow;
      active?.focus();
    };
  }, []);
  return (
    <div className="overlay" onClick={close}>
      <section
        ref={dialogRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-button" onClick={close} aria-label="关闭">
            <X size={18} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}
