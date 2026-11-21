"use client";

import { stepStates, type EditingProgress } from "@/features/video-studio/editing-progress";
import styles from "./editing-progress.module.css";

/** The shared 分析口播 → 编排画面 → 生成视频 → 待你确认 line used by planning and render cards. */
export function EditingProgressSteps({ progress }: { progress: EditingProgress }) {
  const live = progress.outcome === "active";
  return <div>
    <ol className={styles.steps} data-outcome={progress.outcome} aria-label="剪辑进度">
      {stepStates(progress).map(step => <li key={step.key} data-state={step.state} aria-current={step.state === "current" ? "step" : undefined}>{step.label}</li>)}
    </ol>
    {progress.detail && <p className={styles.status} role={live ? "status" : undefined}>{progress.detail}{live && "，完成后会自动更新。"}</p>}
  </div>;
}
