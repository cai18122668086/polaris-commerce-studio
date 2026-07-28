"use client";

import Link from "next/link";
import { ArrowRight, Clock3, ImagePlus, LoaderCircle, Sparkles } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { ProgressRing } from "@/components/progress-ring";
import { StatusBadge } from "@/components/status-badge";
import { useJobs } from "@/features/jobs/api/jobs";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { formatDate, jobCount, jobNote, jobTitle } from "@/lib/jobs/presentation";

export default function DashboardPage() {
  const { workspace } = useWorkspace();
  const jobs = useJobs(workspace?.id, { limit: 20 });
  const items = jobs.data?.items ?? [];
  const completed = items.filter((job) => job.status === "completed").length;
  const active = items.filter((job) => ["queued", "planning", "processing"].includes(job.status)).length;

  return (
    <AppShell>
      <div className="content-page personal-dashboard">
        <div className="page-title-row">
          <div><span>个人工作台 · 内部 mock</span><h1>个人控制台</h1><p>概况由当前 API 列表诚实派生，不代表生产用量或 Provider 能力。</p></div>
          <Link href="/#tools" className="primary-button"><Sparkles size={16} />新建 mock 创作</Link>
        </div>
        <section className="overview-strip">
          <div><p>已加载任务</p><strong>{jobs.data?.total ?? items.length}</strong><span>API 当前窗口</span></div>
          <div><p>mock 已完成</p><strong>{completed}</strong><span>零付费 runner 终态</span></div>
          <div><p>正在处理</p><strong>{active}</strong><span>自动轮询更新</span></div>
          <div className="overview-strip__progress"><ProgressRing value={0} label="真实额度" /><span><p>真实 Provider</p><strong>尚未启用</strong><small>不会产生付费调用</small></span></div>
        </section>
        <section className="dashboard-grid">
          <div className="recent-jobs-card">
            <div className="card-heading"><div><span>最近任务</span><h2>继续内部测试</h2></div><Link href="/jobs">查看全部<ArrowRight size={15} /></Link></div>
            {jobs.isPending && <div className="api-state"><LoaderCircle className="spin" /><p>加载任务中…</p></div>}
            <div className="recent-job-list">
              {items.slice(0, 3).map((job) => (
                <article key={job.id}>
                  <div className="api-job-cover"><Sparkles size={20} /></div>
                  <div><div className="recent-job__title"><strong>{jobTitle(job)}</strong><StatusBadge status={job.status} /></div><p>{jobNote(job)}</p><span><Clock3 size={13} />{formatDate(job.created_at)}<i>·</i>{jobCount(job)}</span></div>
                  <Link href="/jobs"><ArrowRight size={16} /></Link>
                </article>
              ))}
            </div>
          </div>
          <div className="dashboard-shortcuts">
            <div className="card-heading"><div><span>快捷开始</span><h2>内部 mock 工作流</h2></div><ImagePlus size={22} /></div>
            <Link href="/workspace/local-edit"><strong>局部修改</strong><span>上传素材并创建 mock 任务</span><ArrowRight size={16} /></Link>
            <Link href="/workspace/detail-pack"><strong>商品详情图</strong><span>规划确认仅进入 mock runner</span><ArrowRight size={16} /></Link>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
