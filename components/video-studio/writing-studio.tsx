"use client";

import { useEffect, useState } from "react";
import { ArrowRight, Check, Copy, FolderOpen } from "lucide-react";
import type { AssistantMode } from "@/features/video-studio/assistance";
import type { VideoContent, VideoDraft } from "@/features/video-studio/projects";
import type { useProjectSession } from "@/features/video-studio/use-project-session";
import type { ScriptReference } from "@/features/video-studio/use-script-reference";
import { WRITING_STEPS, assistantModeFor, completedSteps, suggestedStep, type WritingStep } from "@/features/video-studio/writing-steps";
import { ScriptAssistantPanel } from "./script-assistant-panel";
import type { ToastTone } from "./studio-toast";
import styles from "./video-studio.module.css";
import page from "./writing-studio.module.css";

type ProjectSession = ReturnType<typeof useProjectSession>["session"];

const stepOfMode = (mode: AssistantMode): WritingStep => mode === "benchmark" ? "benchmark" : mode === "extract" ? "analyze" : "rewrite";

/**
 * 爆款文案 workspace (line A): five steps over one video project. Each step
 * reuses the existing assistant tools; nothing here talks to providers directly.
 */
export function WritingStudio({ workspaceId, projectId, session, content, writing, savedTexts, notify, attempt, copyText, updateDraft, onSaveToLibrary, onUseForVoice }: {
  workspaceId: string;
  projectId: string;
  session: ProjectSession;
  content: VideoContent;
  writing: ScriptReference;
  savedTexts: string[];
  notify: (text: string, tone?: ToastTone) => void;
  attempt: (operation: () => Promise<unknown>) => void;
  copyText: (text: string) => void;
  updateDraft: (patch: Partial<VideoDraft>) => void;
  onSaveToLibrary: () => void;
  onUseForVoice: () => void;
}) {
  const progress = { references: content.references.length, productFacts: content.product_facts, draftText: content.draft.text, savedTexts };
  const done = completedSteps(progress);
  const [chosen, setChosen] = useState<{ projectId: string; step: WritingStep }>();
  const [original, setOriginal] = useState(false);
  const step = chosen?.projectId === projectId ? chosen.step : suggestedStep(progress);
  const mode = assistantModeFor(step, original);
  const { assistantMode, setAssistantMode } = writing;
  useEffect(() => { if (mode && assistantMode !== mode) setAssistantMode(mode); }, [mode, assistantMode, setAssistantMode]);
  const goTo = (next: WritingStep) => setChosen({ projectId, step: next });
  const current = WRITING_STEPS.find(item => item.id === step)!;
  const draft = content.draft.text;

  return <div className={page.writing}>
    <div className={styles.pageHeading}>
      <div><h1>爆款文案</h1><p>先找已验证的爆款，拆出结构，再按你的产品事实改写。定稿后直接做口播。</p></div>
      <button type="button" className={styles.primaryButton} disabled={!draft.trim()} onClick={onUseForVoice}>用这篇文案做口播 <ArrowRight size={16} /></button>
    </div>
    <div className={page.layout}>
      <ol className={page.steps} aria-label="爆款文案步骤">
        {WRITING_STEPS.map(item => <li key={item.id}>
          <button type="button" aria-current={item.id === step ? "step" : undefined} onClick={() => goTo(item.id)}>
            <span className={page.stepIndex} data-done={done.has(item.id) || undefined}>{done.has(item.id) ? <Check size={13} /> : item.index}</span>
            <span><b>{item.label}</b><small>{item.hint}</small></span>
          </button>
        </li>)}
      </ol>
      <section className={page.stage} aria-label={current.label}>
        <header className={page.stageHeader}>
          <div><span>第 {current.index} 步</span><h2>{current.label}</h2></div>
          {step === "rewrite" && <div className={styles.tabs} role="group" aria-label="生成方式">
            <button type="button" aria-pressed={!original} className={!original ? styles.activeTab : ""} onClick={() => setOriginal(false)}>改写参考</button>
            <button type="button" aria-pressed={original} className={original ? styles.activeTab : ""} onClick={() => setOriginal(true)}>直接原创</button>
          </div>}
        </header>

        {mode && <ScriptAssistantPanel workspaceId={workspaceId} projectId={projectId} session={session} content={content} writing={writing} hideTools
          onShowAssistant={next => goTo(stepOfMode(next))} onRevealScript={() => goTo("final")} onDraftReady={() => goTo("final")}
          notify={notify} attempt={attempt} copyText={copyText} updateDraft={updateDraft} />}

        {step === "facts" && <div className={page.facts}>
          <label>
            <span>产品事实</span>
            <textarea aria-label="产品事实" rows={9} maxLength={6000} value={content.product_facts}
              onChange={event => session.edit({ ...session.state.content, product_facts: event.target.value })}
              placeholder={"品牌、品名、规格、价格\n已确认的卖点和使用场景\n有出处的数据（写明来源）"} />
          </label>
          <p>改写只会使用这里写明的事实。没有依据的功效、价格、净含量和「最」「第一」这类绝对化说法不要写进来。更细的事实卡和禁写项，可以在「提取拆解」里的写作流程中设置。</p>
          <div className={page.actions}><button type="button" className={styles.primaryButton} onClick={() => goTo("rewrite")}>下一步：生成改写 <ArrowRight size={15} /></button></div>
        </div>}

        {step === "final" && <div className={page.final}>
          {draft.trim() ? <>
            <label>
              <span>定稿文案 <small>{draft.length} / 3000</small></span>
              <textarea aria-label="定稿文案" rows={14} maxLength={3000} value={draft} onChange={event => updateDraft({ text: event.target.value })} />
            </label>
            <p>逐句核对产品事实后再定稿。改写稿每一句的事实来源，可以在写作流程里查看。</p>
            <div className={page.actions}>
              <button type="button" className={styles.outlineButton} onClick={() => copyText(draft)}><Copy size={15} />复制全文</button>
              <button type="button" className={styles.outlineButton} disabled={done.has("final")} onClick={onSaveToLibrary}><FolderOpen size={15} />{done.has("final") ? "已在文案库" : "存入文案库"}</button>
              <button type="button" className={styles.primaryButton} onClick={onUseForVoice}>用这篇文案做口播 <ArrowRight size={15} /></button>
            </div>
          </> : <div className={page.empty}>
            <b>还没有可定稿的文案</b>
            <p>在「生成改写」里采用一版结果，或直接原创一篇。</p>
            <button type="button" className={styles.primaryButton} onClick={() => goTo("rewrite")}>去生成改写 <ArrowRight size={15} /></button>
          </div>}
        </div>}
      </section>
    </div>
  </div>;
}
