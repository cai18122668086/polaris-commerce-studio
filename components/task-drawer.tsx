"use client";

import Link from "next/link";
import { Ban, ChevronRight, LoaderCircle, RotateCcw, X } from "lucide-react";

import { useCancelJob, useJobs, useRetryJob } from "@/features/jobs/api/jobs";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { formatDate, jobCount, jobNote, jobTitle } from "@/lib/jobs/presentation";
import { allowsJobAction } from "@/lib/jobs/actions";
import { StatusBadge } from "./status-badge";

export function TaskDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
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

  return (
    <>
      {open && <button className="drawer-overlay" onClick={onClose} aria-label="关闭任务抽屉" />}
      <aside
        className={`task-drawer ${open ? "open" : ""}`}
        aria-hidden={!open}
        inert={open ? undefined : true}
      >
        <div className="drawer-head">
          <div><p>任务中心 · API</p><strong>内部 mock 进度</strong></div>
          <button className="icon-button" onClick={onClose} aria-label="关闭任务抽屉"><X size={19} /></button>
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
