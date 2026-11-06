"use client";

import { useEffect, useState } from "react";
import { Check, CircleAlert, Film, LoaderCircle, Sparkles } from "lucide-react";
import type { GenerationJob } from "@/features/video-studio/library";
import { elapsedLabel, generationProgress } from "@/features/video-studio/generation-progress";
import styles from "./generation-progress.module.css";

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
  const hint = state.stopped ? job.status === "unknown" ? "正在核对原提交，请保留此任务。" : "已保存的音频和素材会保留，可从原任务继续。" : state.review ? "确认人物和动作满意后，加入我的形象。" : state.done ? "已保存到你的账号，可以预览和下载。" : elapsed >= 120 ? "正在持续处理，完成后会自动更新。可以先关闭窗口。" : "完成后自动更新，关闭窗口也会继续处理。";
  return <section className={`${styles.panel} ${compact ? styles.compact : ""}`} data-state={state.active ? "active" : state.stopped ? "stopped" : "done"} aria-busy={state.active} aria-label={job.kind === "h3_template" ? "形象创建进度" : "视频生成进度"}>
    {!compact && <div className={styles.visual} aria-hidden="true"><span className={styles.orbit} /><span className={styles.orbitInner} /><span className={styles.core}>{state.active ? <Film size={31} /> : state.stopped ? <CircleAlert size={31} /> : <Check size={31} />}</span>{state.active && <><Sparkles className={styles.sparkle} size={17} /><span className={styles.dot} /></>}</div>}
    <div className={styles.heading}><h3>{compact && (state.active ? <LoaderCircle className={styles.spinner} size={14} /> : state.stopped ? <CircleAlert size={14} /> : <Check size={14} />)}{state.title}</h3>{state.active && <time>{elapsedLabel(elapsed)}</time>}</div>
    <div className={styles.track} role="progressbar" aria-label="处理阶段" aria-valuemin={0} aria-valuemax={4} aria-valuenow={state.step} aria-valuetext={state.title}><span style={{ width: `${state.width}%` }} /></div>
    {!compact && <ol className={styles.steps}>{steps.map((step, index) => <li key={step} data-state={index < state.step ? "done" : index === state.step && state.active ? "current" : "waiting"}><span>{index < state.step ? <Check size={11} /> : index + 1}</span>{step}</li>)}</ol>}
    {(!compact || state.stopped) && <p role="status">{hint}</p>}
  </section>;
}

export function GenerationImageStatus({ job }: { job: GenerationJob }) {
  const state = generationProgress(job);
  if (!state.active && !state.stopped && !state.review) return null;
  return <span className={styles.imageStatus} data-state={state.active ? "active" : "paused"}>{state.active ? <><span className={styles.scan} /><LoaderCircle className={styles.spinner} size={27} /><b>正在制作</b></> : <><CircleAlert size={24} /><b>{state.review ? "待确认" : "待处理"}</b></>}</span>;
}
