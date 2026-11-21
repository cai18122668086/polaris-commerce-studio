export type StepKey = "writing" | "voice" | "editing" | "final";
export type StepState = "done" | "current" | "todo";
export type StepView = { key: StepKey; index: number; label: string; state: StepState; note?: string; screen: "writing" | "create" | "editing" | "works" };

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

const SCREEN_STEP: Record<"writing" | "create" | "editing", StepKey> = { writing: "writing", create: "voice", editing: "editing" };

/** The four steps of one project, marked from what the project actually has, with the open page as current. */
export function projectSteps(input: { screen: "writing" | "create" | "editing"; hasScript: boolean; voice: VoiceStage; editing: EditingStage }): StepView[] {
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
  const steps: Omit<StepView, "state" | "note">[] = [
    { key: "writing", index: 1, label: "文案", screen: "writing" },
    { key: "voice", index: 2, label: "口播", screen: "create" },
    { key: "editing", index: 3, label: "剪辑", screen: "editing" },
    { key: "final", index: 4, label: "成片", screen: "works" },
  ];
  return steps.map(step => ({ ...step, state: step.key === current ? "current" : done[step.key] ? "done" : "todo", note: notes[step.key] }));
}
