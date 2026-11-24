"use client";

import Link from "next/link";
import { ListChecks } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { GenerationJob } from "@/features/video-studio/library";
import { settledSince, taskCenterItems, type TaskItem } from "@/features/video-studio/task-center";
import type { ToastTone } from "./studio-toast";
import styles from "./video-studio.module.css";

const activeRoute = "/api/v1/video-studio/workspaces/{workspace_id}/editing-works/active" as const;

function readPreference(key: string) {
  try { return localStorage.getItem(key) === "on"; } catch { return false; }
}

/** Header entry listing unfinished edits and generations; optional browser notice when one settles. */
export function TaskCenter({ userId, workspaceId, jobs, notify }: { userId: string; workspaceId: string; jobs: GenerationJob[]; notify: (text: string, tone?: ToastTone) => void }) {
  const [open, setOpen] = useState(false);
  const preferenceKey = `polaris-video-task-notify:${userId}:${workspaceId}`;
  const [browserNotice, setBrowserNotice] = useState(() => readPreference(preferenceKey));
  const panel = useRef<HTMLDivElement>(null);
  const active = useQuery({
    queryKey: ["video-studio", "editing-works-active", userId, workspaceId],
    staleTime: 0,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET(activeRoute, {
      params: { path: { workspace_id: workspaceId } },
      signal: AbortSignal.any([signal, AbortSignal.timeout(12000)]),
    })),
    refetchInterval: query => query.state.data?.items.some(item => item.status === "queued" || item.status === "running") ? 15000 : 60000,
  });
  const items = taskCenterItems(active.data?.items ?? [], jobs);
  const previous = useRef<TaskItem[] | undefined>(undefined);
  useEffect(() => {
    if (!active.isSuccess) return;
    const settled = previous.current ? settledSince(previous.current, items) : [];
    previous.current = items;
    for (const item of settled) {
      notify(`${item.title} 有新进展，可在任务中查看`, "success");
      if (browserNotice && typeof Notification !== "undefined" && Notification.permission === "granted" && document.visibilityState !== "visible") {
        new Notification("极光商绘 · 视频任务", { body: `${item.title} 有新进展`, tag: item.id });
      }
    }
  });
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !panel.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  const toggleNotice = async (on: boolean) => {
    if (on && typeof Notification !== "undefined" && Notification.permission !== "granted") {
      const permission = await Notification.requestPermission().catch(() => "denied" as NotificationPermission);
      if (permission !== "granted") { notify("浏览器未允许通知，仍会在页面内提示", "warning"); on = false; }
    }
    setBrowserNotice(on);
    try { localStorage.setItem(preferenceKey, on ? "on" : "off"); } catch { /* preference stays for this visit */ }
  };
  const attention = items.filter(item => item.needsUser).length;

  return <div className={styles.taskCenter} ref={panel}>
    <button type="button" className={styles.taskCenterButton} aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen(value => !value)}>
      <ListChecks size={16} />任务{items.length > 0 && <span className={styles.taskCount}>{items.length}</span>}
    </button>
    {open && <div className={styles.taskPanel} role="dialog" aria-label="任务">
      <header><b>任务</b><span>{attention ? `${attention} 项等你处理` : items.length ? "处理中" : ""}</span></header>
      {active.isError && <p role="alert">暂时无法读取剪辑任务。 <button type="button" className={styles.textButton} onClick={() => void active.refetch()}>重试</button></p>}
      {!items.length && !active.isError && <p className={styles.taskEmpty}>{active.isPending ? "正在读取…" : "没有进行中的任务"}</p>}
      {!!items.length && <ul>{items.map(item => <li key={item.id}>
        <Link href={item.href} onClick={() => setOpen(false)}>
          <span className={styles.taskTitle}>{item.title}</span>
          <span className={item.needsUser ? styles.taskAttention : styles.taskStatus}>{item.label}</span>
        </Link>
      </li>)}</ul>}
      <footer>
        <label><input type="checkbox" checked={browserNotice} onChange={event => void toggleNotice(event.target.checked)} />页面在后台时，完成后用浏览器通知我</label>
        <Link href="/video-studio/works" onClick={() => setOpen(false)}>查看全部作品</Link>
      </footer>
    </div>}
  </div>;
}
