"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import type {
  BenchmarkCriteria, BenchmarkExtractionJob, BenchmarkExtractionPick, BenchmarkItem, BenchmarkJob, BenchmarkSort, BenchmarkWindow,
} from "@/features/video-studio/assistance";
import { assistanceMessage } from "@/features/video-studio/assistance";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import styles from "./writing-workflow.module.css";

const number = new Intl.NumberFormat("zh-CN");
const percent = new Intl.NumberFormat("zh-CN", { style: "percent", maximumFractionDigits: 1 });
const timestamp = new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" });

function display(value: number | null, formatter = number) {
  return value === null ? "未提供" : formatter.format(value);
}

function Candidate({ item, onSelect, blocked, singleBusy, checked, onCheck, batch, onResume, onSave, saved }: {
  item: BenchmarkItem; onSelect: () => void; blocked: boolean; singleBusy: boolean; checked: boolean;
  onCheck?: () => void; batch?: BenchmarkExtractionJob;
  onResume: (id: string) => void; onSave?: (id: string) => void; saved: boolean;
}) {
  return <li>
    <a href={item.source_url} target="_blank" rel="noreferrer">{item.author_name || "未提供作者"} · 查看抖音原视频</a>
    <p className={styles.document}>{item.description || "未提供作品描述"}</p>
    <small>作品 ID {item.platform_id} · {item.posted_at ? timestamp.format(new Date(item.posted_at)) : "发布时间未提供"} · {item.duration_seconds === null ? "时长未提供" : item.duration_seconds + " 秒"}</small>
    <small>赞 {display(item.like_count)} · 评论 {display(item.comment_count)} · 收藏 {display(item.collect_count)} · 分享 {display(item.share_count)}</small>
    <small>藏赞比 {display(item.collect_like_ratio, percent)} · 转赞比 {display(item.share_like_ratio, percent)} · {item.media_status === "link_reported" ? "供应商返回播放地址，待核验" : "播放状态未核验"}</small>
    {batch ? <>
      {batch.status === "completed" ? <>
        <details><summary>查看本条提取原文</summary><p className={styles.document}>{batch.result.text}</p></details>
        {saved ? <small>已保存到参考原文</small> : onSave && <button type="button" disabled={blocked} onClick={() => onSave(batch.id)}>保存到参考原文</button>}
      </> : <small>{assistanceMessage(batch)}</small>}
      {batch.can_resume && <button type="button" disabled={blocked} onClick={() => onResume(batch.id)}>继续本条提取任务</button>}
    </> : <>
      {onCheck && <label><input type="checkbox" checked={checked} disabled={blocked} onChange={onCheck} />勾选作品 {item.platform_id}</label>}
      <button type="button" disabled={blocked || singleBusy} onClick={onSelect}>填入提取链接</button>
    </>}
  </li>;
}

export function BenchmarkSearch({ workspaceId, projectId, jobs, extractions, extractBusy, onSearch, onNext, onResume, onUse, onExtract }: {
  workspaceId: string; projectId: string;
  jobs: BenchmarkJob[];
  extractions: BenchmarkExtractionJob[];
  extractBusy: boolean;
  onSearch: (criteria: BenchmarkCriteria) => Promise<void>;
  onNext: (id: string) => Promise<void>;
  onResume: (id: string) => Promise<void>;
  onUse: (item: BenchmarkItem, page: BenchmarkJob) => void;
  onExtract: (items: BenchmarkExtractionPick[]) => Promise<void>;
}) {
  const [config, setConfig] = useState<{ enabled: boolean; can_extract: boolean; can_save_reference: boolean }>();
  const [keyword, setKeyword] = useState("");
  const [sort, setSort] = useState<BenchmarkSort>("relevance");
  const [publishWindow, setPublishWindow] = useState<BenchmarkWindow>("unlimited");
  const [selected, setSelected] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [selection, setSelection] = useState<{ rootId: string; items: BenchmarkExtractionPick[] }>();
  const [savedReferences, setSavedReferences] = useState<string[]>([]);
  const enabled = config?.enabled;
  useEffect(() => {
    const abort = new AbortController();
    void apiClient.GET("/api/v1/video-studio/workspaces/{workspace_id}/benchmark-config", {
      params: { path: { workspace_id: workspaceId } }, signal: abort.signal, cache: "no-store",
    }).then(res => setConfig(unwrapApiResponse(res))).catch(() => {
      if (!abort.signal.aborted) setConfig({ enabled: false, can_extract: false, can_save_reference: false });
    });
    return () => abort.abort();
  }, [workspaceId]);
  useEffect(() => {
    if (!config?.can_save_reference || !projectId) return;
    const abort = new AbortController();
    void apiClient.GET("/api/v1/video-studio/workspaces/{workspace_id}/writing-documents", {
      params: { path: { workspace_id: workspaceId }, query: { project_id: projectId } }, signal: abort.signal, cache: "no-store",
    }).then(response => {
      if (abort.signal.aborted) return;
      const documents = unwrapApiResponse(response) as { kind: string; assistance_task_id?: string | null }[];
      const ids = documents.filter(doc => doc.kind === "reference" && doc.assistance_task_id).map(doc => doc.assistance_task_id!);
      setSavedReferences(previous => [...new Set([...previous, ...ids])]);
    }).catch(() => undefined);
    return () => abort.abort();
  }, [config?.can_save_reference, projectId, workspaceId]);

  const roots = jobs.filter(job => job.result.page === 1);
  const root = roots.find(job => job.id === selected) || roots[0];
  const pages = jobs.filter(job => job.result.root_task_id === root?.id)
    .sort((a, b) => a.result.page - b.result.page);
  const last = pages.at(-1);
  const running = jobs.some(job => job.status === "queued" || job.status === "running");
  const sameSearchUnknown = roots.some(job => job.status === "unknown" &&
    job.result.keyword === keyword.trim() && job.result.sort === sort && job.result.publish_time === publishWindow);
  const expire = last?.result.next_page_expires_at;
  const batchJobs = new Map(extractions.map(job => [job.benchmark_source.platform_id, job]));
  const selectedItems = selection && selection.rootId === root?.id
    ? selection.items.filter(item => !batchJobs.has(item.platform_id))
    : [];
  const collected = new Map(pages.filter(page => page.status === "completed")
    .flatMap(page => (page.result.items || []).map(item => [item.platform_id, item] as const)));
  const authors = new Map<string, number>();
  let missingAuthors = 0;
  for (const item of collected.values()) {
    if (item.author_id) authors.set(item.author_id, (authors.get(item.author_id) || 0) + 1);
    else missingAuthors += 1;
  }

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

  function toggle(item: BenchmarkItem, page: BenchmarkJob) {
    const included = selectedItems.some(pick => pick.platform_id === item.platform_id);
    if (!included && selectedItems.length === 10) {
      setError("一次最多提交 10 条作品。");
      return;
    }
    setError("");
    setSelection({ rootId: page.result.root_task_id, items: included
      ? selectedItems.filter(pick => pick.platform_id !== item.platform_id)
      : [...selectedItems, { search_task_id: page.id, platform_id: item.platform_id }],
    });
  }

  const saveReference = (taskId: string) => void run(async () => {
    unwrapApiResponse(await apiClient.POST("/api/v1/video-studio/workspaces/{workspace_id}/writing-documents/reference/from-benchmark/{task_id}", {
      params: { path: { workspace_id: workspaceId, task_id: taskId } }, signal: AbortSignal.timeout(12000),
    }));
    setSavedReferences(previous => [...previous, taskId]);
  });

  return <section aria-label="按方向找抖音对标" className={styles.workflow}>
    <strong>按方向找抖音对标</strong>
    <p>按关键词查找作品。结果展示发布描述和公开互动，选中链接后可另行提取语音原文。</p>
    {enabled === undefined ? <p role="status">正在检查搜索服务…</p> : enabled ? <form onSubmit={search}>
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
    {collected.size > 0 && <small aria-label="已加载样本统计">已加载 {collected.size} 条不同作品 · {authors.size} 位可识别作者 · {missingAuthors} 条作者标识缺失 · 同一作者最多 {Math.max(0, ...authors.values())} 条</small>}
    {!!selectedItems.length && <div className={styles.result}>
      <small>逐条提交语音提取，供应商按条计费。每批最多 10 条。</small>
      <button type="button" disabled={pending || !config?.can_extract} onClick={() => void run(async () => {
        await onExtract(selectedItems);
        setSelection(undefined);
      })}>提交 {selectedItems.length} 条提取（付费）</button>
    </div>}
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
          <Candidate key={item.platform_id} item={item} blocked={pending} singleBusy={extractBusy} onSelect={() => onUse(item, page)}
            batch={batchJobs.get(item.platform_id)} checked={selectedItems.some(pick => pick.platform_id === item.platform_id)}
            onCheck={config?.can_extract ? () => toggle(item, page) : undefined} onResume={id => void run(() => onResume(id))}
            onSave={config?.can_save_reference ? saveReference : undefined}
            saved={savedReferences.includes(batchJobs.get(item.platform_id)?.id || "")} />,
        )}</ol> : <p>这页没有符合条件的候选。</p>}
      </>}
    </section>)}
    {enabled && last?.result.has_more && <button type="button" disabled={pending || running} onClick={() => void run(() => onNext(last.id))}>加载下一页（付费）</button>}
    {last?.result.has_more && expire && <small>下一页有效至 {timestamp.format(new Date(expire))}</small>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
  </section>;
}
