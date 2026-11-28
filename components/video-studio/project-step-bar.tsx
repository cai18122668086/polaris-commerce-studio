"use client";

import Link from "next/link";
import { Check } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { GenerationJob } from "@/features/video-studio/library";
import { stepHref, type FlowContext, type FlowStep } from "@/features/video-studio/flow-params";
import { batchSteps, editingStage, projectSteps, voiceStage, type StepScreen, type StepView } from "@/features/video-studio/project-steps";
import styles from "./video-studio.module.css";

const tasksRoute = "/api/v1/video-studio/workspaces/{workspace_id}/editing-tasks" as const;
const itemsRoute = "/api/v1/video-studio/workspaces/{workspace_id}/work-items" as const;
const FLOW_STEP: Record<StepScreen, FlowStep> = { writing: "writing", create: "voice", editing: "editing", finish: "finish" };

/**
 * 「① 文案 ② 口播 ③ 剪辑 ④ 成片」。带 ?batch= 时按这一批作品条目（C2）算每步完成了几条，
 * 步骤之间的链接一路带着 batch / scripts / project；否则按当前项目算。
 */
export function ProjectStepBar({ flow, workspaceId, projectId, saved, screen, hasScript, jobs, onGo }: {
  flow?: FlowContext;
  workspaceId: string;
  projectId: string;
  saved: boolean;
  screen: StepScreen;
  hasScript: boolean;
  jobs: GenerationJob[];
  onGo: (screen: StepView["screen"]) => void;
}) {
  const batch = flow?.batch ?? null;
  const tasks = useQuery({
    queryKey: ["video-studio", "project-steps", workspaceId, projectId],
    enabled: !batch && saved && Boolean(projectId),
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
  const items = useQuery({
    queryKey: ["video-studio", "work-items", workspaceId, `steps:${batch}`],
    enabled: Boolean(batch),
    staleTime: 10000,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET(itemsRoute, {
      params: { path: { workspace_id: workspaceId }, query: { batch_id: batch!, limit: 50 } },
      signal: AbortSignal.any([signal, AbortSignal.timeout(12000)]),
    })),
    refetchInterval: query => (query.state.data ?? []).some(item => ["queued", "running"].includes(item.status)) ? 15000 : false,
  });
  const steps = batch
    ? batchSteps({ screen, items: items.data ?? [] })
    : projectSteps({ screen, hasScript, voice: voiceStage(jobs, projectId), editing: editingStage(tasks.data ?? []) });
  const context: FlowContext = { ...flow, project: flow?.project ?? (saved ? projectId : null) };
  return <nav className={styles.projectSteps} aria-label={batch ? `本批 ${items.data?.length ?? ""} 条的进度` : "本项目进度"}><ol>{steps.map(step => {
    const inner = <>
      <span className={styles.stepIndex} aria-hidden="true">{step.state === "done" ? <Check size={12} strokeWidth={2.4} /> : step.index}</span>
      <span>{step.label}</span>
      {step.note && <small>{step.note}</small>}
      <span className={styles.srOnly}>{step.state === "done" ? "（已完成）" : step.state === "current" ? "（当前）" : ""}</span>
    </>;
    return <li key={step.key} className={styles[`step_${step.state}`]}>
      {batch
        ? <Link href={stepHref(FLOW_STEP[step.screen], context)} aria-current={step.state === "current" ? "step" : undefined}>{inner}</Link>
        : <button type="button" onClick={() => onGo(step.screen)} aria-current={step.state === "current" ? "step" : undefined}>{inner}</button>}
    </li>;
  })}</ol></nav>;
}
