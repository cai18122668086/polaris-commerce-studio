"use client";

import { useState } from "react";
import type { VideoContent, VideoDraft } from "@/features/video-studio/projects";
import type { useProjectSession } from "@/features/video-studio/use-project-session";
import type { ScriptReference } from "@/features/video-studio/use-script-reference";
import type { ToastTone } from "./studio-toast";
import page from "./writing-studio.module.css";
import { AutoWriting } from "./auto-writing";
import { PageHero } from "./page-hero";
import { ViralWriting } from "./viral-writing";

type ProjectSession = ReturnType<typeof useProjectSession>["session"];

/**
 * 爆款文案: by default the user gives a platform, a keyword or links and their
 * own facts once, and the AI does the rest (pick benchmarks, teardown, several
 * versions). The step-by-step flow stays available for choosing by hand.
 */
export function WritingStudio({ workspaceId, projectId, session, content, notify, copyText, onUseForVoice, onUseScripts }: {
  workspaceId: string;
  projectId: string;
  session: ProjectSession;
  content: VideoContent;
  writing?: ScriptReference;
  savedTexts?: string[];
  notify: (text: string, tone?: ToastTone) => void;
  attempt?: (operation: () => Promise<unknown>) => void;
  copyText: (text: string) => void;
  updateDraft?: (patch: Partial<VideoDraft>) => void;
  onSaveToLibrary?: () => void;
  onUseForVoice: () => void;
  /** Go to the voice page with these library entries (?scripts=id1,id2). */
  onUseScripts: (ids: string[]) => void;
}) {
  const [manual, setManual] = useState(false);
  const onAdopted = async () => { await session.select(projectId); notify("文案已放进口播编辑器", "success"); onUseForVoice(); };
  return <div className={page.writing}>
    <PageHero eyebrow="爆款文案" title="照着爆款写，" accent="说的是你自己的事"
      description="告诉 AI 去哪找、找什么，再写下你自己的产品和经历。AI 按点赞挑爆款、拆解，写好几版文案给你挑：每版都有标题、发布正文和口播稿，自动存进文案库。"
      facts={[{ label: "对标平台", value: "抖音 · 小红书" }, { label: "你要做的", value: "填一次，挑一版" }]}
      motif="script" />
    {manual
      ? <>
          <button type="button" className={page.switch} onClick={() => setManual(false)}>← 回到 AI 全自动</button>
          <ViralWriting key={projectId} workspaceId={workspaceId} projectId={projectId} session={session} productFacts={content.product_facts} copyText={copyText} onAdopted={onAdopted} onUseScripts={onUseScripts} />
        </>
      : <AutoWriting key={projectId} workspaceId={workspaceId} projectId={projectId} session={session} productFacts={content.product_facts} copyText={copyText} notify={notify} onUseScripts={onUseScripts} onManual={() => setManual(true)} />}
  </div>;
}
