"use client";

import type { AssistantMode } from "@/features/video-studio/assistance";
import type { VideoContent, VideoDraft } from "@/features/video-studio/projects";
import type { useProjectSession } from "@/features/video-studio/use-project-session";
import type { ScriptReference } from "@/features/video-studio/use-script-reference";
import { BenchmarkSearch } from "./benchmark-search";
import { ScriptAssistant } from "./script-assistant";
import type { ToastTone } from "./studio-toast";
import { WritingWorkflow } from "./writing-workflow";

type ProjectSession = ReturnType<typeof useProjectSession>["session"];

/** Benchmark search, extraction, rewriting and original copy for one project. */
export function ScriptAssistantPanel({ workspaceId, projectId, session, content, writing, onShowAssistant, onRevealScript, notify, attempt, copyText, updateDraft, hideTools, onDraftReady }: {
  workspaceId: string;
  projectId: string;
  session: ProjectSession;
  content: VideoContent;
  writing: ScriptReference;
  onShowAssistant: (mode: AssistantMode, reveal?: boolean) => void;
  onRevealScript: () => void;
  notify: (text: string, tone?: ToastTone) => void;
  attempt: (operation: () => Promise<unknown>) => void;
  copyText: (text: string) => void;
  updateDraft: (patch: Partial<VideoDraft>) => void;
  hideTools?: boolean;
  /** Called after a result has been put into the draft. */
  onDraftReady?: () => void;
}) {
  const { assistance, assistantJob, assistantMode, assistantResult, rewrittenText } = writing;
  return <ScriptAssistant benchmark={<BenchmarkSearch key={"benchmark-" + projectId} workspaceId={workspaceId} jobs={assistance.benchmarkJobs} extractions={assistance.benchmarkExtractions}
    extractBusy={assistance.busy("extract")}
    onSearch={async criteria => {
      const target = session.state.projectId;
      await session.save();
      if (session.state.projectId !== target) return;
      await assistance.submitBenchmark({ ...criteria, project_id: target, expected_revision: session.state.revision });
    }}
    onNext={assistance.nextBenchmarkPage} onResume={assistance.resume}
    onExtract={async items => {
      const target = session.state.projectId;
      await session.save();
      if (session.state.projectId !== target) return;
      await assistance.submitBenchmarkExtractions({ project_id: target, expected_revision: session.state.revision, items });
    }}
    onUse={(item, page) => {
      const note = "抖音对标「" + page.result.keyword + "」，搜索任务 " + page.id;
      writing.setReferenceDraft({ projectId, link: item.source_url, text: "", note });
      onShowAssistant("extract", false);
      notify("已填入参考链接，可提取语音原文");
    }} />} workflow={<WritingWorkflow key={projectId} workspaceId={workspaceId} projectId={projectId} revision={session.state.revision} saved={session.state.status === "saved" && session.state.revision > 0} references={content.references} productFacts={content.product_facts} onApplied={async () => { await session.select(projectId); onRevealScript(); notify("已采用为新草稿，确认稿仍由原流程管理", "success"); }} />} mode={assistantMode} onModeChange={mode => onShowAssistant(mode, false)} prompt={writing.assistantPrompt} onPromptChange={writing.setAssistantPrompt} style={writing.assistantType} onStyleChange={writing.setAssistantType}
    facts={content.product_facts} onFactsChange={facts => session.edit({ ...session.state.content, product_facts: facts })}
    sourceLink={writing.sourceLink} onSourceLinkChange={writing.setSourceLink} sourceText={writing.sourceText} onSourceTextChange={writing.setSourceText}
    result={assistantMode === "create" ? assistantResult : rewrittenText} onResultChange={writing.setRewrittenText}
    job={assistantJob} busy={assistantMode !== "benchmark" && assistance.busy(assistantMode)}
    onSubmit={() => {
      if (assistantMode === "create") writing.generateCopy();
      if (assistantMode === "extract" || assistantMode === "rewrite") writing.runReference(assistantMode);
    }}
    onResume={() => assistantJob && attempt(() => assistance.resume(assistantJob.id))} onCopy={copyText} onUseOriginal={() => { if (writing.adoptReference(true)) onDraftReady?.(); }}
    onUseResult={() => { if (assistantMode === "rewrite") { if (writing.adoptReference()) onDraftReady?.(); return; } if (assistantResult.length > 3000) return notify("文案超过3000字，请先明确选择要使用的片段；不会自动截断", "warning"); updateDraft({ text: assistantResult }); onRevealScript(); notify("已填入文案编辑区", "success"); onDraftReady?.(); }}
    hideTools={hideTools} />;
}
