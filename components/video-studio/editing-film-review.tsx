"use client";

import { useState } from "react";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/openapi";
import { unwrapApiResponse } from "@/lib/api/request";
import { editingMessage } from "@/features/video-studio/editing-presentation";
import styles from "./editing-workspace.module.css";

type Assessment = components["schemas"]["EditingFilmAssessment"];
type Task = components["schemas"]["EditingTaskResponse"];
type Artifact = components["schemas"]["EditingArtifactResponse"];

const dimensions = [
  ["semantic", "口播与动效语义"],
  ["timing", "字幕与动作时序"],
  ["visual", "画面与人物"],
  ["listening", "原声、音效与配乐"],
] as const;
const empty: Assessment = {
  semantic: "unreviewed", timing: "unreviewed", visual: "unreviewed", listening: "unreviewed", note: "",
};

export function EditingFilmReview({ workspaceId, task, final }: {
  workspaceId: string;
  task: Task;
  final: Artifact;
}) {
  const [draft, setDraft] = useState<{ assessment: Assessment; revision: number }>();
  const [acknowledged, setAcknowledged] = useState<Task>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const current = acknowledged && acknowledged.revision > task.revision ? acknowledged : task;
  const review = current.manual_review;
  const saved = review?.assessment ?? empty;
  const assessment = draft?.assessment ?? saved;
  const changed = assessment.note !== saved.note || dimensions.some(([key]) => assessment[key] !== saved[key]);
  const stale = draft && changed && draft.revision !== current.revision;

  const edit = (patch: Partial<Assessment>) => {
    setError("");
    setDraft({
      assessment: { ...assessment, ...patch },
      revision: changed && draft ? draft.revision : current.revision,
    });
  };
  const save = async () => {
    if (busy || !draft || !changed || stale) return;
    setBusy(true);
    setError("");
    try {
      const result = unwrapApiResponse(await apiClient.PUT(
        "/api/v1/video-studio/workspaces/{workspace_id}/editing-tasks/{task_id}/review",
        {
          params: { path: { workspace_id: workspaceId, task_id: task.id } },
          body: {
            final_artifact_id: final.id,
            final_sha256: final.sha256,
            expected_revision: draft.revision,
            assessment,
          },
          signal: AbortSignal.timeout(12000),
        },
      ));
      setAcknowledged(result);
      setDraft(undefined);
    } catch (caught) {
      setError(editingMessage(caught, "验收保存结果暂未确认，请重试。"));
    } finally {
      setBusy(false);
    }
  };

  return <details className={styles.filmReview}>
    <summary>成片人工验收 · {review ? "已记录" : "待验收"}</summary>
    <fieldset className={styles.correction} disabled={busy}>
      <legend>核对本版高清成片</legend>
      <p className={styles.note}>请在实播后分别记录四项。可在备注里写明问题的秒数。</p>
      {dimensions.map(([key, label]) => <label key={key}>{label}
        <select value={assessment[key]} onChange={event => edit({ [key]: event.target.value as Assessment[typeof key] })}>
          <option value="unreviewed">待验收</option>
          <option value="accepted">通过</option>
          <option value="needs_changes">需调整</option>
        </select>
      </label>)}
      <label>验收备注<textarea rows={2} maxLength={1000} value={assessment.note}
        onChange={event => edit({ note: event.target.value })} /></label>
      {stale && <p role="alert">此成片的验收记录已更新。请载入最新记录再修改。
        <button type="button" onClick={() => { setDraft(undefined); setError(""); }}>载入最新记录</button>
      </p>}
      <button type="button" disabled={!changed || !!stale} onClick={() => void save()}>
        {busy ? "正在保存" : "保存人工验收"}
      </button>
      {review && <p className={styles.note}>已保存 · {new Date(review.recorded_at).toLocaleString("zh-CN")}</p>}
      {error && changed && <p className={styles.error} role="alert">{error}</p>}
    </fieldset>
  </details>;
}
