"use client";

import { Check } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { GenerationJob } from "@/features/video-studio/library";
import { editingStage, projectSteps, voiceStage, type StepView } from "@/features/video-studio/project-steps";
import styles from "./video-studio.module.css";

const tasksRoute = "/api/v1/video-studio/workspaces/{workspace_id}/editing-tasks" as const;

/** 「① 文案 ② 口播 ③ 剪辑 ④ 成片」for the open project, marked from what it actually has. */
export function ProjectStepBar({ workspaceId, projectId, saved, screen, hasScript, jobs, onGo }: {
  workspaceId: string;
  projectId: string;
  saved: boolean;
  screen: "writing" | "create" | "editing";
  hasScript: boolean;
  jobs: GenerationJob[];
  onGo: (screen: StepView["screen"]) => void;
}) {
  const tasks = useQuery({
    queryKey: ["video-studio", "project-steps", workspaceId, projectId],
    enabled: saved && Boolean(projectId),
    staleTime: 10000,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET(tasksRoute, {
      params: { path: { workspace_id: workspaceId }, query: { project_id: projectId } },
      signal: AbortSignal.any([signal, AbortSignal.timeout(12000)]),
    })),
    refetchInterval: query => {
      const stage = editingStage(query.state.data ?? []);
      return stage === "running" ? 15000 : false;
    },
  });
  const steps = projectSteps({ screen, hasScript, voice: voiceStage(jobs, projectId), editing: editingStage(tasks.data ?? []) });
  return <nav className={styles.projectSteps} aria-label="本项目进度"><ol>{steps.map(step => <li key={step.key} className={styles[`step_${step.state}`]}>
    <button type="button" onClick={() => onGo(step.screen)} aria-current={step.state === "current" ? "step" : undefined}>
      <span className={styles.stepIndex} aria-hidden="true">{step.state === "done" ? <Check size={12} strokeWidth={2.4} /> : step.index}</span>
      <span>{step.label}</span>
      {step.note && <small>{step.note}</small>}
      <span className={styles.srOnly}>{step.state === "done" ? "（已完成）" : step.state === "current" ? "（当前）" : ""}</span>
    </button>
  </li>)}</ol></nav>;
}
