"use client";

import { useSearchParams } from "next/navigation";
import { useSyncExternalStore } from "react";
import type { CostNote } from "@/features/video-studio/credit-notes";
import type { GenerationJob } from "@/features/video-studio/library";
import type { VideoDraft } from "@/features/video-studio/projects";
import type { useProjectSession } from "@/features/video-studio/use-project-session";
import { editingHref, parseFlowParams } from "@/features/video-studio/flow-params";
import { EditingBatchFlow } from "./editing-batch-flow";
import flowStyles from "./editing-batch-flow.module.css";
import { EditingWorkspace } from "./editing-workspace";
import styles from "./video-studio.module.css";
import { PageHero } from "./page-hero";

type ProjectSessionState = ReturnType<typeof useProjectSession>;

const subscribeToHash = (listener: () => void) => {
  window.addEventListener("hashchange", listener);
  return () => window.removeEventListener("hashchange", listener);
};
const legacyTaskLink = () => window.location.hash.startsWith("#editing-task-");

/**
 * 智能剪辑页。默认是四步批量剪辑（① 选视频 → ② 选模板 → ③ 补充素材 → ④ 生成）；
 * 「精修这一条」（?mode=refine）和旧任务链接（#editing-task-…）进入单条精修工作台。
 */
export function StudioEditingScreen({ workspaceId, persisted, jobs, attempt, updateDraft, saveEditingProject, cost, renderCredits }: {
  workspaceId: string;
  persisted: ProjectSessionState;
  jobs: GenerationJob[];
  attempt: (operation: () => Promise<unknown>) => void;
  updateDraft: (patch: Partial<VideoDraft>) => void;
  saveEditingProject: () => Promise<void>;
  cost?: CostNote;
  renderCredits?: number | null;
}) {
  const params = useSearchParams();
  const flow = parseFlowParams(params);
  const fromTaskLink = useSyncExternalStore(subscribeToHash, legacyTaskLink, () => false);
  const refine = params.get("mode") === "refine" || fromTaskLink;
  const { session, content, projectId, status } = persisted;
  const draft = content.draft;
  if (!refine) {
    const ensureUploadProject = async () => {
      if (!persisted.revision) await saveEditingProject();
      return projectId;
    };
    return <><PageHero eyebrow="智能剪辑" title="一批口播，剪成" accent="一批成片" description="选好视频和模板，可选补充素材；每条自动识别口播、编排字幕花字和动效，剪完直接导出高清，再去成片。" facts={[{ label: "可用口播", value: jobs.filter(job => job.kind === "lipsync" && job.status === "completed").length }]} motif="edit" />
      <EditingBatchFlow key={`${workspaceId}:${flow.batch ?? ""}`} workspaceId={workspaceId} batchId={flow.batch ?? null} jobs={jobs} uploadProjectId={projectId} ensureUploadProject={ensureUploadProject} cost={cost} /></>;
  }
  return <><PageHero eyebrow="精修这一条" title="单条精修：" accent="字幕、画面逐段调整" description="校对字幕、调整本版画面或重新编排；确认高清后，这条作品会更新为最新版本。" facts={[{ label: "剪辑项目", value: persisted.projects.length }]} motif="edit" />
    {flow.batch && <p className={flowStyles.back}><a href={editingHref(flow.batch)}>← 回到这一批的剪辑结果</a></p>}
    <details className={styles.editingProject}><summary>{draft.name || "未命名视频"}</summary><div className={styles.editorHeader}>
      <label className={styles.projectName}><span>剪辑项目名称</span><input aria-label="剪辑项目名称" value={draft.name} maxLength={80} onChange={event => updateDraft({ name: event.target.value })} /></label>
      <select aria-label="切换剪辑项目" value={persisted.projects.some(p => p.id === projectId) ? projectId : ""} onChange={event => attempt(() => session.select(event.target.value))}><option value="" disabled>新项目</option>{persisted.projects.map(p => <option value={p.id} key={p.id}>{p.content.draft.name || "未命名视频"}</option>)}</select>
      <button type="button" onClick={() => attempt(async () => { await session.newProject(); await saveEditingProject(); })}>新建剪辑项目</button>
      <span role="status">{status === "saving" ? "保存中" : persisted.revision ? "已保存" : "选视频后自动保存"}</span>
    </div></details><EditingWorkspace key={`${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={projectId} saved={Boolean(persisted.revision)} jobs={jobs} cost={cost} renderCredits={renderCredits} onSaveProject={saveEditingProject} workItemId={flow.item ?? undefined} /></>;
}
