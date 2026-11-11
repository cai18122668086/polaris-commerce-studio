"use client";

import { ArrowDownToLine, ArrowRight, AudioLines, Check, Clock3, PackageOpen } from "lucide-react";
import type { GenerationJob } from "@/features/video-studio/library";
import { Dialog } from "./studio-primitives";
import { GenerationDetails } from "./generation-details";
import { GenerationProgress, GenerationResumeButton } from "./generation-progress";
import { Notice } from "./studio-content";
import base from "./video-studio.module.css";
import styles from "./generation-details.module.css";

export function GenerationPreview({ job, resuming, submitting, onClose, onResume, onApprove, onReject, onCopy, onUseAvatar, onEdit }: {
  job:GenerationJob; resuming:boolean; submitting:boolean; onClose:()=>void; onResume:()=>void; onApprove:()=>void; onReject:()=>void; onCopy:(text:string)=>void; onUseAvatar?:()=>void; onEdit?:()=>void;
}) {
  return <Dialog title={job.kind === "h3_template" ? "形象预览" : "口播视频"} onClose={onClose}>
    {job.video_url ? <video controls playsInline preload="metadata" src={job.video_url} className={styles.media} /> : <GenerationProgress job={job} />}
    {job.video_url && !["completed", "awaiting_review"].includes(job.status) && <GenerationProgress job={job} />}
    <p className={styles.timestamp}><Clock3 size={12} />{new Date(job.created_at).toLocaleString("zh-CN", {month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false})} 创建</p>
    <GenerationDetails job={job} onCopy={onCopy} />
    {job.handoff_url && <p className={styles.handoffNote}>剪辑材料含文案、配音与原片 · 字幕待对齐</p>}
    {job.status === "awaiting_review" && <Notice>预览人物与动作，确认满意后登记形象。登记按实际服务计费。</Notice>}
    {job.status === "completed" && job.kind === "h3_template" && <Notice>形象已就绪，下一步填写口播文案、选择声音。</Notice>}
    {job.status === "completed" && job.kind === "lipsync" && <Notice>口播已生成，下一步选择模板并添加配图，保留这条视频的原声。</Notice>}
    <footer className={styles.actions}>
      {job.audio_url && <a className={base.outlineButton} href={job.audio_url} download><AudioLines size={14} />下载配音</a>}
      {job.handoff_url && <a className={base.outlineButton} href={job.handoff_url} download title="文案、配音与原片；字幕待音文对齐"><PackageOpen size={14} />剪辑材料</a>}
      {job.can_resume && <GenerationResumeButton job={job} className={base.primaryButton} resuming={resuming} onResume={onResume} />}
      {job.status === "awaiting_review" && <><button type="button" className={base.outlineButton} disabled={submitting} onClick={onReject}>不加入形象库</button><button type="button" className={base.primaryButton} disabled={submitting} onClick={onApprove}><Check size={14} />确认加入（计费）</button></>}
      {job.video_url && <a className={base.outlineButton} href={job.video_url} download><ArrowDownToLine size={14} />下载视频</a>}
      {job.status === "completed" && job.kind === "h3_template" && onUseAvatar && <button type="button" className={base.primaryButton} onClick={onUseAvatar}>使用此形象写口播<ArrowRight size={14} /></button>}
      {job.status === "completed" && job.kind === "lipsync" && onEdit && <button type="button" className={base.primaryButton} onClick={onEdit}>选择模板剪辑<ArrowRight size={14} /></button>}
    </footer>
  </Dialog>;
}
