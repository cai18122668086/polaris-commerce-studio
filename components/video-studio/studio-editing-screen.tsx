"use client";

import type { CostNote } from "@/features/video-studio/credit-notes";
import type { GenerationJob } from "@/features/video-studio/library";
import type { VideoDraft } from "@/features/video-studio/projects";
import type { useProjectSession } from "@/features/video-studio/use-project-session";
import { EditingWorkspace } from "./editing-workspace";
import styles from "./video-studio.module.css";
import { PageHero } from "./page-hero";

type ProjectSessionState = ReturnType<typeof useProjectSession>;

/** The 智能剪辑 page: project picker plus the editing workspace for that project. */
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
  const { session, content, projectId, status } = persisted;
  const draft = content.draft;
  return <><PageHero eyebrow="智能剪辑" title="一条口播，剪成" accent="有节奏的成片" description="选一条口播或上传视频，挑一个模板；字幕、花字、音效和配乐自动编排，预览满意再下载高清。" facts={[{ label: "可用口播", value: jobs.filter(job => job.kind === "lipsync" && job.status === "completed").length }, { label: "剪辑项目", value: persisted.projects.length }]} motif="edit" /><details className={styles.editingProject}><summary>{draft.name || "未命名视频"}</summary><div className={styles.editorHeader}>
      <label className={styles.projectName}><span>剪辑项目名称</span><input aria-label="剪辑项目名称" value={draft.name} maxLength={80} onChange={event => updateDraft({ name: event.target.value })} /></label>
      <select aria-label="切换剪辑项目" value={persisted.projects.some(p => p.id === projectId) ? projectId : ""} onChange={event => attempt(() => session.select(event.target.value))}><option value="" disabled>新项目</option>{persisted.projects.map(p => <option value={p.id} key={p.id}>{p.content.draft.name || "未命名视频"}</option>)}</select>
      <button type="button" onClick={() => attempt(async () => { await session.newProject(); await saveEditingProject(); })}>新建剪辑项目</button>
      <span role="status">{status === "saving" ? "保存中" : persisted.revision ? "已保存" : "选视频后自动保存"}</span>
    </div></details><EditingWorkspace key={`${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={projectId} saved={Boolean(persisted.revision)} jobs={jobs} cost={cost} renderCredits={renderCredits} onSaveProject={saveEditingProject} /></>;
}
