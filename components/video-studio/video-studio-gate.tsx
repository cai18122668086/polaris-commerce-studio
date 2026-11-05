"use client";

import Link from "next/link";
import { useVideoStudioGrantState } from "@/features/video-studio/access";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { VideoStudio, type StudioScreen } from "./video-studio";

export function VideoStudioGate({ screen }: { screen: StudioScreen }) {
  const grant = useVideoStudioGrantState();
  const workspaceQuery = useWorkspace();
  const workspace = workspaceQuery.workspace;
  const userId = grant.userId;
  if (grant.status === "denied" || grant.status === "revoked") return <main style={{ padding: "15vh 24px", textAlign: "center" }}>
    <h1>页面暂不可用</h1><p>请返回首页继续使用。</p><Link href="/">返回首页</Link>
  </main>;
  const error = grant.status === "error" || workspaceQuery.workspaceState === "error";
  const waiting = !userId || !workspace;
  return <>
    {waiting && <main style={{ padding: "15vh 24px", textAlign: "center" }} aria-busy={!error}>
      <h1>{error ? "连接暂时未能恢复" : "正在准备视频空间"}</h1>
      <p>{error ? "访问确认暂时失败，请重新检查；已载入的编辑内容会保留。" : "正在核验访问权限并载入工作区，请稍候。"}</p>
      {error && <button type="button" className="auth-button auth-button--primary" onClick={() => { grant.retry(); void workspaceQuery.refetch(); }}>重新检查</button>}
      {workspaceQuery.workspaceState === "empty" && <Link href="/account">查看工作区</Link>}
    </main>}
    {!waiting && error && <div role="alert" style={{ padding: "12px 24px", background: "#f7f4fd", textAlign: "center" }}>
      连接暂时中断，已载入的内容仍保留。<button type="button" onClick={() => { grant.retry(); void workspaceQuery.refetch(); }}>重新检查</button>
    </div>}
    {userId && workspace && <div>
      <VideoStudio key={`${userId}:${workspace.id}`} screen={screen} userId={userId} workspaceId={workspace.id} />
    </div>}
  </>;
}
