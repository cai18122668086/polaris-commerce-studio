/**
 * 口播面板（v3）的纯逻辑：草稿结构、每条稿的数字人/音色、生成请求体、汇总估算、
 * 本页草稿的 sessionStorage 编解码。不依赖 React，node --test 直接测。
 *
 * 一条稿 = 一个作品条目（契约 C2 work item）。批次由后端按条目并行生成。
 */

import { scriptStats } from "./script-library-format";

export type TalkingDrive = "text" | "audio";
export type AssignMode = "same" | "each";

/** 第 ① 步里的一条稿：来自文案库、手动输入，或一段上传的音频。 */
export type TalkingScript = {
  key: string;
  source: "library" | "manual" | "audio";
  documentId?: string;
  title: string;
  body: string;
  script: string;
  audioId?: string;
  audioName?: string;
  audioSeconds?: number;
  /** 文案库接口给的字数与时长（全站同一口径）；手动输入的稿没有，现算。 */
  chars?: number;
  seconds?: number;
};

/** 一条稿的出镜设置。personaId 有值时 avatarId/voiceId 来自固定形象。 */
export type Assignment = { personaId?: string; avatarId?: string; voiceId?: string };

export type TalkingDraft = {
  version: 1;
  drive: TalkingDrive;
  scripts: TalkingScript[];
  mode: AssignMode;
  shared: Assignment;
  perScript: Record<string, Assignment>;
  step: 1 | 2 | 3 | 4;
  /** 本次生成的提交编号：同一份设置重复点生成都用它，后端据此只建一个批次。 */
  requestId?: string;
};

export type Persona = { id: string; name: string; avatar_id: string; voice_id: string; available?: boolean };

export { CHARS_PER_SECOND } from "./script-library-format";
export const MAX_SCRIPTS = 20;
export const PARALLEL_LIMIT = 4;
/** 一条口播从提交到出片的大致分钟数（含配音与口型驱动），用于给商家一个心理预期。 */
export const MINUTES_PER_ROUND: [number, number] = [3, 6];

export const emptyDraft = (): TalkingDraft => ({ version: 1, drive: "text", scripts: [], mode: "same", shared: {}, perScript: {}, step: 1 });

/** 字数和时长与文案库同一口径：库里的稿用接口返回的 script_chars / script_seconds，手动输入的用 scriptStats。 */
export function scriptChars(script: Pick<TalkingScript, "script" | "chars">): number {
  return script.chars ?? scriptStats(script.script).chars;
}

export function scriptSeconds(script: Pick<TalkingScript, "script" | "audioSeconds" | "seconds">): number {
  if (script.audioSeconds) return Math.round(script.audioSeconds);
  return script.seconds ?? Math.max(1, scriptStats(script.script).seconds);
}

export function durationLabel(seconds: number): string {
  const value = Math.max(0, Math.round(seconds));
  return value < 60 ? `${value} 秒` : `${Math.floor(value / 60)} 分 ${value % 60 ? `${value % 60} 秒` : ""}`.trim();
}

export function displayTitle(script: TalkingScript): string {
  const title = script.title.trim();
  if (title) return title;
  if (script.audioName) return script.audioName;
  const first = script.script.trim().split(/[。！？!?\n]/)[0] || script.script.trim();
  return first.length > 18 ? `${first.slice(0, 18)}…` : first || "未命名口播";
}

export function assignmentFor(draft: TalkingDraft, key: string): Assignment {
  return draft.mode === "same" ? draft.shared : draft.perScript[key] ?? {};
}

/** 选固定形象：形象和声音一起带入。 */
export function withPersona(persona: Persona): Assignment {
  return { personaId: persona.id, avatarId: persona.avatar_id, voiceId: persona.voice_id };
}

/** 换数字人：不再是固定形象；声音保留（固定形象带入的声音也保留，用户可再换）。 */
export function withAvatar(current: Assignment, avatarId: string): Assignment {
  return { avatarId, voiceId: current.voiceId };
}

export function withVoice(current: Assignment, voiceId: string): Assignment {
  return { ...current, voiceId };
}

/** 声音是否就是固定形象带入的那一个（第 ③ 步显示「已随固定形象带入，可更换」）。 */
export function voiceFromPersona(assignment: Assignment, personas: Persona[]): boolean {
  const persona = personas.find(item => item.id === assignment.personaId);
  return !!persona && persona.voice_id === assignment.voiceId;
}

/** 改某条或全部的设置。切到「每条单独选」时，用统一设置给还没单独选过的稿打底。 */
export function assign(draft: TalkingDraft, key: string | "all", next: (current: Assignment) => Assignment): TalkingDraft {
  if (draft.mode === "same" || key === "all") {
    if (draft.mode === "same") return { ...draft, shared: next(draft.shared) };
    const perScript = Object.fromEntries(draft.scripts.map(script => [script.key, next(assignmentFor(draft, script.key))]));
    return { ...draft, perScript };
  }
  return { ...draft, perScript: { ...draft.perScript, [key]: next(assignmentFor(draft, key)) } };
}

export function switchMode(draft: TalkingDraft, mode: AssignMode): TalkingDraft {
  if (mode === draft.mode) return draft;
  if (mode === "each") {
    const perScript = Object.fromEntries(draft.scripts.map(script => [script.key, draft.perScript[script.key]?.avatarId ? draft.perScript[script.key] : { ...draft.shared }]));
    return { ...draft, mode, perScript };
  }
  return { ...draft, mode };
}

export function addScripts(draft: TalkingDraft, scripts: TalkingScript[]): TalkingDraft {
  const known = new Set(draft.scripts.map(script => script.documentId ? `doc:${script.documentId}` : script.key));
  const fresh = scripts.filter(script => !known.has(script.documentId ? `doc:${script.documentId}` : script.key));
  const drive: TalkingDrive = fresh[0]?.source === "audio" ? "audio" : draft.drive;
  return { ...draft, drive, scripts: [...draft.scripts, ...fresh].slice(0, MAX_SCRIPTS), requestId: undefined };
}

export function removeScript(draft: TalkingDraft, key: string): TalkingDraft {
  const perScript = { ...draft.perScript };
  delete perScript[key];
  return { ...draft, scripts: draft.scripts.filter(script => script.key !== key), perScript, requestId: undefined };
}

export function switchDrive(draft: TalkingDraft, drive: TalkingDrive): TalkingDraft {
  if (drive === draft.drive) return draft;
  // 文本稿和音频不能混在一个批次里：换驱动方式时只保留对应类型的条目。
  const scripts = draft.scripts.filter(script => drive === "audio" ? script.source === "audio" : script.source !== "audio");
  return { ...draft, drive, scripts, step: 1, requestId: undefined };
}

export type StepProblem = { step: 1 | 2 | 3; text: string };

/** 每一步还缺什么。没有问题才能生成。 */
export function problems(draft: TalkingDraft, catalog: { avatarIds: Set<string>; voiceIds: Set<string> }): StepProblem[] {
  const list: StepProblem[] = [];
  if (!draft.scripts.length) list.push({ step: 1, text: draft.drive === "audio" ? "请上传至少一段音频" : "请至少选择或输入一条口播稿" });
  if (draft.drive === "text" && draft.scripts.some(script => !script.script.trim())) list.push({ step: 1, text: "有一条稿是空的" });
  if (draft.drive === "audio" && draft.scripts.some(script => !script.audioId)) list.push({ step: 1, text: "音频还在上传" });
  const rows = draft.scripts.map(script => assignmentFor(draft, script.key));
  const noAvatar = rows.filter(row => !row.avatarId || !catalog.avatarIds.has(row.avatarId)).length;
  if (draft.scripts.length && noAvatar) list.push({ step: 2, text: draft.mode === "same" ? "请选择数字人" : `还有 ${noAvatar} 条没选数字人` });
  if (draft.drive === "text") {
    const noVoice = rows.filter(row => !row.voiceId || !catalog.voiceIds.has(row.voiceId)).length;
    if (draft.scripts.length && noVoice) list.push({ step: 3, text: draft.mode === "same" ? "请选择音色" : `还有 ${noVoice} 条没选音色` });
  }
  return list;
}

/** POST /work-batches 的 items：每条稿一个条目，「所有稿同一个」时每条都带上同一组设置。 */
export function batchItems(draft: TalkingDraft) {
  return draft.scripts.map(script => {
    const row = assignmentFor(draft, script.key);
    return {
      drive_mode: draft.drive,
      script_document_id: script.documentId ?? null,
      publish_title: script.title.trim().slice(0, 80),
      publish_body: script.body.slice(0, 2000),
      script_text: draft.drive === "text" ? script.script.trim() : "",
      persona_id: row.personaId ?? null,
      avatar_id: row.avatarId ?? null,
      voice_id: draft.drive === "text" ? row.voiceId ?? null : null,
      audio_file_id: draft.drive === "audio" ? script.audioId ?? null : null,
    };
  });
}

/** 汇总：共 N 条 · 预计积分 · 预计耗时（并行 4 条一轮）。price 为 null 表示未配置价格。 */
export function summary(draft: TalkingDraft, price: number | null) {
  const count = draft.scripts.length;
  const rounds = Math.max(1, Math.ceil(count / PARALLEL_LIMIT));
  const seconds = draft.scripts.reduce((sum, script) => sum + scriptSeconds(script), 0);
  const presenters = new Set(draft.scripts.map(script => assignmentFor(draft, script.key).avatarId).filter(Boolean)).size;
  return {
    count,
    credits: price === null ? null : price * count,
    minutes: [MINUTES_PER_ROUND[0] * rounds, MINUTES_PER_ROUND[1] * rounds] as [number, number],
    seconds,
    presenters,
    queued: Math.max(0, count - PARALLEL_LIMIT),
  };
}

// ---- 草稿保存（sessionStorage）：打开定制抽屉/去形象库再回来，多条稿设置不丢 ----

export const draftKey = (userId: string, workspaceId: string) => `polaris-video-talking-draft:${userId}:${workspaceId}`;

export function encodeDraft(draft: TalkingDraft): string {
  return JSON.stringify(draft);
}

export function decodeDraft(raw: string | null): TalkingDraft | undefined {
  if (!raw) return undefined;
  try {
    const value = JSON.parse(raw) as Partial<TalkingDraft>;
    if (value?.version !== 1 || !Array.isArray(value.scripts) || !["text", "audio"].includes(value.drive as string) || !["same", "each"].includes(value.mode as string)) return undefined;
    const scripts = value.scripts.filter((script): script is TalkingScript => !!script && typeof script.key === "string" && typeof script.script === "string").slice(0, MAX_SCRIPTS);
    const step = [1, 2, 3, 4].includes(value.step as number) ? value.step as TalkingDraft["step"] : 1;
    return { version: 1, drive: value.drive as TalkingDrive, mode: value.mode as AssignMode, scripts, shared: value.shared ?? {}, perScript: value.perScript ?? {}, step, requestId: typeof value.requestId === "string" ? value.requestId : undefined };
  } catch {
    return undefined;
  }
}

// ---- 结果区：后端批次视图 → 每个结果框 ----

export type WorkItemView = {
  id: string; position: number; status: "pending" | "queued" | "running" | "succeeded" | "failed" | "canceled";
  error: string | null; publish_title: string; script_text: string; avatar_id: string | null; voice_id: string | null;
  persona_id: string | null; generation_task_id: string | null; drive_mode: string; stage: string; version: number;
};
export type TalkingView = { item_id: string; queue_position: number | null; stage: string | null; video_url: string | null; can_retry: boolean; awaiting_check?: boolean };
export type TalkingBatch = { batch: { id: string; created_at: string; item_ids: string[]; items: WorkItemView[]; status_counts: Record<string, number> }; talking: TalkingView[]; parallel_limit: number; notice?: string | null };

export type ResultBox = { id: string; title: string; state: "queued" | "running" | "done" | "failed" | "checking"; label: string; videoUrl: string | null; canRetry: boolean; canCheck: boolean; error: string | null; position: number };

export function resultBoxes(view: TalkingBatch, stageLabel: (stage: string) => string): ResultBox[] {
  const talking = new Map(view.talking.map(item => [item.item_id, item]));
  return view.batch.items.map(item => {
    const extra = talking.get(item.id);
    const title = item.publish_title || (item.script_text.trim().split(/[。！？!?\n]/)[0] || "口播").slice(0, 18);
    const base = { id: item.id, title, videoUrl: extra?.video_url ?? null, canRetry: !!extra?.can_retry, canCheck: !!extra?.awaiting_check, error: item.error, position: item.position };
    if (extra?.awaiting_check) return { ...base, state: "checking", label: "结果待确认" };
    if (item.status === "succeeded") return { ...base, state: "done", label: "已完成" };
    if (item.status === "failed" || item.status === "canceled") return { ...base, state: "failed", label: "生成失败" };
    if (item.status === "running" || (item.status === "queued" && item.generation_task_id)) return { ...base, state: "running", label: extra?.stage ? stageLabel(extra.stage) : "正在生成" };
    return { ...base, state: "queued", label: extra?.queue_position ? `排队中 · 第 ${extra.queue_position} 位` : "排队中" };
  });
}

export function batchSettled(view: TalkingBatch): boolean {
  return view.batch.items.every(item => ["succeeded", "failed", "canceled"].includes(item.status)) && !view.talking.some(item => item.awaiting_check);
}


/** 主按钮：全部结束前只剪已完成的，并说明其余条完成后还能加入。 */
export function editingCta(boxes: Pick<ResultBox, "state">[], settled: boolean) {
  const done = boxes.filter(box => box.state === "done").length;
  const open = boxes.filter(box => box.state === "queued" || box.state === "running" || box.state === "checking").length;
  if (!settled && open && done) return { label: `先剪已完成的 ${done} 条`, note: `其余 ${open} 条完成后可继续加入`, disabled: false };
  if (!done) return { label: `去剪辑这 ${boxes.length} 条`, note: open ? "完成后就能去剪辑" : "", disabled: true };
  return { label: `去剪辑这 ${done} 条`, note: "", disabled: false };
}
