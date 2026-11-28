"use client";

import { ArrowRight, Flame } from "lucide-react";
import { useVideoCredits } from "@/features/video-studio/credits";
import type { VideoContent, VideoDraft } from "@/features/video-studio/projects";
import type { useProjectSession } from "@/features/video-studio/use-project-session";
import type { ScriptReference } from "@/features/video-studio/use-script-reference";
import { ScriptAssistant } from "./script-assistant";
import type { ToastTone } from "./studio-toast";
import styles from "./studio-workflow.module.css";

type ProjectSession = ReturnType<typeof useProjectSession>["session"];

/**
 * The editor keeps one quick tool: write an original script from a brief.
 * Everything built on a benchmark (search, links, transcripts, teardown,
 * shadow rewrite) lives on the 爆款文案 page, so there is one place for it.
 */
export function ScriptAssistantPanel({ workspaceId, session, content, writing, onRevealScript, notify, attempt, copyText, updateDraft, onGoWriting }: {
  workspaceId: string;
  projectId: string;
  session: ProjectSession;
  content: VideoContent;
  writing: ScriptReference;
  onRevealScript: () => void;
  notify: (text: string, tone?: ToastTone) => void;
  attempt: (operation: () => Promise<unknown>) => void;
  copyText: (text: string) => void;
  updateDraft: (patch: Partial<VideoDraft>) => void;
  onGoWriting: () => void;
}) {
  const { assistance, assistantResult } = writing;
  const credits = useVideoCredits(workspaceId);
  const writingNote = credits.note(["writing_generate"]);
  const job = assistance.latest("create");
  return <div className={styles.assistantStack}>
    <button type="button" className={styles.viralEntry} onClick={onGoWriting}>
      <Flame size={18} />
      <span><b>照着爆款写</b><small>按点赞找抖音、小红书爆款，拆解后换成你的事实一键仿写</small></span>
      <ArrowRight size={15} />
    </button>
    <ScriptAssistant hideTools mode="create" onModeChange={() => undefined}
      prompt={writing.assistantPrompt} onPromptChange={writing.setAssistantPrompt} style={writing.assistantType} onStyleChange={writing.setAssistantType}
      facts={content.product_facts} onFactsChange={facts => session.edit({ ...session.state.content, product_facts: facts })}
      sourceLink="" onSourceLinkChange={() => undefined} sourceText="" onSourceTextChange={() => undefined}
      result={assistantResult} onResultChange={() => undefined}
      writingCredits={writingNote.credits} writingShort={writingNote.insufficient}
      job={job} busy={assistance.busy("create")}
      onSubmit={() => writing.generateCopy()}
      onResume={() => job && attempt(() => assistance.resume(job.id))} onCopy={copyText} onUseOriginal={() => undefined}
      onUseResult={() => {
        if (assistantResult.length > 3000) return notify("文案超过3000字，请先明确选择要使用的片段；不会自动截断", "warning");
        updateDraft({ text: assistantResult }); onRevealScript(); notify("已填入文案编辑区", "success");
      }} />
  </div>;
}
