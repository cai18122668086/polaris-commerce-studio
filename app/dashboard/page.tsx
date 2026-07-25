import Link from "next/link";
import {
  ArrowRight,
  Clock3,
  ImagePlus,
  Sparkles,
} from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { ProgressRing } from "@/components/progress-ring";
import { StatusBadge } from "@/components/status-badge";
import { mockJobs } from "@/lib/mock-data";

export const metadata = {
  title: "个人控制台",
};

export default function DashboardPage() {
  return (
    <AppShell>
      <div className="content-page personal-dashboard">
        <div className="page-title-row">
          <div>
            <span>个人工作台</span>
            <h1>个人控制台</h1>
            <p>查看创作概况、剩余额度并继续最近任务。</p>
          </div>
          <Link href="/#tools" className="primary-button">
            <Sparkles size={16} />
            新建创作
          </Link>
        </div>

        <section className="overview-strip">
          <div>
            <p>今日创作</p>
            <strong>16</strong>
            <span>较昨日 +23%</span>
          </div>
          <div>
            <p>完成图片</p>
            <strong>42</strong>
            <span>含 3 套详情图</span>
          </div>
          <div>
            <p>预计节省</p>
            <strong>5.8h</strong>
            <span>按同类人工流程估算</span>
          </div>
          <div className="overview-strip__progress">
            <ProgressRing value={68} label="月度额度" />
            <span>
              <p>本月创作额度</p>
              <strong>268 次可用</strong>
              <small>8 月 1 日更新</small>
            </span>
          </div>
        </section>

        <section className="dashboard-grid">
          <div className="recent-jobs-card">
            <div className="card-heading">
              <div>
                <span>最近任务</span>
                <h2>继续你的创作</h2>
              </div>
              <Link href="/jobs">
                查看全部
                <ArrowRight size={15} />
              </Link>
            </div>
            <div className="recent-job-list">
              {mockJobs.slice(0, 3).map((job) => (
                <article key={job.id}>
                  <img src={job.cover} alt="" />
                  <div>
                    <div className="recent-job__title">
                      <strong>{job.title}</strong>
                      <StatusBadge status={job.status} />
                    </div>
                    <p>{job.note}</p>
                    <span>
                      <Clock3 size={13} />
                      {job.createdAt}
                      <i>·</i>
                      {job.count}
                    </span>
                  </div>
                  <Link
                    href={
                      job.type === "局部修改"
                        ? "/workspace/local-edit"
                        : "/workspace/detail-pack"
                    }
                  >
                    <ArrowRight size={16} />
                  </Link>
                </article>
              ))}
            </div>
          </div>

          <div className="dashboard-shortcuts">
            <div className="card-heading">
              <div>
                <span>快捷开始</span>
                <h2>常用创作入口</h2>
              </div>
              <ImagePlus size={22} />
            </div>
            <Link href="/workspace/local-edit">
              <strong>局部修改</strong>
              <span>精准修改选中区域</span>
              <ArrowRight size={16} />
            </Link>
            <Link href="/workspace/detail-pack">
              <strong>商品详情图</strong>
              <span>规划并生成整套详情页</span>
              <ArrowRight size={16} />
            </Link>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
