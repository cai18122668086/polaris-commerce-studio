"use client";

import { ArrowDownToLine, Play } from "lucide-react";
import type { GenerationJob, VideoAvatar } from "@/features/video-studio/library";
import { GenerationImageStatus, GenerationProgress } from "./generation-progress";
import { generationProgress } from "@/features/video-studio/generation-progress";
import styles from "./video-studio.module.css";

export function GenerationWorkCard({ job, avatar, onPreview, onResume }: { job: GenerationJob; avatar: VideoAvatar; onPreview: () => void; onResume: () => void }) {
  const state = generationProgress(job);
  return <article className={styles.workCard}>
    <button type="button" className={styles.workImage} onClick={onPreview} aria-label={`${state.done ? "预览" : "查看进度"}：${job.snapshot?.draft.name || avatar.name}`}>
      {avatar.cover_url && <img src={avatar.cover_url} alt={avatar.name} />}
      <span>{job.kind === "h3_template" ? "我的形象" : "口播视频"}</span>
      <GenerationImageStatus job={job} />
      {state.done && <i><Play size={21} /></i>}
    </button>
    <div><b>{job.snapshot?.draft.name || avatar.name}</b><time>{new Date(job.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</time>
      <GenerationProgress job={job} compact />
      <div className={styles.workActions}>
        <button className={styles.textButton} type="button" onClick={job.can_resume ? onResume : onPreview}>{job.can_resume ? "继续处理" : state.review ? "预览并确认" : state.done ? "查看视频" : "查看进度"}</button>
        {job.video_url && <a className={styles.textButton} href={job.video_url} download aria-label="下载视频"><ArrowDownToLine size={14} />下载</a>}
      </div>
    </div>
  </article>;
}
