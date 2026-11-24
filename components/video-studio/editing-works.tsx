"use client";

import Link from "next/link";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import { activeWorkView, matchesKeyword } from "@/features/video-studio/active-works";
import styles from "./video-studio.module.css";
import { GuidedEmpty } from "./page-hero";

const route = "/api/v1/video-studio/workspaces/{workspace_id}/editing-works" as const;
const activeRoute = "/api/v1/video-studio/workspaces/{workspace_id}/editing-works/active" as const;

function ActiveEditingWorks({ userId, workspaceId, keyword }: { userId: string; workspaceId: string; keyword: string }) {
  const active = useQuery({
    queryKey: ["video-studio", "editing-works-active", userId, workspaceId],
    staleTime: 0,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET(activeRoute, {
      params: { path: { workspace_id: workspaceId } },
      signal: AbortSignal.any([signal, AbortSignal.timeout(12000)]),
    })),
    refetchInterval: query => query.state.data?.items.some(item => activeWorkView(item).polling) ? 15000 : false,
  });
  const items = (active.data?.items ?? []).filter(item => matchesKeyword(item, keyword));
  if (active.isPending || (active.isSuccess && !items.length)) return null;

  return <section className={styles.editingWorks} aria-label="进行中的剪辑">
    <div className={styles.sectionHeading}><h2>进行中</h2></div>
    {active.isError && <p role="alert">
      暂时无法读取进行中的剪辑。 <button type="button" className={styles.textButton} onClick={() => void active.refetch()}>重试</button>
    </p>}
    {!!items.length && <div className={styles.worksGrid}>{items.map(work => {
      const view = activeWorkView(work);
      return <article key={`${work.kind}:${work.task_id}`} className={styles.workCard}>
        {work.preview && <video controls playsInline preload="none" className={styles.editingWorkVideo} src={work.preview.url} aria-label={`待确认预览 · ${work.project_title}`} />}
        <div>
          <b>{work.project_title}</b>
          <time dateTime={work.created_at}>{new Date(work.created_at).toLocaleString("zh-CN")}</time>
          <p role="status">{view.label}</p>
          <div className={styles.workActions}>
            <Link className={styles.textButton} scroll={false} href={view.href}>{view.action}</Link>
          </div>
        </div>
      </article>;
    })}</div>}
  </section>;
}

export function EditingWorks({ userId, workspaceId, keyword }: { userId: string; workspaceId: string; keyword: string }) {
  const term = keyword.trim().slice(0, 120);
  const works = useInfiniteQuery({
    queryKey: ["video-studio", "editing-works", userId, workspaceId, term],
    initialPageParam: undefined as string | undefined,
    staleTime: 0,
    queryFn: async ({ pageParam, signal }) => unwrapApiResponse(await apiClient.GET(route, {
      params: {
        path: { workspace_id: workspaceId },
        query: { keyword: term, before: pageParam },
      },
      signal: AbortSignal.any([signal, AbortSignal.timeout(12000)]),
    })),
    getNextPageParam: page => page.next_before ?? undefined,
  });
  const items = works.data?.pages.flatMap(page => page.items) ?? [];

  return <>
    <ActiveEditingWorks userId={userId} workspaceId={workspaceId} keyword={term} />
    <section className={styles.editingWorks} aria-label="剪辑成片">
      <div className={styles.sectionHeading}><h2>剪辑成片</h2></div>
      {works.isPending && <p role="status">正在读取剪辑成片…</p>}
      {works.isError && <p role="alert">
        暂时无法读取剪辑成片。 <button type="button" className={styles.textButton} onClick={() => void (works.isFetchNextPageError ? works.fetchNextPage() : works.refetch())}>重试</button>
      </p>}
      {works.isSuccess && !items.length && (term ? <p>没有找到匹配的剪辑成片。</p> : <GuidedEmpty title="还没有剪辑成片" description="把口播送进智能剪辑，确认预览后，高清成片会出现在这里，可以直接播放和下载。" steps={["在「智能剪辑」选一条口播或上传视频", "挑一个模板，开始智能剪辑", "预览满意后确认，获取高清成片"]} action={<Link className={styles.primaryButton} href="/video-studio/editing">去智能剪辑</Link>} motif="works" />)}
      {!!items.length && <div className={styles.worksGrid}>{items.map(work => <article key={work.task_id} className={styles.workCard}>
        <video controls playsInline preload="none" className={styles.editingWorkVideo} src={work.final.url} aria-label={`剪辑成片 · ${work.project_title}`} />
        <div>
          <b>{work.project_title}</b>
          <time dateTime={work.created_at}>{new Date(work.created_at).toLocaleString("zh-CN")}</time>
          <p>智能剪辑{work.final.duration_ms != null && ` · ${(work.final.duration_ms / 1000).toFixed(1)} 秒`}</p>
          <div className={styles.workActions}>
            <a className={styles.textButton} href={work.final.url} download>下载成片</a>
            <Link className={styles.textButton} scroll={false} href={`/video-studio/editing?project=${encodeURIComponent(work.project_id)}#editing-task-${encodeURIComponent(work.task_id)}`}>查看本条剪辑</Link>
          </div>
        </div>
      </article>)}</div>}
      {works.hasNextPage && !works.isFetchNextPageError && <button type="button" className={styles.textButton} disabled={works.isFetchingNextPage} onClick={() => void works.fetchNextPage()}>
        {works.isFetchingNextPage ? "正在加载…" : "加载更多剪辑成片"}
      </button>}
    </section>
  </>;
}
