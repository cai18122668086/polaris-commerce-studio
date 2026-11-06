"use client";

import { ArrowDownToLine, AudioLines, Check, Clock3, PackageOpen } from "lucide-react";
import type { GenerationJob } from "@/features/video-studio/library";
import { Dialog } from "./studio-primitives";
import { GenerationDetails } from "./generation-details";
import { GenerationProgress, GenerationResumeButton } from "./generation-progress";
import { Notice } from "./studio-content";
import base from "./video-studio.module.css";
import styles from "./generation-details.module.css";

export function GenerationPreview({ job, resuming, submitting, onClose, onResume, onApprove, onReject, onCopy }: {
  job:GenerationJob; resuming:boolean; submitting:boolean; onClose:()=>void; onResume:()=>void; onApprove:()=>void; onReject:()=>void; onCopy:(text:string)=>void;
}) {
  return <Dialog title={job.kind === "h3_template" ? "形象预览" : "口播视频"} onClose={onClose}>
    {job.video_url ? <video controls playsInline preload="metadata" src={job.video_url} className={styles.media} /> : <GenerationProgress job={job} />}
    <p className={styles.timestamp}><Clock3 size={12} />{new Date(job.created_at).toLocaleString("zh-CN", {month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false})} 创建</p>
    <GenerationDetails job={job} onCopy={onCopy} />
    {job.handoff_url && <p className={styles.handoffNote}>剪辑材料含文案、配音与原片 · 字幕待对齐</p>}
    {job.status === "awaiting_review" && <Notice>预览人物与动作，确认满意后加入我的形象。</Notice>}
    <footer className={styles.actions}>
      {job.audio_url && <a className={base.outlineButton} href={job.audio_url} download><AudioLines size={14} />下载配音</a>}
      {job.handoff_url && <a className={base.outlineButton} href={job.handoff_url} download title="文案、配音与原片；字幕待音文对齐"><PackageOpen size={14} />剪辑材料</a>}
      {job.can_resume && <GenerationResumeButton job={job} className={base.primaryButton} resuming={resuming} onResume={onResume} />}
      {job.status === "awaiting_review" && <><button type="button" className={base.outlineButton} disabled={submitting} onClick={onReject}>不加入形象库</button><button type="button" className={base.primaryButton} disabled={submitting} onClick={onApprove}><Check size={14} />确认并加入形象库</button></>}
      {job.video_url && <a className={base.primaryButton} href={job.video_url} download><ArrowDownToLine size={14} />下载视频</a>}
    </footer>
  </Dialog>;
}
