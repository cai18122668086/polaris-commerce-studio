/**
 * 形象 / 声音 / 固定形象的纯规则（无 React、无网络），抽屉和页面共用，单测直接覆盖。
 */

export type PersonaLike = { id: string; name: string; avatar_id: string; voice_id: string; emotion?: string | null; language?: string | null; available: boolean; created_at: string };

/** 可用的排前面，其余按创建时间新→旧。 */
export function sortPersonas<T extends PersonaLike>(items: T[]): T[] {
  return [...items].sort((a, b) => Number(b.available) - Number(a.available) || b.created_at.localeCompare(a.created_at));
}

/** 选中固定形象时写进口播草稿的字段：同时带出形象和声音（声音参数有才覆盖）。 */
export function personaDraftPatch(persona: PersonaLike): { avatarId: string; voiceId: string; personaId: string; emotion?: string; language?: string } {
  return {
    personaId: persona.id,
    avatarId: persona.avatar_id,
    voiceId: persona.voice_id,
    ...(persona.emotion ? { emotion: persona.emotion } : {}),
    ...(persona.language ? { language: persona.language } : {}),
  };
}

export const PERSONA_NAME_MAX = 30;

/** 固定形象名称校验：返回中文错误，通过返回空串。 */
export function personaNameError(name: string, existing: string[] = []): string {
  const value = name.trim();
  if (!value) return "请给固定形象起个名字";
  if (value.length > PERSONA_NAME_MAX) return `名字最多 ${PERSONA_NAME_MAX} 个字`;
  if (existing.some(item => item.trim() === value)) return "已有同名的固定形象，换个名字吧";
  return "";
}

/** 定制形象任务（h3_template）对商家展示的阶段。 */
export type AvatarPhase = "uploading" | "generating" | "review" | "registering" | "ready" | "failed" | "pending_check" | "unknown";
export function avatarPhase(job: { status: string; stage?: string } | undefined, submitting = false): AvatarPhase {
  if (submitting) return "uploading";
  if (!job) return "unknown";
  if (job.status === "awaiting_review") return "review";
  if (job.status === "completed") return "ready";
  if (["failed", "rejected", "cancelled"].includes(job.status)) return "failed";
  // 重启后可能已提交、但没拿到供应商任务号：结果待确认（只能「查询结果」，绝不重新提交）。
  if (job.status === "unknown") return "pending_check";
  if (["queued", "running", "awaiting_resume"].includes(job.status)) return /model_submitting|regist/.test(job.stage || "") ? "registering" : "generating";
  return "unknown";
}
export const AVATAR_PHASE_COPY: Record<AvatarPhase, { title: string; detail: string }> = {
  uploading: { title: "正在上传素材", detail: "请保持页面打开，上传完成后即可关闭抽屉，进度会保留。" },
  generating: { title: "正在生成形象动作", detail: "通常需要 3～8 分钟。可以先关闭抽屉继续配置其他稿件，完成后会出现在「我的形象」。" },
  review: { title: "动作已生成，请预览确认", detail: "满意后确认加入形象库；不满意可以放弃，重新上传。" },
  registering: { title: "正在加入形象库", detail: "确认已提交，稍等片刻即可使用。" },
  ready: { title: "形象已就绪", detail: "已加入「我的形象」，口播时可以直接选用。" },
  failed: { title: "这次没有生成成功", detail: "未完成的步骤不会扣费。可换一张更清晰的正面照片重试。" },
  pending_check: { title: "结果待确认", detail: "这条的提交结果还在确认：不会重新生成，也不会重复扣积分。可以点「查询结果」重新核对。" },
  unknown: { title: "状态待确认", detail: "正在核对进度，请稍后在「我的形象」查看。" },
};

/** 声音克隆开关：配置关闭时入口可见但不发任何请求。 */
export function voiceCloneGate(config: { available?: boolean } | undefined, loaded: boolean): { open: boolean; title: string; detail: string } {
  if (!loaded) return { open: false, title: "正在读取", detail: "" };
  if (config?.available) return { open: true, title: "", detail: "" };
  return { open: false, title: "声音克隆暂未开通", detail: "这项能力正在准备中，开通后可以用一段本人录音克隆专属声音。现在可以先用系统声音，效果同样自然。" };
}

/** 形象卡上的状态标签（我的形象分区）。 */
export function ownAvatarStatus(avatar: { ready: boolean }, job?: { status: string }): { label: string; tone: "ready" | "busy" | "review" | "failed" } {
  if (avatar.ready) return { label: "可使用", tone: "ready" };
  const phase = avatarPhase(job);
  if (phase === "review") return { label: "待确认", tone: "review" };
  if (phase === "failed") return { label: "未成功", tone: "failed" };
  if (phase === "pending_check") return { label: "结果待确认", tone: "review" };
  if (phase === "generating" || phase === "registering") return { label: "定制中", tone: "busy" };
  return { label: "待生成动作", tone: "review" };
}

/** 「结果待确认」的形象任务才给「查询结果」；不要对它调 /resume（会重新冻结积分）。 */
export function canCheckAvatarJob(job: { status: string; kind?: string } | undefined): boolean {
  return !!job && job.status === "unknown";
}

/** 声音库里的「克隆新声音」入口（与口播页 B15 同一处理）：没开通时置灰、说明原因，点了不打开表单。 */
export function cloneEntry(config?: { available?: boolean } | null): { available: boolean; label: string; hint: string } {
  return config?.available === true
    ? { available: true, label: "克隆新声音", hint: "" }
    : { available: false, label: "克隆新声音（暂未开通）", hint: "声音克隆暂未开通，可以先用系统声音" };
}
