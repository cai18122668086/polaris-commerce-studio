"use client";

import Link from "next/link";
import { Ban, ChevronRight, LoaderCircle, RotateCcw, X } from "lucide-react";
import { useEffect, useRef, type RefObject } from "react";

import { useCancelJob, useJobs, useRetryJob } from "@/features/jobs/api/jobs";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { formatDate, jobCount, jobNote, jobTitle } from "@/lib/jobs/presentation";
import { allowsJobAction } from "@/lib/jobs/actions";
import { StatusBadge } from "./status-badge";

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export function TaskDrawer({
  open,
  onClose,
  triggerRef,
}: {
  open: boolean;
  onClose: () => void;
  triggerRef: RefObject<HTMLButtonElement | null>;
}) {
  const drawerRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef(false);
  const { workspace } = useWorkspace();
  const jobs = useJobs(workspace?.id, { limit: 8 });
  const cancel = useCancelJob(workspace?.id);
  const retry = useRetryJob(workspace?.id);
  const visibleJobs = jobs.data?.items.slice(0, 4) ?? [];
  const runCancel = (job: (typeof visibleJobs)[number]) => {
    if (!allowsJobAction(job.allowed_actions, "cancel")) return;
    cancel.mutate({ jobId: job.id, allowedActions: job.allowed_actions });
  };
  const runRetry = (job: (typeof visibleJobs)[number]) => {
    if (!allowsJobAction(job.allowed_actions, "retry")) return;
    retry.mutate({ jobId: job.id, allowedActions: job.allowed_actions });
  };

  useEffect(() => {
    if (open) {
      restoreFocusRef.current = true;
      const frame = requestAnimationFrame(() => closeButtonRef.current?.focus());
      return () => cancelAnimationFrame(frame);
    }
    if (restoreFocusRef.current) {
      restoreFocusRef.current = false;
      triggerRef.current?.focus();
    }
  }, [open, triggerRef]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;
      const focusable = Array.from(
        drawerRef.current.querySelectorAll<HTMLElement>(focusableSelector),
      ).filter((element) => !element.hasAttribute("disabled"));
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) {
        event.preventDefault();
        drawerRef.current.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!drawerRef.current.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open]);

  return (
    <>
      {open && (
        <button
          className="drawer-overlay"
          onClick={onClose}
          aria-label="关闭任务抽屉"
          tabIndex={-1}
        />
      )}
      <aside
        ref={drawerRef}
        id="task-drawer"
        className={`task-drawer ${open ? "open" : ""}`}
        role="dialog"
        aria-modal={open ? true : undefined}
        aria-labelledby="task-drawer-title"
        aria-hidden={!open}
        inert={open ? undefined : true}
        tabIndex={-1}
      >
        <div className="drawer-head">
          <div><p>任务中心 · API</p><h2 id="task-drawer-title">内部 mock 进度</h2></div>
          <button ref={closeButtonRef} className="icon-button" onClick={onClose} aria-label="关闭任务抽屉"><X size={19} /></button>
        </div>
        <div className="drawer-summary">
          <div><span className="live-dot" /><p>正在处理</p><strong>{visibleJobs.filter((job) => ["queued", "planning", "processing"].includes(job.status)).length}</strong></div>
          <div><p>已完成</p><strong>{visibleJobs.filter((job) => job.status === "completed").length}</strong></div>
          <div><p>待处理异常</p><strong className="danger-text">{visibleJobs.filter((job) => ["failed", "partial"].includes(job.status)).length}</strong></div>
        </div>
        <div className="drawer-list">
          {jobs.isPending && <div className="api-state"><LoaderCircle className="spin" /><p>加载任务中…</p></div>}
          {!jobs.isPending && visibleJobs.length === 0 && <div className="api-state"><p>尚无内部 mock 任务。</p></div>}
          {visibleJobs.map((job) => (
            <article key={job.id} className="drawer-job drawer-job--api">
              <div className="drawer-job__body">
                <div className="drawer-job__top"><StatusBadge status={job.status} /><small>{formatDate(job.created_at)}</small></div>
                <strong>{jobTitle(job)}</strong><p>{jobNote(job)}</p>
                {["processing", "queued", "planning"].includes(job.status) && <div className="mini-progress"><i style={{ width: `${job.progress}%` }} /></div>}
                <div className="drawer-job__meta">
                  <span>{jobCount(job)}</span><span>{job.stage ?? "—"}</span>
                  {allowsJobAction(job.allowed_actions, "cancel") && <button aria-label={`取消任务 ${jobTitle(job)}`} onClick={() => runCancel(job)}><Ban size={14} /></button>}
                  {allowsJobAction(job.allowed_actions, "retry") && <button aria-label={`重试失败项 ${jobTitle(job)}`} onClick={() => runRetry(job)}><RotateCcw size={14} /></button>}
                </div>
              </div>
            </article>
          ))}
        </div>
        <Link href="/jobs" className="drawer-footer-link" onClick={onClose}>查看全部生成记录<ChevronRight size={16} /></Link>
      </aside>
    </>
  );
}
