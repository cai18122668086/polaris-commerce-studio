"use client";

import Link from "next/link";
import { ChevronRight, Pause, RotateCcw, X } from "lucide-react";
import { mockJobs } from "@/lib/mock-data";
import { StatusBadge } from "./status-badge";

export function TaskDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const visibleJobs = mockJobs.slice(0, 4);

  return (
    <>
      {open && <button className="drawer-overlay" onClick={onClose} aria-label="关闭任务抽屉" />}
      <aside className={`task-drawer ${open ? "open" : ""}`} aria-hidden={!open}>
        <div className="drawer-head">
          <div>
            <p>任务中心</p>
            <strong>全站创作进度</strong>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="关闭任务抽屉">
            <X size={19} />
          </button>
        </div>
        <div className="drawer-summary">
          <div>
            <span className="live-dot" />
            <p>正在处理</p>
            <strong>2</strong>
          </div>
          <div>
            <p>今日完成</p>
            <strong>14</strong>
          </div>
          <div>
            <p>待处理异常</p>
            <strong className="danger-text">1</strong>
          </div>
        </div>
        <div className="drawer-list">
          {visibleJobs.map((job) => (
            <article key={job.id} className="drawer-job">
              <img src={job.cover} alt="" />
              <div className="drawer-job__body">
                <div className="drawer-job__top">
                  <StatusBadge status={job.status} />
                  <small>{job.createdAt}</small>
                </div>
                <strong>{job.title}</strong>
                <p>{job.note}</p>
                {(job.status === "processing" || job.status === "queued") && (
                  <div className="mini-progress">
                    <i style={{ width: `${job.progress}%` }} />
                  </div>
                )}
                <div className="drawer-job__meta">
                  <span>{job.count}</span>
                  <span>{job.duration}</span>
                  {job.status === "processing" && (
                    <button aria-label="暂停任务">
                      <Pause size={14} />
                    </button>
                  )}
                  {job.status === "failed" && (
                    <button aria-label="重试任务">
                      <RotateCcw size={14} />
                    </button>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>
        <Link href="/jobs" className="drawer-footer-link" onClick={onClose}>
          查看全部生成记录
          <ChevronRight size={16} />
        </Link>
      </aside>
    </>
  );
}

