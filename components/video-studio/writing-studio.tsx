"use client";

import { ArrowRight } from "lucide-react";
import type { VideoContent, VideoDraft } from "@/features/video-studio/projects";
import type { useProjectSession } from "@/features/video-studio/use-project-session";
import type { ScriptReference } from "@/features/video-studio/use-script-reference";
import { ScriptAssistantPanel } from "./script-assistant-panel";
import type { ToastTone } from "./studio-toast";
import styles from "./video-studio.module.css";

type ProjectSession = ReturnType<typeof useProjectSession>["session"];

/**
 * 爆款文案 workspace (line A). Owns everything under this screen; the studio
 * shell only mounts it. v0 shows the existing assistant full width.
 */
export function WritingStudio({ workspaceId, projectId, session, content, writing, notify, attempt, copyText, updateDraft, onUseForVoice }: {
  workspaceId: string;
  projectId: string;
  session: ProjectSession;
  content: VideoContent;
  writing: ScriptReference;
  notify: (text: string, tone?: ToastTone) => void;
  attempt: (operation: () => Promise<unknown>) => void;
  copyText: (text: string) => void;
  updateDraft: (patch: Partial<VideoDraft>) => void;
  onUseForVoice: () => void;
}) {
  return <>
    <div className={styles.pageHeading}>
      <div><h1>爆款文案</h1><p>找对标、拆结构、按产品事实改写，定稿后直接做口播。</p></div>
      <button type="button" className={styles.primaryButton} disabled={!content.draft.text.trim()} onClick={onUseForVoice}>用这篇文案做口播 <ArrowRight size={16} /></button>
    </div>
    <ScriptAssistantPanel workspaceId={workspaceId} projectId={projectId} session={session} content={content} writing={writing}
      onShowAssistant={mode => writing.setAssistantMode(mode)} onRevealScript={() => undefined}
      notify={notify} attempt={attempt} copyText={copyText} updateDraft={updateDraft} />
  </>;
}
