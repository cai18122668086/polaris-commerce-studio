"use client";

import { useState } from "react";
import { LoaderCircle } from "lucide-react";
import styles from "./finish-works.module.css";

/** 页内二次确认（不用浏览器弹窗）：先出「删除」，点了变成「确定删除？删除 / 取消」。 */
export function ConfirmDelete({ onConfirm, label = "删除", className }: { onConfirm: () => Promise<unknown> | void; label?: string; className?: string }) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!asking) return <button type="button" className={className ?? styles.textAction} onClick={event => { event.stopPropagation(); setAsking(true); }}>{label}</button>;
  return <span className={styles.confirm} role="group" aria-label="确认删除">
    <span>从作品里移除？文件会保留</span>
    <button type="button" className={styles.confirmYes} disabled={busy} onClick={async event => { event.stopPropagation(); setBusy(true); try { await onConfirm(); } finally { setBusy(false); setAsking(false); } }}>{busy ? <LoaderCircle className={styles.spin} size={13} /> : null}删除</button>
    <button type="button" className={styles.textAction} disabled={busy} onClick={event => { event.stopPropagation(); setAsking(false); }}>取消</button>
  </span>;
}

