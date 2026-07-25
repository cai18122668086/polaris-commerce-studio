"use client";

import { useMemo, useState } from "react";
import {
  ArrowUpRight,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Copy,
  Download,
  Filter,
  LayoutGrid,
  List,
  MoreHorizontal,
  PauseCircle,
  Plus,
  RotateCcw,
  Search,
  Sparkles,
  TimerReset,
} from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { StatusBadge } from "@/components/status-badge";
import { mockJobs } from "@/lib/mock-data";

const tabs = [
  { key: "all", label: "全部任务", count: 28 },
  { key: "active", label: "进行中", count: 2 },
  { key: "completed", label: "已完成", count: 19 },
  { key: "attention", label: "需处理", count: 2 },
  { key: "draft", label: "草稿", count: 5 },
];

export default function JobsPage() {
  const [tab, setTab] = useState("all");
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"list" | "grid">("list");
  const visibleJobs = useMemo(
    () =>
      mockJobs.filter((job) => {
        const matchesQuery = job.title.toLowerCase().includes(query.toLowerCase());
        if (!matchesQuery) return false;
        if (tab === "active") return ["queued", "planning", "processing"].includes(job.status);
        if (tab === "completed") return job.status === "completed";
        if (tab === "attention") return ["partial", "failed"].includes(job.status);
        if (tab === "draft") return job.status === "draft";
        return true;
      }),
    [query, tab],
  );

  return (
    <AppShell>
      <div className="content-page">
        <div className="page-title-row">
          <div>
            <span>资产管理</span>
            <h1>生成记录</h1>
            <p>集中查看、继续和复用每一次创作任务。</p>
          </div>
          <button className="primary-button">
            <Plus size={17} />
            新建创作
          </button>
        </div>

        <section className="job-stats">
          <div>
            <span className="stat-icon stat-icon--violet">
              <Sparkles size={19} />
            </span>
            <p>本月生成</p>
            <strong>128</strong>
            <small>比上月同期 +18%</small>
          </div>
          <div>
            <span className="stat-icon stat-icon--green">
              <CheckCircle2 size={19} />
            </span>
            <p>成功交付</p>
            <strong>96.4%</strong>
            <small>共 312 张图片</small>
          </div>
          <div>
            <span className="stat-icon stat-icon--blue">
              <Clock3 size={19} />
            </span>
            <p>平均耗时</p>
            <strong>4m 18s</strong>
            <small>较上周缩短 36 秒</small>
          </div>
          <div>
            <span className="stat-icon stat-icon--orange">
              <TimerReset size={19} />
            </span>
            <p>等待处理</p>
            <strong>2</strong>
            <small>1 项可单页重试</small>
          </div>
        </section>

        <section className="records-card">
          <div className="record-tabs">
            <div>
              {tabs.map((item) => (
                <button
                  key={item.key}
                  className={tab === item.key ? "active" : ""}
                  onClick={() => setTab(item.key)}
                >
                  {item.label}
                  <span>{item.count}</span>
                </button>
              ))}
            </div>
            <div className="view-toggle">
              <button
                className={view === "list" ? "active" : ""}
                onClick={() => setView("list")}
                aria-label="列表视图"
              >
                <List size={17} />
              </button>
              <button
                className={view === "grid" ? "active" : ""}
                onClick={() => setView("grid")}
                aria-label="网格视图"
              >
                <LayoutGrid size={17} />
              </button>
            </div>
          </div>
          <div className="records-toolbar">
            <label className="search-field">
              <Search size={16} />
              <input
                placeholder="搜索任务名称或编号"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <button>
              <Filter size={16} />
              任务类型
            </button>
            <button>
              <CalendarDays size={16} />
              最近 30 天
            </button>
            <span>{visibleJobs.length} 个任务</span>
          </div>

          {visibleJobs.length ? (
            <div className={view === "grid" ? "records-grid" : "records-list"}>
              {visibleJobs.map((job) => (
                <article key={job.id} className="record-row">
                  <div className="record-cover">
                    <img src={job.cover} alt="" />
                    <span>{job.type === "局部修改" ? "局部修改" : "详情套图"}</span>
                  </div>
                  <div className="record-main">
                    <div>
                      <StatusBadge status={job.status} />
                      <small>{job.id}</small>
                    </div>
                    <h3>{job.title}</h3>
                    <p>{job.note}</p>
                    {(job.status === "processing" || job.status === "queued") && (
                      <div className="record-progress">
                        <i style={{ width: `${job.progress}%` }} />
                        <span>{job.progress}%</span>
                      </div>
                    )}
                  </div>
                  <div className="record-meta">
                    <span>
                      <Clock3 size={14} />
                      {job.createdAt}
                    </span>
                    <strong>{job.count}</strong>
                    <small>{job.duration}</small>
                  </div>
                  <div className="record-actions">
                    {job.status === "completed" && (
                      <button title="下载结果">
                        <Download size={16} />
                      </button>
                    )}
                    {job.status === "failed" || job.status === "partial" ? (
                      <button title="重试失败项" className="emphasis">
                        <RotateCcw size={16} />
                      </button>
                    ) : null}
                    {job.status === "processing" && (
                      <button title="暂停任务">
                        <PauseCircle size={16} />
                      </button>
                    )}
                    <button title="复制任务">
                      <Copy size={16} />
                    </button>
                    <button title="查看详情" className="row-open">
                      <ArrowUpRight size={16} />
                    </button>
                    <button title="更多操作">
                      <MoreHorizontal size={17} />
                    </button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <Search size={28} />
              <h3>没有找到匹配任务</h3>
              <p>调整关键词或筛选条件后再试一次。</p>
              <button className="secondary-button" onClick={() => { setQuery(""); setTab("all"); }}>
                清除筛选
              </button>
            </div>
          )}
          <div className="pagination">
            <span>第 1–5 项，共 28 项</span>
            <div>
              <button disabled>上一页</button>
              <button className="active">1</button>
              <button>2</button>
              <button>3</button>
              <button>下一页</button>
            </div>
          </div>
        </section>
      </div>
    </AppShell>
  );
}

