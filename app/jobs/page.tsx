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
  X,
} from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { StatusBadge } from "@/components/status-badge";
import {
  useCancelJob,
  useJob,
  useJobs,
  useRetryJob,
} from "@/features/jobs/api/jobs";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { errorMessage } from "@/lib/api/request";
import type { Job, JobStatus } from "@/lib/api/types";
import {
  canCancel,
  formatDate,
  jobCount,
  jobNote,
  jobTitle,
  jobTypeLabel,
} from "@/lib/jobs/presentation";

const tabFilters: Record<string, JobStatus[] | undefined> = {
  all: undefined,
  active: ["queued", "planning", "awaiting_confirmation", "processing", "cancelling"],
  completed: ["completed"],
  attention: ["partial", "failed"],
  draft: ["draft"],
};

function JobDetailPanel({
  workspaceId,
  jobId,
  onClose,
}: {
  workspaceId: string;
  jobId: string;
  onClose: () => void;
}) {
  const detail = useJob(workspaceId, jobId);
  return (
    <>
      <button className="drawer-overlay" onClick={onClose} aria-label="关闭任务详情" />
      <aside className="task-drawer open" aria-label="任务详情">
        <div className="drawer-head">
          <div><p>API 任务详情</p><strong>{detail.data ? jobTitle(detail.data) : "正在加载"}</strong></div>
          <button className="icon-button" onClick={onClose} aria-label="关闭任务详情"><X size={19} /></button>
        </div>
        {detail.isPending && <div className="api-state"><LoaderCircle className="spin" /><p>正在轮询任务详情…</p></div>}
        {detail.error && <div className="api-state api-state--error"><FileWarning /><p>{errorMessage(detail.error)}</p></div>}
        {detail.data && (
          <div className="job-detail-content">
            <StatusBadge status={detail.data.status} />
            <dl>
              <div><dt>任务编号</dt><dd>{detail.data.id}</dd></div>
              <div><dt>进度</dt><dd>{detail.data.progress}%</dd></div>
              <div><dt>成功 / 失败</dt><dd>{detail.data.succeeded_item_count} / {detail.data.failed_item_count}</dd></div>
              <div><dt>阶段</dt><dd>{detail.data.stage ?? "—"}</dd></div>
              <div><dt>API 请求数</dt><dd>{detail.data.api_request_count}</dd></div>
            </dl>
            <p>{jobNote(detail.data)}</p>
            {detail.data.error_message && <div className="api-inline-error">{detail.data.error_message}</div>}
            <small>此详情来自零付费 mock 后端，不代表真实图片 Provider 已启用。</small>
          </div>
        )}
      </aside>
    </>
  );
}

export default function JobsPage() {
  const [tab, setTab] = useState("all");
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"list" | "grid">("list");
  const [selectedJobId, setSelectedJobId] = useState<string>();
  const { workspace, error: workspaceError } = useWorkspace();
  const jobsQuery = useJobs(workspace?.id, { statuses: tabFilters[tab], limit: 100 });
  const cancel = useCancelJob(workspace?.id);
  const retry = useRetryJob(workspace?.id);
  const jobs = useMemo(
    () =>
      (jobsQuery.data?.items ?? []).filter((job) =>
        `${job.display_name ?? ""} ${job.id}`.toLowerCase().includes(query.toLowerCase()),
      ),
    [jobsQuery.data, query],
  );
  const allJobs = jobsQuery.data?.items ?? [];
  const actionError = cancel.error ?? retry.error;

  const runCancel = (job: Job) => {
    if (window.confirm("确认取消此内部 mock 任务？已进入终态的项目不会回滚。")) cancel.mutate(job.id);
  };

  return (
    <AppShell>
      <div className="content-page">
        <div className="page-title-row">
          <div><span>资产管理 · API 已连接</span><h1>生成记录</h1><p>查看真实持久化的 mock 任务状态、错误与恢复动作。</p></div>
        </div>
        <section className="job-stats">
          <div><span className="stat-icon stat-icon--violet"><Sparkles size={19} /></span><p>当前加载</p><strong>{jobsQuery.data?.total ?? allJobs.length}</strong><small>由 API 列表派生</small></div>
          <div><span className="stat-icon stat-icon--green"><CheckCircle2 size={19} /></span><p>已完成</p><strong>{allJobs.filter((job) => job.status === "completed").length}</strong><small>mock runner 终态</small></div>
          <div><span className="stat-icon stat-icon--blue"><Clock3 size={19} /></span><p>处理中</p><strong>{allJobs.filter((job) => ["queued", "planning", "processing"].includes(job.status)).length}</strong><small>每 2 秒轮询</small></div>
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
            <label className="search-field"><Search size={16} /><input placeholder="搜索任务名称或编号" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
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
            <div className="empty-state"><Search size={28} /><h3>没有匹配任务</h3><p>可从两个工作台创建第一条内部 mock 任务。</p><button className="secondary-button" onClick={() => { setQuery(""); setTab("all"); }}>清除筛选</button></div>
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
                  <div className="record-meta"><span><Clock3 size={14} />{formatDate(job.created_at)}</span><strong>{jobCount(job)}</strong><small>{job.stage ?? "等待阶段更新"}</small></div>
                  <div className="record-actions">
                    {["failed", "partial"].includes(job.status) && <button title="重试失败项" className="emphasis" onClick={() => retry.mutate(job.id)} disabled={retry.isPending}><RotateCcw size={16} /></button>}
                    {canCancel(job.status, job.allowed_actions) && <button title="取消任务" onClick={() => runCancel(job)} disabled={cancel.isPending}><Ban size={16} /></button>}
                    <button title="查看详情" className="row-open" onClick={() => setSelectedJobId(job.id)}><ArrowUpRight size={16} /></button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
      {workspace && selectedJobId && <JobDetailPanel workspaceId={workspace.id} jobId={selectedJobId} onClose={() => setSelectedJobId(undefined)} />}
    </AppShell>
  );
}
