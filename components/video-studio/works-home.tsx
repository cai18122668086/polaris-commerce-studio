"use client";

import Link from "next/link";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Clapperboard, Download, FileSpreadsheet, LoaderCircle, Search } from "lucide-react";
import { ApiError } from "@/lib/api/api-error";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import { mediaUrl } from "@/lib/api/base-url";
import { finishHref, stepHref } from "@/features/video-studio/flow-params";
import { batchOptions, filterPublished, filterWorkCards, mergeWorkCards, posterPath, shortDate, splitWorkCards, unfinishedState, workCounts, type PublishFilter, type TalkJobLike, type WorkCard, type WorkRange } from "@/features/video-studio/works";
import { coverImageUrl, resolveWorkVideo, useBatchItems, useWorkItemActions, useWorkItemPages, useWorkSummary } from "@/features/video-studio/use-finishing";
import { csvFileName, exportRows, toCsv } from "@/features/video-studio/publish-export";
import { ActiveEditingWorks } from "./editing-works";
import { GuidedEmpty } from "./page-hero";
import { PhonePreview } from "./phone-preview";
import { ConfirmDelete } from "./confirm-delete";
import styles from "./finish-works.module.css";

type Notify = (text: string, tone?: "success" | "error" | "info") => void;
const worksRoute = "/api/v1/video-studio/workspaces/{workspace_id}/editing-works" as const;
const RANGES: { key: WorkRange; label: string }[] = [{ key: "all", label: "全部" }, { key: "7d", label: "近 7 天" }, { key: "30d", label: "近 30 天" }];
const PUBLISH: { key: PublishFilter; label: string }[] = [{ key: "all", label: "全部" }, { key: "unpublished", label: "未发布" }, { key: "published", label: "已发布" }];

function useWorkspaceName(workspaceId: string) {
  return useQuery({
    queryKey: ["workspaces", "names"],
    staleTime: 300000,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET("/api/v1/workspaces", { signal })) as { id: string; name?: string }[],
    select: list => list.find(entry => entry.id === workspaceId)?.name ?? "",
  });
}

const errorText = (error: unknown, fallback: string) => error instanceof ApiError && error.message ? error.message
  : error instanceof DOMException && (error.name === "TimeoutError" || error.name === "AbortError") ? "网络较慢，暂时没收到结果，已重新读取作品状态。" : fallback;

export function WorksHome({ userId, workspaceId, jobs, initialBatch, notify }: {
  userId: string;
  workspaceId: string;
  jobs: TalkJobLike[];
  initialBatch: string | null;
  notify: Notify;
}) {
  const summary = useWorkSummary(workspaceId);
  const items = useWorkItemPages(workspaceId, (summary.data?.active ?? 0) > 0);
  const edits = useInfiniteQuery({
    queryKey: ["video-studio", "editing-works", userId, workspaceId, ""],
    initialPageParam: undefined as string | undefined,
    staleTime: 0,
    queryFn: async ({ pageParam, signal }) => unwrapApiResponse(await apiClient.GET(worksRoute, {
      params: { path: { workspace_id: workspaceId }, query: { keyword: "", before: pageParam } },
      signal: AbortSignal.any([signal, AbortSignal.timeout(12000)]),
    })),
    getNextPageParam: page => page.next_before ?? undefined,
  });
  const actions = useWorkItemActions(workspaceId);
  const name = useWorkspaceName(workspaceId);
  const [range, setRange] = useState<WorkRange>("all");
  const [published, setPublished] = useState<PublishFilter>("all");
  const [batch, setBatch] = useState<string>(initialBatch ?? "");
  const [keyword, setKeyword] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const itemList = useMemo(() => items.data?.pages.flat() ?? [], [items.data]);
  const cards = useMemo(() => mergeWorkCards(itemList, edits.data?.pages.flatMap(page => page.items) ?? [], jobs, { itemsComplete: !items.hasNextPage }), [itemList, edits.data, jobs, items.hasNextPage]);
  const filtered = useMemo(() => filterWorkCards(cards, { batch: batch || null, range, keyword }), [cards, batch, range, keyword]);
  const split = useMemo(() => splitWorkCards(filtered), [filtered]);
  const grid = useMemo(() => filterPublished(split.grid, published), [split.grid, published]);
  const batches = useMemo(() => batchOptions(cards), [cards]);
  const counts = workCounts(summary.data, cards);
  const loading = items.isPending && edits.isPending;
  const opened = grid.find(card => card.key === open) ?? null;
  const hasMore = Boolean(items.hasNextPage || edits.hasNextPage);
  const fetchingMore = items.isFetchingNextPage || edits.isFetchingNextPage;
  const more = () => { if (items.hasNextPage) void items.fetchNextPage(); else if (edits.hasNextPage) void edits.fetchNextPage(); };

  // B2：滚到底自动加载更早的作品（作品条目翻完再翻旧的剪辑成片）。
  const sentinel = useRef<HTMLDivElement>(null);
  const moreRef = useRef(more);
  useEffect(() => { moreRef.current = more; });
  useEffect(() => {
    const node = sentinel.current;
    if (!node || !hasMore || fetchingMore || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting)) moreRef.current(); }, { rootMargin: "600px 0px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasMore, fetchingMore, cards.length]);

  const remove = async (card: WorkCard) => {
    if (!card.itemId) return false;
    try {
      await actions.remove.mutateAsync(card.itemId);
      notify("已从我的作品中移除（视频文件仍保留）", "success");
      return true;
    } catch (error) { notify(errorText(error, "没有删除成功，请稍后再试。"), "error"); return false; }
  };
  const togglePublished = async (card: WorkCard) => {
    if (!card.itemId || card.version === null) return;
    try {
      await actions.publish.mutateAsync({ itemId: card.itemId, version: card.version, published: !card.publishedAt });
      notify(card.publishedAt ? "已取消「已发布」标记" : "已标记为已发布", "success");
    } catch (error) { notify(errorText(error, "标记没有成功，请刷新后再试。"), "error"); }
  };
  const retry = async (card: WorkCard, stage: "talking" | "editing") => {
    if (!card.itemId) return;
    try { await actions.retry.mutateAsync({ itemId: card.itemId, stage }); notify(stage === "talking" ? "已重新提交口播" : "已重新提交剪辑", "success"); }
    catch (error) { notify(errorText(error, "重试没有提交成功，可以回到这一步再试。"), "error"); }
  };
  const batchLabel = batches.find(entry => entry.id === batch)?.label ?? "";

  return <section className={styles.works} aria-label="我的作品">
    <header className={styles.profile}>
      <span className={styles.avatar} aria-hidden="true">{(name.data || "极").slice(0, 1)}</span>
      <div className={styles.profileText}>
        <h1>{name.data || "我的工作区"}</h1>
        <p>剪好、配好封面的视频都在这里，点开看手机上的效果，复制文案直接去发布。</p>
      </div>
      <dl className={styles.profileFacts} aria-label="作品计数">
        <div><dd>{counts.works}{edits.hasNextPage ? "+" : ""}</dd><dt>作品</dt></div>
        <div><dd>{counts.finishing}</dd><dt>待成片</dt></div>
        <div><dd>{counts.running}</dd><dt>生成中</dt></div>
        <div><dd>{counts.unfinished}</dd><dt>未完成</dt></div>
      </dl>
    </header>

    <div className={styles.filters}>
      <div className={styles.segment} role="radiogroup" aria-label="时间">
        {RANGES.map(entry => <button key={entry.key} type="button" role="radio" aria-checked={range === entry.key} onClick={() => setRange(entry.key)}>{entry.label}</button>)}
      </div>
      <div className={styles.segment} role="radiogroup" aria-label="发布状态">
        {PUBLISH.map(entry => <button key={entry.key} type="button" role="radio" aria-checked={published === entry.key} onClick={() => setPublished(entry.key)}>{entry.label}</button>)}
      </div>
      {batches.length > 0 && <label className={styles.select}>
        <span className={styles.srOnly}>批次</span>
        <select value={batch} onChange={event => setBatch(event.target.value)} aria-label="按批次筛选">
          <option value="">全部批次</option>
          {batches.map(entry => <option key={entry.id} value={entry.id}>{entry.label}</option>)}
        </select>
      </label>}
      <label className={styles.searchBox}><Search size={15} /><input aria-label="搜索作品" placeholder="搜索标题或文案" value={keyword} onChange={event => setKeyword(event.target.value)} /></label>
    </div>

    {batch && <ExportBar workspaceId={workspaceId} batchId={batch} batchLabel={batchLabel} notify={notify} />}

    {loading && <p className={styles.loading} role="status">正在读取作品…</p>}
    {(items.isError || edits.isError) && <p role="alert" className={styles.alert}>部分作品暂时读不到。<button type="button" className={styles.linkButton} onClick={() => { void items.refetch(); void edits.refetch(); }}>重试</button></p>}
    {!loading && !cards.length && <GuidedEmpty title="还没有作品" description="从文案开始，口播、剪辑、成片一路做下来，作品会像主页一样一格一格排在这里。" steps={["写文案或从文案库多选几条", "生成口播并批量剪辑", "成片配封面，保存到我的作品"]} action={<Link className={styles.primary} href="/video-studio/writing">从文案开始</Link>} motif="works" />}
    {!loading && cards.length > 0 && !grid.length && !split.running.length && !split.unfinished.length && <p className={styles.emptyLine}>没有符合条件的作品，换个筛选试试。</p>}

    {grid.length > 0 && <ul className={styles.grid} aria-label="作品">
      {grid.map(card => <li key={card.key}><WorkTile workspaceId={workspaceId} card={card} onOpen={() => setOpen(card.key)} onDelete={() => remove(card)} /></li>)}
    </ul>}
    {!loading && cards.length > 0 && !grid.length && (split.running.length > 0 || split.unfinished.length > 0) && <p className={styles.emptyLine}>还没有剪好的作品，进行中的在下面。</p>}

    {(split.running.length > 0 || split.unfinished.length > 0) && <section className={styles.unfinished} aria-label="未完成">
      <h2>未完成 <small>{split.running.length ? `${split.running.length} 条生成中` : ""}{split.running.length && split.unfinished.length ? " · " : ""}{split.unfinished.length ? `${split.unfinished.length} 条待处理` : ""}</small></h2>
      <ul>{[...split.running, ...split.unfinished].map(card => <UnfinishedRow key={card.key} card={card} retrying={actions.retry.isPending && actions.retry.variables?.itemId === card.itemId} onRetry={stage => void retry(card, stage)} onDelete={() => remove(card)} />)}</ul>
    </section>}

    <div className={styles.activeBelow}><ActiveEditingWorks userId={userId} workspaceId={workspaceId} keyword="" /></div>
    <div ref={sentinel} aria-hidden="true" />
    {hasMore && <button type="button" className={styles.more} disabled={fetchingMore} onClick={more}>{fetchingMore ? "正在加载…" : "加载更早的作品"}</button>}

    {opened && <PhonePreview workspaceId={workspaceId} cards={grid.filter(card => card.finished)} current={opened} accountName={name.data || "我的工作区"} onMove={key => setOpen(key)} onClose={() => setOpen(null)} notify={notify}
      onDelete={opened.itemId ? async () => { if (await remove(opened)) setOpen(null); } : undefined}
      onTogglePublished={opened.itemId ? () => void togglePublished(opened) : undefined} publishing={actions.publish.isPending} />}
  </section>;
}

function WorkTile({ workspaceId, card, onOpen, onDelete }: { workspaceId: string; card: WorkCard; onOpen: () => void; onDelete: () => Promise<boolean> }) {
  const [broken, setBroken] = useState(false);
  const source = card.coverId ? coverImageUrl(workspaceId, card.coverId, "thumb") : posterPath(workspaceId, card);
  const placeholder = <div className={styles.tileBlank} aria-hidden="true"><Clapperboard size={22} /><span>{card.progress?.label ?? "暂无封面"}</span></div>;
  const media = source && !broken
    ? <img src={mediaUrl(source)} alt="" loading="lazy" decoding="async" onError={() => setBroken(true)} />
    : placeholder;
  const body = <>
    <div className={styles.tileMedia}>
      {media}
      {card.progress && <span className={`${styles.badge} ${styles[`badge_${card.progress.tone}`]}`}>{card.progress.label}</span>}
    </div>
    <b className={styles.tileTitle}>{card.title}</b>
  </>;
  const main = card.finished
    ? <button type="button" className={styles.tile} onClick={onOpen} aria-label={`预览：${card.title}`}>{body}</button>
    : card.itemId ? <Link className={styles.tile} href={finishHref({ item: card.itemId })} aria-label={`去成片：${card.title}`}>{body}</Link>
      : <div className={`${styles.tile} ${styles.tileStatic}`}>{body}</div>;
  return <>
    {main}
    <div className={styles.tileMeta}>
      <time className={styles.tileTime} dateTime={card.createdAt}>{shortDate(card.createdAt)}</time>
      {card.publishedAt && <span className={styles.tilePublished}><Check size={12} />已发布</span>}
      {card.itemId && <ConfirmDelete onConfirm={onDelete} />}
    </div>
  </>;
}

function UnfinishedRow({ card, retrying, onRetry, onDelete }: { card: WorkCard; retrying: boolean; onRetry: (stage: "talking" | "editing") => void; onDelete: () => Promise<boolean> }) {
  const state = unfinishedState(card);
  return <li>
    <span className={styles.unfinishedTitle}>{card.title}</span>
    <span className={`${styles.unfinishedState} ${card.group === "failed" ? styles.unfinishedFailed : ""}`}>{card.group === "active" && <LoaderCircle className={styles.spin} size={13} />}{state.label}</span>
    <time className={styles.tileTime} dateTime={card.createdAt}>{shortDate(card.createdAt)}</time>
    <span className={styles.unfinishedActions}>
      {state.retry && <button type="button" className={styles.textAction} disabled={retrying} onClick={() => onRetry(state.retry!)}>{retrying ? "正在提交…" : "重试"}</button>}
      {card.batchId && <Link className={styles.textAction} href={stepHref(state.step, { batch: card.batchId })}>回到这一步</Link>}
      {card.itemId && state.deletable && <ConfirmDelete onConfirm={onDelete} />}
    </span>
  </li>;
}

/** 浏览器里存一个文件（中文文件名）。 */
function saveBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = fileName; link.rel = "noopener";
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

/** B13 小版本：选了批次后出现。总表 CSV + 逐个下载视频与封面；只含已完成的条目，文案原样取自成片页保存的内容。 */
function ExportBar({ workspaceId, batchId, batchLabel, notify }: { workspaceId: string; batchId: string; batchLabel: string; notify: Notify }) {
  const items = useBatchItems(workspaceId, batchId);
  const list = useMemo(() => (items.data ?? []).filter(item => !item.deleted_at), [items.data]);
  const rows = useMemo(() => exportRows(list.map(item => ({ ...item, publish_title: item.publish_title ?? "", publish_body: item.publish_body ?? "" }))), [list]);
  const [progress, setProgress] = useState<string | null>(null);
  const label = batchLabel.split(" · ")[0] || "这一批";

  const exportCsv = () => {
    saveBlob(new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" }), csvFileName(label, rows.length));
    notify(`已导出 ${rows.length} 条的发布清单`, "success");
  };
  const downloadAll = async () => {
    const byId = new Map(list.map(item => [item.id, item]));
    const files = rows.reduce((sum, row) => sum + 1 + (row.coverId ? 1 : 0), 0);
    let done = 0;
    try {
      for (const row of rows) {
        const item = byId.get(row.itemId);
        if (!item) continue;
        setProgress(`正在下载 ${done + 1}/${files}`);
        const video = await resolveWorkVideo(workspaceId, item);
        if (video) {
          const response = await fetch(mediaUrl(video)!, { credentials: "include" });
          if (!response.ok) throw new Error(`「${row.title}」的视频没有下载成功`);
          saveBlob(await response.blob(), row.video);
        }
        done += 1;
        if (row.coverId) {
          setProgress(`正在下载 ${done + 1}/${files}`);
          const response = await fetch(mediaUrl(coverImageUrl(workspaceId, row.coverId, "cover", true))!, { credentials: "include" });
          if (!response.ok) throw new Error(`「${row.title}」的封面没有下载成功`);
          saveBlob(await response.blob(), row.cover);
          done += 1;
        }
      }
      notify(`已下载 ${done} 个文件`, "success");
    } catch (error) {
      notify(`${error instanceof Error ? error.message : "下载中断"}，已下载 ${done} 个，可以再点一次`, "error");
    } finally { setProgress(null); }
  };

  return <div className={styles.exportBar} role="region" aria-label="导出这一批">
    <span className={styles.exportNote}>
      <b>导出这一批</b>
      {items.isPending ? "正在读取…" : rows.length ? `已完成 ${rows.length} 条${list.length > rows.length ? `，另有 ${list.length - rows.length} 条还没成片，不导出` : ""}` : "这一批还没有已完成的作品"}
    </span>
    <button type="button" className={styles.secondary} disabled={!rows.length} onClick={exportCsv}><FileSpreadsheet size={15} />发布清单（表格）</button>
    <button type="button" className={styles.secondary} disabled={!rows.length || Boolean(progress)} onClick={() => void downloadAll()}>{progress ? <><LoaderCircle className={styles.spin} size={15} />{progress}</> : <><Download size={15} />全部下载（视频 + 封面）</>}</button>
  </div>;
}
