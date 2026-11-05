"use client";

import { useEffect, useState } from "react";
import { AudioLines, Check, CircleAlert } from "lucide-react";
import type { UploadProgress } from "@/lib/api/upload";
import { estimatedVoiceProgress } from "@/features/video-studio/voice-progress";
import styles from "./voice-cloning.module.css";

export function VoiceProgress({ status, upload, startedAt, preview = false, compact = false }: { status: string; upload?: UploadProgress; startedAt?: number; preview?: boolean; compact?: boolean }) {
  const [elapsed, setElapsed] = useState(() => startedAt ? Math.max(0, Math.floor((Date.now() - startedAt) / 1000)) : 0);
  const [mountedAt] = useState(() => Date.now());
  const beganAt = startedAt ?? mountedAt;
  const done = status === "ready";
  const stopped = status === "unknown" || status === "failed";
  useEffect(() => {
    if (done || stopped) return;
    const timer = setInterval(() => setElapsed(Math.max(0, Math.floor((Date.now() - beganAt) / 1000))), 1000);
    return () => clearInterval(timer);
  }, [beganAt, done, stopped]);
  const uploadPercent = upload?.total ? Math.min(100, Math.floor(upload.loaded / upload.total * 100)) : undefined;
  const percent = done ? 100 : stopped ? undefined : status === "uploading" ? uploadPercent === undefined ? undefined : Math.floor(uploadPercent / 4) : estimatedVoiceProgress(elapsed);
  const title = preview ? done ? "试听已就绪" : "正在生成试听" : ({ uploading: "正在上传录音", validating: "正在检查录音", queued: "正在准备声音", submitting: "正在创建声音", processing: "正在创建声音", ready: "你的声音，准备好了", failed: "换一段录音再试试", unknown: "声音结果待确认" }[status] || "正在更新进度");
  const hint = stopped ? status === "failed" ? "请使用清晰、单人说话的录音。" : "稍后查询原任务，无需重新上传。" : done ? "先听听效果，再为视频配音。" : status === "uploading" || status === "validating" ? "请保持窗口打开，录音很快就准备好。" : elapsed >= 45 ? "处理时间稍长，完成后会自动更新。" : "完成后，可在“我的声音”中查看。";
  return <section className={`${styles.progressPanel} ${compact ? styles.progressCompact : ""}`} data-state={done ? "done" : stopped ? "stopped" : "running"} aria-label={preview ? "试听生成进度" : "声音创建进度"} aria-busy={!done && !stopped}>
    {!compact && <div className={styles.progressMark}>{done ? <Check size={27} /> : stopped ? <CircleAlert size={27} /> : <AudioLines size={28} />}</div>}
    <div className={styles.progressHeading}><h3>{title}</h3><span>{done ? "100%" : stopped ? "" : status === "uploading" ? uploadPercent === undefined ? "上传中" : `${uploadPercent}%` : `预计 ${percent}%`}</span></div>
    {!stopped && <progress className={styles.progressBar} aria-label={preview ? "试听生成进度" : "声音创建进度"} max={100} value={percent} />}
    <p role="status">{hint}</p>
  </section>;
}
