"use client";

import Link from "next/link";
import { useInfiniteQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import styles from "./video-studio.module.css";

const route = "/api/v1/video-studio/workspaces/{workspace_id}/editing-works" as const;

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

  return <section className={styles.editingWorks} aria-label="剪辑成片">
    <div className={styles.sectionHeading}><h2>剪辑成片</h2></div>
    {works.isPending && <p role="status">正在读取剪辑成片…</p>}
    {works.isError && <p role="alert">
      暂时无法读取剪辑成片。 <button type="button" className={styles.textButton} onClick={() => void (works.isFetchNextPageError ? works.fetchNextPage() : works.refetch())}>重试</button>
    </p>}
    {works.isSuccess && !items.length && <p>{term ? "没有找到匹配的剪辑成片。" : "完成的剪辑成片会出现在这里。"}</p>}
    {!!items.length && <div className={styles.worksGrid}>{items.map(work => <article key={work.task_id} className={styles.workCard}>
      <video controls playsInline preload="none" className={styles.editingWorkVideo} src={work.final.url} aria-label={`剪辑成片 · ${work.project_title}`} />
      <div>
        <b>{work.project_title}</b>
        <time dateTime={work.created_at}>{new Date(work.created_at).toLocaleString("zh-CN")}</time>
        <p>{work.mode === "native_plan" ? "动效剪辑" : "字幕剪辑"}{work.final.duration_ms != null && ` · ${(work.final.duration_ms / 1000).toFixed(1)} 秒`}</p>
        <div className={styles.workActions}>
          <a className={styles.textButton} href={work.final.url} download>下载成片</a>
          <Link className={styles.textButton} href={`/video-studio/editing?project=${encodeURIComponent(work.project_id)}`}>查看项目剪辑</Link>
        </div>
      </div>
    </article>)}</div>}
    {works.hasNextPage && !works.isFetchNextPageError && <button type="button" className={styles.textButton} disabled={works.isFetchingNextPage} onClick={() => void works.fetchNextPage()}>
      {works.isFetchingNextPage ? "正在加载…" : "加载更多剪辑成片"}
    </button>}
  </section>;
}
