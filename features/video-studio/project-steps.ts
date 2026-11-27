export type StepKey = "writing" | "voice" | "editing" | "final";
export type StepState = "done" | "current" | "todo";
export type StepScreen = "writing" | "create" | "editing" | "finish";
export type StepView = { key: StepKey; index: number; label: string; state: StepState; note?: string; screen: StepScreen };

type JobLike = { kind: string; project_id: string | null; status: string };
type EditingTaskLike = { status: string; options?: { mode?: string } | null; artifacts?: { role: string }[] };

export type VoiceStage = "none" | "running" | "done";
export type EditingStage = "none" | "running" | "review" | "done";

const RUNNING = new Set(["queued", "running", "submitted", "processing", "unknown", "awaiting_result"]);

/** 口播 stage of one project: any finished lip-sync job counts; otherwise one still in flight. */
export function voiceStage(jobs: JobLike[], projectId: string): VoiceStage {
  const own = jobs.filter(job => job.kind === "lipsync" && job.project_id === projectId);
  if (own.some(job => job.status === "completed")) return "done";
  if (own.some(job => RUNNING.has(job.status))) return "running";
  return "none";
}

/** 剪辑 stage: transcript-only preparation tasks are not edits; a confirmed final means 成片. */
export function editingStage(tasks: EditingTaskLike[]): EditingStage {
  const edits = tasks.filter(task => task.options?.mode !== "transcript");
  if (edits.some(task => task.status === "completed" && task.artifacts?.some(a => a.role === "final"))) return "done";
  if (edits.some(task => task.status === "awaiting_review")) return "review";
  if (edits.some(task => task.status === "queued" || task.status === "running")) return "running";
  return "none";
}

const STEPS: Omit<StepView, "state" | "note">[] = [
  { key: "writing", index: 1, label: "文案", screen: "writing" },
  { key: "voice", index: 2, label: "口播", screen: "create" },
  { key: "editing", index: 3, label: "剪辑", screen: "editing" },
  { key: "final", index: 4, label: "成片", screen: "finish" },
];

const SCREEN_STEP: Record<StepScreen, StepKey> = { writing: "writing", create: "voice", editing: "editing", finish: "final" };

/** The four steps of one project, marked from what the project actually has, with the open page as current. */
export function projectSteps(input: { screen: StepScreen; hasScript: boolean; voice: VoiceStage; editing: EditingStage }): StepView[] {
  const current = SCREEN_STEP[input.screen];
  const done: Record<StepKey, boolean> = {
    writing: input.hasScript,
    voice: input.voice === "done",
    editing: input.editing === "done" || input.editing === "review",
    final: input.editing === "done",
  };
  const notes: Partial<Record<StepKey, string>> = {
    ...(input.voice === "running" ? { voice: "生成中" } : {}),
    ...(input.editing === "running" ? { editing: "剪辑中" } : {}),
    ...(input.editing === "review" ? { final: "待确认" } : {}),
  };
  return STEPS.map(step => ({ ...step, state: step.key === current ? "current" : done[step.key] ? "done" : "todo", note: notes[step.key] }));
}

type BatchItem = { stage: string; status: string; generation_task_id?: string | null; source_video_ref?: unknown };
const AFTER: Record<string, number> = { talking: 0, editing: 1, finishing: 2, done: 3 };

/**
 * The four steps of one work batch (contract C2), with the open page as current:
 * a step is done when every item is past it; while some are, the note says how many.
 */
export function batchSteps(input: { screen: StepScreen; items: BatchItem[] }): StepView[] {
  const current = SCREEN_STEP[input.screen];
  const total = input.items.length;
  const past = (stage: number) => input.items.filter(item => (AFTER[item.stage] ?? 0) > stage
    || ((AFTER[item.stage] ?? 0) === stage && item.status === "succeeded")).length;
  const counts: Record<StepKey, number> = { writing: total, voice: past(0), editing: past(1), final: input.items.filter(item => item.stage === "done").length };
  const active = (stage: string) => input.items.filter(item => item.stage === stage && ["queued", "running"].includes(item.status)).length;
  const failed = (stage: string) => input.items.filter(item => item.stage === stage && item.status === "failed").length;
  const notes: Partial<Record<StepKey, string>> = {};
  for (const [key, stage] of [["voice", "talking"], ["editing", "editing"]] as const) {
    if (failed(stage)) notes[key] = `${failed(stage)} 条未完成`;
    else if (active(stage)) notes[key] = `${counts[key]}/${total}`;
  }
  const waiting = input.items.filter(item => item.stage === "finishing").length;
  if (waiting && counts.final) notes.final = `${counts.final}/${total}`;
  else if (waiting) notes.final = "待成片";
  return STEPS.map(step => ({
    ...step,
    state: step.key === current ? "current" : total > 0 && counts[step.key] === total ? "done" : "todo",
    note: notes[step.key],
  }));
}
