"use client";

import Link from "next/link";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Clapperboard, Search } from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import { mediaUrl } from "@/lib/api/base-url";
import { finishHref } from "@/features/video-studio/flow-params";
import { batchOptions, filterWorkCards, mergeWorkCards, posterPath, shortDate, type TalkJobLike, type WorkCard, type WorkRange } from "@/features/video-studio/works";
import { coverImageUrl, useAllWorkItems } from "@/features/video-studio/use-finishing";
import { ActiveEditingWorks } from "./editing-works";
import { GuidedEmpty } from "./page-hero";
import { PhonePreview } from "./phone-preview";
import styles from "./finish-works.module.css";

const worksRoute = "/api/v1/video-studio/workspaces/{workspace_id}/editing-works" as const;
const RANGES: { key: WorkRange; label: string }[] = [{ key: "all", label: "全部" }, { key: "7d", label: "近 7 天" }, { key: "30d", label: "近 30 天" }];

function useWorkspaceName(workspaceId: string) {
  return useQuery({
    queryKey: ["workspaces", "names"],
    staleTime: 300000,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET("/api/v1/workspaces", { signal })) as { id: string; name?: string }[],
    select: list => list.find(entry => entry.id === workspaceId)?.name ?? "",
  });
}

export function WorksHome({ userId, workspaceId, jobs, initialBatch, notify }: {
  userId: string;
  workspaceId: string;
  jobs: TalkJobLike[];
  initialBatch: string | null;
  notify: (text: string, tone?: "success" | "error" | "info") => void;
}) {
  const items = useAllWorkItems(workspaceId);
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
  const name = useWorkspaceName(workspaceId);
  const [range, setRange] = useState<WorkRange>("all");
  const [batch, setBatch] = useState<string>(initialBatch ?? "");
  const [keyword, setKeyword] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const cards = useMemo(() => mergeWorkCards(items.data ?? [], edits.data?.pages.flatMap(page => page.items) ?? [], jobs), [items.data, edits.data, jobs]);
  const shown = useMemo(() => filterWorkCards(cards, { batch: batch || null, range, keyword }), [cards, batch, range, keyword]);
  const batches = useMemo(() => batchOptions(cards), [cards]);
  const finished = cards.filter(card => card.finished).length;
  const running = cards.length - finished;
  const loading = items.isPending && edits.isPending;
  const opened = shown.find(card => card.key === open) ?? null;

  return <section className={styles.works} aria-label="我的作品">
    <header className={styles.profile}>
      <span className={styles.avatar} aria-hidden="true">{(name.data || "极").slice(0, 1)}</span>
      <div className={styles.profileText}>
        <h1>{name.data || "我的工作区"}</h1>
        <p>剪好、配好封面的视频都在这里，点开看手机上的效果，复制文案直接去发布。</p>
      </div>
      <dl className={styles.profileFacts}>
        <div><dd>{cards.length}</dd><dt>作品</dt></div>
        <div><dd>{finished}</dd><dt>已完成</dt></div>
        <div><dd>{running}</dd><dt>进行中</dt></div>
      </dl>
    </header>

    <div className={styles.filters}>
      <div className={styles.segment} role="radiogroup" aria-label="时间">
        {RANGES.map(entry => <button key={entry.key} type="button" role="radio" aria-checked={range === entry.key} onClick={() => setRange(entry.key)}>{entry.label}</button>)}
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

    {loading && <p className={styles.loading} role="status">正在读取作品…</p>}
    {(items.isError || edits.isError) && <p role="alert" className={styles.alert}>部分作品暂时读不到。<button type="button" className={styles.linkButton} onClick={() => { void items.refetch(); void edits.refetch(); }}>重试</button></p>}
    {!loading && !cards.length && <GuidedEmpty title="还没有作品" description="从文案开始，口播、剪辑、成片一路做下来，作品会像主页一样一格一格排在这里。" steps={["写文案或从文案库多选几条", "生成口播并批量剪辑", "成片配封面，保存到我的作品"]} action={<Link className={styles.primary} href="/video-studio/writing">从文案开始</Link>} motif="works" />}
    {!loading && cards.length > 0 && !shown.length && <p className={styles.emptyLine}>没有符合条件的作品，换个筛选试试。</p>}

    {shown.length > 0 && <ul className={styles.grid}>
      {shown.map(card => <li key={card.key}><WorkTile workspaceId={workspaceId} card={card} onOpen={() => setOpen(card.key)} /></li>)}
    </ul>}
    <div className={styles.activeBelow}><ActiveEditingWorks userId={userId} workspaceId={workspaceId} keyword="" /></div>
    {edits.hasNextPage && <button type="button" className={styles.more} disabled={edits.isFetchingNextPage} onClick={() => void edits.fetchNextPage()}>{edits.isFetchingNextPage ? "正在加载…" : "加载更早的作品"}</button>}

    {opened && <PhonePreview workspaceId={workspaceId} cards={shown.filter(card => card.finished)} current={opened} accountName={name.data || "我的工作区"} onMove={key => setOpen(key)} onClose={() => setOpen(null)} notify={notify} />}
  </section>;
}

function WorkTile({ workspaceId, card, onOpen }: { workspaceId: string; card: WorkCard; onOpen: () => void }) {
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
    <time className={styles.tileTime} dateTime={card.createdAt}>{shortDate(card.createdAt)}</time>
  </>;
  if (card.finished) return <button type="button" className={styles.tile} onClick={onOpen} aria-label={`预览：${card.title}`}>{body}</button>;
  if (card.itemId && card.progress?.label === "待成片") return <Link className={styles.tile} href={finishHref({ item: card.itemId })} aria-label={`去成片：${card.title}`}>{body}</Link>;
  return <div className={`${styles.tile} ${styles.tileStatic}`} aria-label={`${card.progress?.label ?? ""}：${card.title}`}>{body}</div>;
}
