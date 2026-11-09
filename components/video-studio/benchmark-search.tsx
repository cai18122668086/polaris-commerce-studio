"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import type {
  BenchmarkCriteria, BenchmarkItem, BenchmarkJob, BenchmarkSort, BenchmarkWindow,
} from "@/features/video-studio/assistance";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import styles from "./writing-workflow.module.css";

const number = new Intl.NumberFormat("zh-CN");
const percent = new Intl.NumberFormat("zh-CN", { style: "percent", maximumFractionDigits: 1 });
const timestamp = new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" });

function display(value: number | null, formatter = number) {
  return value === null ? "未提供" : formatter.format(value);
}

function Candidate({ item, onSelect, blocked }: {
  item: BenchmarkItem; onSelect: () => void; blocked: boolean;
}) {
  return <li>
    <a href={item.source_url} target="_blank" rel="noreferrer">{item.author_name || "未提供作者"} · 查看抖音原视频</a>
    <p className={styles.document}>{item.description || "未提供作品描述"}</p>
    <small>作品 ID {item.platform_id} · {item.posted_at ? timestamp.format(new Date(item.posted_at)) : "发布时间未提供"} · {item.duration_seconds === null ? "时长未提供" : item.duration_seconds + " 秒"}</small>
    <small>赞 {display(item.like_count)} · 评论 {display(item.comment_count)} · 收藏 {display(item.collect_count)} · 分享 {display(item.share_count)}</small>
    <small>藏赞比 {display(item.collect_like_ratio, percent)} · 转赞比 {display(item.share_like_ratio, percent)} · {item.media_status === "link_reported" ? "供应商返回播放地址，待核验" : "播放状态未核验"}</small>
    <button type="button" disabled={blocked} onClick={onSelect}>填入提取链接</button>
  </li>;
}

export function BenchmarkSearch({ workspaceId, jobs, extractBusy, onSearch, onNext, onResume, onUse }: {
  workspaceId: string;
  jobs: BenchmarkJob[];
  extractBusy: boolean;
  onSearch: (criteria: BenchmarkCriteria) => Promise<void>;
  onNext: (id: string) => Promise<void>;
  onResume: (id: string) => Promise<void>;
  onUse: (item: BenchmarkItem, page: BenchmarkJob) => void;
}) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [keyword, setKeyword] = useState("");
  const [sort, setSort] = useState<BenchmarkSort>("relevance");
  const [publishWindow, setPublishWindow] = useState<BenchmarkWindow>("unlimited");
  const [selected, setSelected] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    void apiClient.GET("/api/v1/video-studio/workspaces/{workspace_id}/benchmark-config", {
      params: { path: { workspace_id: workspaceId } }, signal: abort.signal, cache: "no-store",
    }).then(res => setEnabled(unwrapApiResponse(res).enabled)).catch(() => {
      if (!abort.signal.aborted) setEnabled(false);
    });
    return () => abort.abort();
  }, [workspaceId]);

  const roots = jobs.filter(job => job.result.page === 1);
  const root = roots.find(job => job.id === selected) || roots[0];
  const pages = jobs.filter(job => job.result.root_task_id === root?.id)
    .sort((a, b) => a.result.page - b.result.page);
  const last = pages.at(-1);
  const running = jobs.some(job => job.status === "queued" || job.status === "running");
  const sameSearchUnknown = roots.some(job => job.status === "unknown" &&
    job.result.keyword === keyword.trim() && job.result.sort === sort && job.result.publish_time === publishWindow);
  const expire = last?.result.next_page_expires_at;

  async function run(operation: () => Promise<void>) {
    setPending(true);
    setError("");
    try {
      await operation();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "对标任务暂未完成。");
    } finally {
      setPending(false);
    }
  }

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!enabled || pending || running || sameSearchUnknown || !keyword.trim()) return;
    void run(async () => {
      await onSearch({ keyword: keyword.trim(), sort, publish_time: publishWindow });
      setSelected("");
    });
  }

  return <section aria-label="按方向找抖音对标" className={styles.workflow}>
    <strong>按方向找抖音对标</strong>
    <p>按关键词查找作品。结果展示发布描述和公开互动，选中链接后可另行提取语音原文。</p>
    {enabled === null ? <p role="status">正在检查搜索服务…</p> : enabled ? <form onSubmit={search}>
      <label>内容方向或关键词<input value={keyword} onChange={event => setKeyword(event.target.value)} maxLength={120} required /></label>
      <label>排序<select aria-label="排序" value={sort} onChange={event => setSort(event.target.value as BenchmarkSort)}>
        <option value="relevance">相关度</option><option value="newest">最新发布</option><option value="most_liked">点赞最多</option>
      </select></label>
      <label>发布时间<select aria-label="发布时间" value={publishWindow} onChange={event => setPublishWindow(event.target.value as BenchmarkWindow)}>
        <option value="unlimited">不限</option><option value="one_day">最近 24 小时</option>
        <option value="one_week">最近 7 天</option><option value="half_year">最近半年</option>
      </select></label>
      <small>每页单独提交一次供应商付费请求。</small>
      <button type="submit" disabled={pending || running || sameSearchUnknown || !keyword.trim()}>搜索对标（付费）</button>
      {sameSearchUnknown && <p role="alert">同条件的搜索回执待核对，请保留原任务。</p>}
    </form> : <p>对标搜索服务暂未启用，仍可使用公开抖音链接提取原文。</p>}
    {roots.length > 0 && <label>已提交的搜索<select aria-label="已提交的搜索" value={root?.id || ""} onChange={event => setSelected(event.target.value)}>
      {roots.map(job => <option key={job.id} value={job.id}>{job.result.keyword} · {job.result.captured_at ? timestamp.format(new Date(job.result.captured_at)) : "待完成"}</option>)}
    </select></label>}
    {pages.map(page => <section className={styles.result} key={page.id} aria-label={"搜索结果第 " + page.result.page + " 页"}>
      <strong>第 {page.result.page} 页</strong>
      {["queued", "running"].includes(page.status) && <p role="status">正在查询公开作品…</p>}
      {page.status === "unknown" && <p role="alert">搜索回执待核对，请保留原任务。</p>}
      {page.status === "failed" && <p role="alert">搜索未完成，请核对服务状态。</p>}
      {page.can_resume && <button type="button" disabled={!enabled || pending} onClick={() => void run(() => onResume(page.id))}>继续原搜索任务</button>}
      {page.status === "completed" && <>
        <small>收到 {page.result.received_count} 条 · 重复 {page.result.duplicate_count} 条 · 跳过 {page.result.skipped_count} 条 · {page.result.author_count} 位可识别作者 · {page.result.unknown_author_count} 条作者标识缺失</small>
        {Boolean(page.result.author_count) && page.result.top_author_item_count !== undefined && <small>同一作者最多 {page.result.top_author_item_count} 条，本页有 {(page.result.items?.length ?? 0) - (page.result.unknown_author_count ?? 0)} 条作品的作者标识已知。</small>}
        <small>此页为候选样本。藏赞比为收藏数除以点赞数，转赞比为分享数除以点赞数。</small>
        {page.result.items?.length ? <ol>{page.result.items.map(item =>
          <Candidate key={item.platform_id} item={item} blocked={extractBusy} onSelect={() => onUse(item, page)} />,
        )}</ol> : <p>这页没有符合条件的候选。</p>}
      </>}
    </section>)}
    {enabled && last?.result.has_more && <button type="button" disabled={pending || running} onClick={() => void run(() => onNext(last.id))}>加载下一页（付费）</button>}
    {last?.result.has_more && expire && <small>下一页有效至 {timestamp.format(new Date(expire))}</small>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
  </section>;
}
