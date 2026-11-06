"use client";

import { useEffect, useState } from "react";
import { Check, CircleAlert, Clock3, Film, LoaderCircle, Play, Sparkles } from "lucide-react";
import type { GenerationJob } from "@/features/video-studio/library";
import { elapsedLabel, generationProgress } from "@/features/video-studio/generation-progress";
import styles from "./generation-progress.module.css";

export function GenerationResumeButton({ job, onResume, resuming = false, className }: { job: GenerationJob; onResume: () => void; resuming?: boolean; className?: string }) {
  const state = generationProgress(job);
  return <button className={className} type="button" disabled={resuming} onClick={onResume}>{resuming ? state.waitingForResult ? "正在查询…" : "正在继续…" : state.resumeLabel}</button>;
}

export function GenerationProgress({ job, compact = false }: { job: GenerationJob; compact?: boolean }) {
  const state = generationProgress(job);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!state.active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [state.active, job.id]);
  const began = Date.parse(job.created_at);
  const elapsed = Number.isFinite(began) ? Math.max(0, (now - began) / 1000) : 0;
  const steps = job.kind === "h3_template" ? ["上传素材", "生成动作", "保存形象", "预览确认"] : ["准备配音", "匹配动作", "生成视频", "保存成片"];
  const hint = state.waitingForResult ? "暂未收到生成结果，请继续查询原任务，无需重新生成。" : job.status === "unknown" ? "提交结果尚未确认，请保留此任务，避免重复生成。" : job.status === "rejected" ? "此形象未加入素材库，可以返回重新选择。" : state.stopped && !job.can_resume ? "已完成的内容已保留，请检查素材与设置。" : state.waiting || state.stopped ? "已保存的音频和素材会保留，可从原任务继续。" : state.review ? "确认人物和动作满意后，加入我的形象。" : state.done ? "已保存到你的账号，可以预览和下载。" : elapsed >= 120 ? "正在查询生成结果，完成后会自动更新。可以先关闭窗口，稍后查看。" : "正在处理当前任务，完成后自动更新。";
  return <section className={`${styles.panel} ${compact ? styles.compact : ""}`} data-state={state.active ? "active" : state.waiting ? "waiting" : state.stopped ? "stopped" : "done"} aria-busy={state.active} aria-label={job.kind === "h3_template" ? "形象创建进度" : "视频生成进度"}>
    {!compact && <div className={styles.visual} aria-hidden="true"><span className={styles.orbit} /><span className={styles.orbitInner} /><span className={styles.core}>{state.active ? <Film size={31} /> : state.waiting ? <Clock3 size={31} /> : state.stopped ? <CircleAlert size={31} /> : <Check size={31} />}</span>{state.active && <><Sparkles className={styles.sparkle} size={17} /><span className={styles.dot} /></>}</div>}
    <div className={styles.heading}><h3>{compact && (state.active ? <LoaderCircle className={styles.spinner} size={14} /> : state.waiting ? <Clock3 size={14} /> : state.stopped ? <CircleAlert size={14} /> : <Check size={14} />)}{state.title}</h3>{state.active && <time>{elapsedLabel(elapsed)}</time>}</div>
    <div className={styles.track} role="progressbar" aria-label="处理阶段" aria-valuemin={0} aria-valuemax={4} aria-valuenow={state.step} aria-valuetext={state.title}><span style={{ width: `${state.width}%` }} /></div>
    {!compact && <ol className={styles.steps}>{steps.map((step, index) => <li key={step} data-state={index < state.step ? "done" : index === state.step && (state.active || state.waiting) ? "current" : "waiting"}><span>{index < state.step ? <Check size={11} /> : index + 1}</span>{step}</li>)}</ol>}
    {(!compact || state.stopped || state.waiting) && <p role="status">{hint}</p>}
  </section>;
}

export function GenerationImageStatus({ job }: { job: GenerationJob }) {
  const state = generationProgress(job);
  if (!state.active && !state.stopped && !state.waiting && !state.review) return null;
  return <span className={styles.imageStatus} data-state={state.active ? "active" : state.waiting ? "waiting" : "paused"}>{state.active ? <><span className={styles.scan} /><LoaderCircle className={styles.spinner} size={27} /><b>正在制作</b></> : state.waiting ? <><Clock3 size={24} /><b>{state.waitingForResult ? "等待生成结果" : "等待继续处理"}</b></> : state.review ? <><Play size={24} /><b>待确认</b></> : <><CircleAlert size={24} /><b>待处理</b></>}</span>;
}
