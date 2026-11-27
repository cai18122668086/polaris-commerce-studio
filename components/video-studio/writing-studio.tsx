"use client";

import type { VideoContent, VideoDraft } from "@/features/video-studio/projects";
import type { useProjectSession } from "@/features/video-studio/use-project-session";
import type { ScriptReference } from "@/features/video-studio/use-script-reference";
import type { ToastTone } from "./studio-toast";
import page from "./writing-studio.module.css";
import { PageHero } from "./page-hero";
import { ViralWriting } from "./viral-writing";

type ProjectSession = ReturnType<typeof useProjectSession>["session"];

/**
 * 爆款文案: find benchmarks by likes (or paste links) → confirm → expert
 * teardown → the user's own facts → one-click shadow rewrite → adopt and go
 * on to 口播. The older assistant tools stay available inside the editor.
 */
export function WritingStudio({ workspaceId, projectId, session, content, notify, copyText, onUseForVoice }: {
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
}) {
  return <div className={page.writing}>
    <PageHero eyebrow="爆款文案" title="照着爆款写，" accent="说的是你自己的事"
      description="按点赞找到同类爆款，拆出它的钩子、结构和表达，再换成你的身份、产品和经历，一键仿写成口播稿。"
      facts={[{ label: "对标平台", value: "抖音 · 小红书 · B站" }, { label: "每次对标", value: "最多 3 条" }]}
      motif="script" />
    <ViralWriting key={projectId} workspaceId={workspaceId} projectId={projectId} session={session} productFacts={content.product_facts}
      copyText={copyText}
      onAdopted={async () => { await session.select(projectId); notify("文案已放进口播编辑器", "success"); onUseForVoice(); }} />
  </div>;
}
