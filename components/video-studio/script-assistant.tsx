"use client";

import { AlertCircle, ArrowDownToLine, ArrowRight, Copy, FilePenLine, LoaderCircle, Search, Send, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { assistanceMessage, type AssistanceJob, type AssistantMode } from "@/features/video-studio/assistance";
import { Disclosure, TextDocument } from "./studio-content";
import styles from "./studio-workflow.module.css";

const tools = [
  { id: "benchmark", label: "找对标", icon: Search, title: "按方向找抖音对标", hint: "" },
  { id: "extract", label: "视频提取", icon: ArrowDownToLine, title: "从视频开始创作", hint: "粘贴公开抖音链接，提取语音文案后核对、改写。" },
  { id: "create", label: "文案原创", icon: Sparkles, title: "把想法写成好文案", hint: "告诉我产品和受众，生成一段自然的口播文案。" },
  { id: "rewrite", label: "文案二创", icon: FilePenLine, title: "让表达更适合你", hint: "结合真实产品信息，重新组织参考文案。" },
] as const;

export function ScriptAssistant(props: {
  mode: AssistantMode; onModeChange: (mode: AssistantMode) => void;
  prompt: string; onPromptChange: (text: string) => void;
  style: string; onStyleChange: (style: string) => void;
  facts: string; onFactsChange: (facts: string) => void;
  sourceLink: string; onSourceLinkChange: (link: string) => void;
  sourceText: string; onSourceTextChange: (text: string) => void;
  result: string; onResultChange: (text: string) => void;
  job?: AssistanceJob; busy: boolean; onSubmit: () => void; onResume: () => void;
  onUseResult: () => void; onUseOriginal: () => void; onCopy: (text: string) => void;
  workflow?: ReactNode;
  benchmark?: ReactNode;
}) {
  const tool = tools.find(item => item.id === props.mode)!;
  const Icon = tool.icon;
  const status = assistanceMessage(props.job);
  const running = props.job?.status === "queued" || props.job?.status === "running";
  const badStatus = props.job?.status === "failed" || props.job?.status === "unknown";
  const canSubmit = props.mode === "create" ? !!props.prompt.trim() : props.mode === "extract" ? !!props.sourceLink.trim() : !!props.sourceText.trim();
  const result = props.mode === "extract" ? props.sourceText : props.result;

  const navigation = <div className={styles.assistantTools} role="group" aria-label="文案助手工具">{tools.map(item => <button key={item.id} type="button" aria-pressed={props.mode === item.id} onClick={() => props.onModeChange(item.id)}><item.icon size={16} />{item.label}</button>)}</div>;
  if (props.mode === "benchmark") return <div className={styles.assistantPanel}>
    {navigation}
    <div className={styles.assistantScroll}>{props.benchmark}</div>
  </div>;

  return <div className={styles.assistantPanel}>
    {navigation}
    <div className={styles.assistantScroll}>
      {props.workflow}
      <div className={styles.toolIntro}><span><Icon size={25} /></span><h2>{tool.title}</h2><p>{tool.hint}</p></div>
      {props.mode === "extract" ? <label className={styles.assistantField}>参考视频链接<input type="url" aria-label="参考视频链接" value={props.sourceLink} onChange={event => props.onSourceLinkChange(event.target.value)} placeholder="粘贴公开抖音视频链接" maxLength={2048} /><small>当前支持公开抖音视频，提取后请核对转写内容。</small></label>
        : props.mode === "rewrite" ? <label className={styles.assistantField}><span>参考文案<button type="button" onClick={() => props.onModeChange("extract")}>从视频提取 <ArrowRight size={12} /></button></span><textarea aria-label="原始文案" rows={5} value={props.sourceText} onChange={event => props.onSourceTextChange(event.target.value)} maxLength={6000} placeholder="粘贴参考文案，也可以先从视频提取" /></label>
          : <div className={styles.assistantSuggestions}>{["写一段产品介绍", "写一个吸引人的口播开场", "把产品卖点讲得更自然"].map(text => <button type="button" key={text} onClick={() => props.onPromptChange(text)}>{text}<ArrowRight size={13} /></button>)}</div>}
      {props.mode !== "extract" && <Disclosure title="产品资料" description="补充真实卖点与规格" meta={props.facts.trim() ? "已填写" : "选填"}><label className={styles.assistantField}><textarea aria-label="产品事实" rows={4} maxLength={6000} value={props.facts} onChange={event => props.onFactsChange(event.target.value)} placeholder="品牌、规格、价格、已确认卖点…" /></label></Disclosure>}
      {status && <div className={styles.assistantStatus} data-error={badStatus || undefined} role={badStatus ? "alert" : "status"}>{running ? <LoaderCircle size={16} className={styles.spin} /> : <AlertCircle size={16} />}<p>{status}</p>{props.job?.can_resume && <button type="button" onClick={props.onResume}>继续原任务</button>}</div>}
      {result.trim() && <section className={styles.assistantResult}><header><b>{props.mode === "extract" ? "提取原文" : "待确认文案"}</b><span>{result.length} 字</span><button type="button" aria-label="复制助手结果全文" onClick={() => props.onCopy(result)}><Copy size={14} /></button></header>
        {props.mode === "create" ? <TextDocument key={props.job?.id || "result"} text={result} title="文案预览" onCopy={props.onCopy} /> : <textarea aria-label={props.mode === "extract" ? "提取原文" : "改写结果"} value={result} onChange={event => props.mode === "extract" ? props.onSourceTextChange(event.target.value) : props.onResultChange(event.target.value)} rows={7} />}
        {props.job?.result.warnings?.length ? <ul className={styles.resultWarnings}>{props.job.result.warnings.map((warning,index) => <li key={index}>{warning}</li>)}</ul> : null}
        <div className={styles.assistantResultActions}>{props.mode === "extract" && <button type="button" className={styles.secondaryButton} onClick={() => props.onModeChange("rewrite")}>继续二创</button>}<button type="button" className={styles.actionButton} onClick={props.mode === "extract" ? props.onUseOriginal : props.onUseResult}>填入编辑器 <ArrowRight size={14} /></button></div>
      </section>}
    </div>
    <div className={styles.assistantInputArea}>
      {props.mode === "create" && <><label className={styles.assistantStyle}>文案风格<select aria-label="文案类型" value={props.style} onChange={event => props.onStyleChange(event.target.value)}>{["产品介绍", "好物种草", "知识分享", "品牌故事"].map(value => <option key={value}>{value}</option>)}</select></label><textarea aria-label="告诉文案助手你的需求" value={props.prompt} onChange={event => props.onPromptChange(event.target.value)} maxLength={1500} rows={3} placeholder="产品是什么？讲给谁听？希望突出什么？" /></>}
      <div className={styles.assistantSubmit}><small>{props.mode === "create" ? `${props.prompt.length} / 1500` : props.mode === "extract" ? "提取结果不会自动覆盖当前文案" : "生成后请核对产品事实"}</small><button type="button" disabled={props.busy || !canSubmit} onClick={props.onSubmit}>{running ? <LoaderCircle size={15} className={styles.spin} /> : props.mode === "extract" ? <ArrowDownToLine size={15} /> : <Send size={15} />}{running ? "处理中…" : props.mode === "extract" ? "提取文案" : props.mode === "rewrite" ? "生成改写" : "生成文案"}</button></div>
    </div>
  </div>;
}
