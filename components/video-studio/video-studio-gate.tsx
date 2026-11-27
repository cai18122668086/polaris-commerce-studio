"use client";

import Link from "next/link";
import { useLayoutEffect } from "react";
import { CircleHelp, LoaderCircle, WifiOff } from "lucide-react";
import { useVideoStudioGrantState } from "@/features/video-studio/access";
import { InternalToolsContext } from "@/features/video-studio/internal-tools";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { VideoStudio, type StudioScreen } from "./video-studio";
import styles from "./video-studio.module.css";
import workflow from "./studio-workflow.module.css";

export function VideoStudioGate({ screen }: { screen: StudioScreen }) {
  // 主题跟全站走：<html> 上是 theme-plaster（石膏灰白，2026-11-27 起视频空间也用）就是浅色，换回 theme-ember 就是暗色。
  // 两套主题都没挂时（单独渲染视频空间）才补上熔光暗色，离开时只撤掉自己加的。
  // data-video-studio：全站的主题层（app/ember-*.css、app/plaster*.css）据此跳过本页面，视频空间用自己模块里的主题块。
  useLayoutEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-video-studio", "");
    const added = !root.classList.contains("theme-ember") && !root.classList.contains("theme-plaster");
    if (added) root.classList.add("theme-ember");
    return () => {
      root.removeAttribute("data-video-studio");
      if (added) root.classList.remove("theme-ember");
    };
  }, []);
  const grant = useVideoStudioGrantState();
  const workspaceQuery = useWorkspace();
  const workspace = workspaceQuery.workspace;
  const userId = grant.userId;
  if (grant.status === "denied" || grant.status === "revoked") return <main className={`${styles.studio} ${styles.statusPage}`}>
    <section className={styles.statusCard}><CircleHelp size={32} /><h1>页面暂不可用</h1><p>请返回首页继续使用。</p><Link className={styles.primaryButton} href="/">返回首页</Link></section>
  </main>;
  const error = grant.status === "error" || workspaceQuery.workspaceState === "error";
  const waiting = !userId || !workspace;
  return <>
    {waiting && <main className={`${styles.studio} ${styles.statusPage}`} aria-busy={!error}>
      <section className={styles.statusCard}>{error ? <WifiOff size={32} /> : <LoaderCircle className={workflow.spin} size={32} />}<h1>{error ? "连接暂时未能恢复" : "正在准备视频空间"}</h1>
      <p>{error ? "连接暂时中断，已保存内容保留。" : "正在载入你的创作工作区，请稍候。"}</p>
      {error && <button type="button" className={styles.primaryButton} onClick={() => { grant.retry(); void workspaceQuery.refetch(); }}>重新检查</button>}
      {workspaceQuery.workspaceState === "empty" && <Link className={styles.outlineButton} href="/account">查看工作区</Link>}</section>
    </main>}
    {!waiting && error && <div role="alert" className={styles.connectionNotice}>
      <WifiOff size={15} />连接暂时中断，已载入的内容仍保留。<button type="button" className={styles.textButton} onClick={() => { grant.retry(); void workspaceQuery.refetch(); }}>重新检查</button>
    </div>}
    {userId && workspace && <div>
      <InternalToolsContext.Provider value={grant.internalTools === true}>
        <VideoStudio key={`${userId}:${workspace.id}`} screen={screen} userId={userId} workspaceId={workspace.id} />
      </InternalToolsContext.Provider>
    </div>}
  </>;
}
