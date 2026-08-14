"use client";

import { useMemo, useState } from "react";
import {
  ArrowUpRight,
  Ban,
  CheckCircle2,
  Clock3,
  FileWarning,
  LayoutGrid,
  List,
  LoaderCircle,
  RotateCcw,
  Search,
  Sparkles,
  TimerReset,
} from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { StatusBadge } from "@/components/status-badge";
import {
  useCancelJob,
  useJobs,
  useRetryJob,
  useConfirmPlan,
} from "@/features/jobs/api/jobs";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { errorMessage } from "@/lib/api/request";
import type { Job, JobDetail, JobStatus } from "@/lib/api/types";
import {
  formatDate,
  jobCount,
  jobNote,
  jobTitle,
  jobTypeLabel,
} from "@/lib/jobs/presentation";
import { allowsJobAction } from "@/lib/jobs/actions";
import { JobDetailPanel } from "@/features/jobs/components/job-detail-panel";

const tabFilters: Record<string, JobStatus[] | undefined> = {
  all: undefined,
  active: ["queued", "planning", "awaiting_confirmation", "processing", "cancelling"],
  completed: ["completed"],
  attention: ["partial", "failed"],
  draft: ["draft"],
};

export default function JobsPage() {
  const [tab, setTab] = useState("all");
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"list" | "grid">("list");
  const [selectedJobId, setSelectedJobId] = useState<string>();
  const { workspace, error: workspaceError } = useWorkspace();
  const jobsQuery = useJobs(workspace?.id, { statuses: tabFilters[tab], limit: 100 });
  const cancel = useCancelJob(workspace?.id);
  const retry = useRetryJob(workspace?.id);
  const confirmPlan = useConfirmPlan(workspace?.id);
  const jobs = useMemo(
    () =>
      (jobsQuery.data?.items ?? []).filter((job) =>
        `${job.display_name ?? ""} ${job.id}`.toLowerCase().includes(query.toLowerCase()),
      ),
    [jobsQuery.data, query],
  );
  const allJobs = jobsQuery.data?.items ?? [];
  const actionError = cancel.error ?? retry.error ?? confirmPlan.error;

  const runCancel = (job: Job | JobDetail) => {
    if (
      !allowsJobAction(job.allowed_actions, "cancel") ||
      !window.confirm("确认取消此任务？已经完成的任务不会回滚。")
    ) {
      return;
    }
    cancel.mutate({ jobId: job.id, allowedActions: job.allowed_actions });
  };

  const runRetry = (job: Job | JobDetail, itemId?: string) => {
    if (!allowsJobAction(job.allowed_actions, "retry")) return;
    retry.mutate({
      jobId: job.id,
      allowedActions: job.allowed_actions,
      scope: itemId ? "selected" : "failed",
      itemIds: itemId ? [itemId] : [],
    });
  };

  const runConfirmPlan = (job: JobDetail) => {
    if (!job.plan || !allowsJobAction(job.allowed_actions, "confirm_plan")) return;
    confirmPlan.mutate({
      jobId: job.id,
      allowedActions: job.allowed_actions,
      revision: job.plan.revision,
    });
  };

  return (
    <AppShell>
      <div className="content-page">
        <div className="page-title-row">
          <div><span>创作管理</span><h1>生成记录</h1><p>查看任务状态、生成结果、错误信息与可用操作。</p></div>
        </div>
        <section className="job-stats">
          <div><span className="stat-icon stat-icon--violet"><Sparkles size={19} /></span><p>当前加载</p><strong>{jobsQuery.data?.total ?? allJobs.length}</strong><small>由任务列表统计</small></div>
          <div><span className="stat-icon stat-icon--green"><CheckCircle2 size={19} /></span><p>已完成</p><strong>{allJobs.filter((job) => job.status === "completed").length}</strong><small>已完成任务</small></div>
          <div><span className="stat-icon stat-icon--blue"><Clock3 size={19} /></span><p>处理中</p><strong>{allJobs.filter((job) => ["queued", "planning", "processing"].includes(job.status)).length}</strong><small>状态自动同步</small></div>
          <div><span className="stat-icon stat-icon--orange"><TimerReset size={19} /></span><p>需处理</p><strong>{allJobs.filter((job) => ["partial", "failed", "awaiting_confirmation"].includes(job.status)).length}</strong><small>可恢复或确认</small></div>
        </section>

        <section className="records-card" aria-busy={jobsQuery.isPending}>
          <div className="record-tabs">
            <div>
              {[
                ["all", "全部任务"],
                ["active", "进行中"],
                ["completed", "已完成"],
                ["attention", "需处理"],
                ["draft", "草稿"],
              ].map(([key, label]) => (
                <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>{label}</button>
              ))}
            </div>
            <div className="view-toggle">
              <button className={view === "list" ? "active" : ""} onClick={() => setView("list")} aria-label="列表视图"><List size={17} /></button>
              <button className={view === "grid" ? "active" : ""} onClick={() => setView("grid")} aria-label="网格视图"><LayoutGrid size={17} /></button>
            </div>
          </div>
          <div className="records-toolbar">
            <label className="search-field" htmlFor="job-search"><span className="visually-hidden">搜索任务</span><Search size={16} /><input id="job-search" placeholder="搜索任务名称或编号" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
            <span>{jobs.length} 个任务</span>
          </div>

          {(workspaceError || jobsQuery.error) && (
            <div className="api-state api-state--error" role="alert">
              <FileWarning size={24} /><div><strong>任务服务暂时不可用</strong><p>{errorMessage(workspaceError ?? jobsQuery.error)}</p></div>
              <button className="secondary-button" onClick={() => void jobsQuery.refetch()}>重试</button>
            </div>
          )}
          {actionError && <div className="api-inline-error" role="alert">{errorMessage(actionError)}</div>}
          {jobsQuery.isPending && <div className="api-state"><LoaderCircle className="spin" /><p>正在加载任务…</p></div>}
          {!jobsQuery.isPending && !jobsQuery.error && jobs.length === 0 && (
            <div className="empty-state"><Search size={28} /><h3>没有匹配任务</h3><p>可以从首页选择一个功能创建第一条任务。</p><button className="secondary-button" onClick={() => { setQuery(""); setTab("all"); }}>清除筛选</button></div>
          )}
          {jobs.length > 0 && (
            <div className={view === "grid" ? "records-grid" : "records-list"}>
              {jobs.map((job) => (
                <article key={job.id} className="record-row">
                  <div className="record-cover api-job-cover"><Sparkles size={24} /><span>{jobTypeLabel(job.type)}</span></div>
                  <div className="record-main">
                    <div><StatusBadge status={job.status} /><small>{job.id}</small></div>
                    <h3>{jobTitle(job)}</h3><p>{jobNote(job)}</p>
                    {["queued", "planning", "processing", "cancelling"].includes(job.status) && <div className="record-progress"><i style={{ width: `${job.progress}%` }} /><span>{job.progress}%</span></div>}
                  </div>
                  <div className="record-meta"><span><Clock3 size={14} />{formatDate(job.created_at)}</span><strong>{jobCount(job)}</strong><small>状态自动同步</small></div>
                  <div className="record-actions">
                    {allowsJobAction(job.allowed_actions, "retry") && <button aria-label={`重试任务 ${jobTitle(job)}`} title="重试失败项" className="emphasis" onClick={() => runRetry(job)} disabled={retry.isPending}><RotateCcw size={16} /></button>}
                    {allowsJobAction(job.allowed_actions, "cancel") && <button aria-label={`取消任务 ${jobTitle(job)}`} title="取消任务" onClick={() => runCancel(job)} disabled={cancel.isPending}><Ban size={16} /></button>}
                    <button aria-label={`查看任务详情 ${jobTitle(job)}`} title="查看详情" className="row-open" onClick={() => setSelectedJobId(job.id)}><ArrowUpRight size={16} /></button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
      {workspace && selectedJobId && (
        <JobDetailPanel
          workspaceId={workspace.id}
          jobId={selectedJobId}
          onClose={() => setSelectedJobId(undefined)}
          onCancel={runCancel}
          onRetry={runRetry}
          onRetryItem={(job, itemId) => runRetry(job, itemId)}
          onConfirmPlan={runConfirmPlan}
          cancelPending={cancel.isPending}
          retryPending={retry.isPending}
          confirmPending={confirmPlan.isPending}
        />
      )}
    </AppShell>
  );
}
