/**
 * 批量剪辑（四步：选视频 → 选模板 → 补充素材 → 生成）的纯函数：
 * 候选视频、建批次的请求体、结果框的阶段文案、汇总与完成判断。不依赖 React，可直接 node --test。
 */

export type CandidateKind = "talking" | "library" | "upload";

/** 一条可以剪的视频（来自口播批次 / 视频库 / 刚上传的文件）。 */
export type EditingCandidate = {
  /** 选择列表里的唯一键：`${kind}:${refId}` */
  key: string;
  kind: CandidateKind;
  /** 口播任务 id（talking / 视频库里的口播结果）或已上传原片 id（upload / 视频库里的上传视频） */
  refId: string;
  /** 来自口播批次时的作品条目 id */
  itemId?: string;
  batchId?: string;
  projectId: string | null;
  title: string;
  videoUrl: string | null;
  durationMs?: number | null;
  createdAt?: string;
  /** 口播批次里还没生成完或失败的条目不可选 */
  ready: boolean;
  note?: string;
};

export const candidateKey = (kind: CandidateKind, refId: string) => `${kind}:${refId}`;

export const SOURCE_LABEL: Record<CandidateKind, string> = { talking: "口播批次", library: "视频库", upload: "上传" };

export function durationLabel(ms?: number | null): string {
  if (!ms || ms <= 0) return "";
  const seconds = Math.round(ms / 1000);
  return seconds >= 60 ? `${Math.floor(seconds / 60)}分${String(seconds % 60).padStart(2, "0")}秒` : `${seconds}秒`;
}

/**
 * 选中的视频怎样进入剪辑：全部来自同一个口播批次 → 直接剪这个批次里选中的条目；
 * 否则（视频库 / 上传 / 混选）新建一个「直接剪辑」批次，每条视频一条作品条目（drive_mode=uploaded_video）。
 */
export function batchPlan(selected: EditingCandidate[]):
  | { kind: "existing"; batchId: string; itemIds: string[] }
  | { kind: "create"; items: { drive_mode: "uploaded_video"; source_video_ref: { kind: "library" | "upload"; id: string }; publish_title: string; publish_body: string; script_text: string }[] }
  | { kind: "conflict"; reason: string }
  | { kind: "empty" } {
  const usable = selected.filter(row => row.ready);
  if (!usable.length) return { kind: "empty" };
  const talking = usable.filter(row => row.kind === "talking" && row.batchId && row.itemId);
  const batches = new Set(talking.map(row => row.batchId));
  if (talking.length === usable.length && batches.size === 1) {
    return { kind: "existing", batchId: usable[0].batchId as string, itemIds: usable.map(row => row.itemId as string) };
  }
  // 口播批次里的视频必须沿用原条目（标题、正文、口播稿在条目上），不能和别的视频混成新批次。
  if (talking.length) {
    return { kind: "conflict", reason: batches.size > 1
      ? "选中的视频来自不同的口播批次。一次剪一批，请只保留同一批的视频。"
      : "口播批次里的视频要和本批一起剪，才能带上标题和正文。请把视频库或上传的视频分开另剪一批。" };
  }
  return {
    kind: "create",
    items: usable.map(row => ({
      drive_mode: "uploaded_video" as const,
      source_video_ref: { kind: row.kind === "upload" ? "upload" as const : "library" as const, id: row.refId },
      publish_title: row.title.slice(0, 60),
      publish_body: "",
      script_text: "",
    })),
  };
}

export type ItemPhase = "queued" | "transcribing" | "preparing" | "planning" | "rendering" | "done" | "failed";
export type EditingItemState = {
  item_id: string;
  position: number;
  phase?: string | null;
  queue_position?: number | null;
  estimate_minutes?: number | null;
  error?: string | null;
  can_retry?: boolean;
  waiting_for_source?: boolean;
};

const STEPS: { phase: ItemPhase; label: string }[] = [
  { phase: "transcribing", label: "识别口播" },
  { phase: "preparing", label: "检查素材" },
  { phase: "planning", label: "编排画面" },
  { phase: "rendering", label: "生成视频" },
];

/** 结果框：一句状态 + 四段进度（已完成段数）。说真话：排队按全站顺序估算。 */
export function itemStatus(state: EditingItemState): { label: string; detail: string; done: number; tone: "wait" | "work" | "ok" | "bad" } {
  const phase = state.phase as ItemPhase | undefined;
  if (!phase) {
    return state.waiting_for_source
      ? { label: "口播未完成", detail: "口播生成完后才能剪", done: 0, tone: "wait" }
      : { label: "未加入", detail: "这条没有加入本次剪辑", done: 0, tone: "wait" };
  }
  if (phase === "queued") {
    const minutes = state.estimate_minutes;
    return {
      label: state.queue_position ? `排队中 · 第 ${state.queue_position} 位` : "排队中",
      detail: minutes ? `剪辑服务全站按顺序处理，预计 ${minutes} 分钟内完成` : "前面的视频完成后自动开始",
      done: 0,
      tone: "wait",
    };
  }
  if (phase === "done") return { label: "已完成", detail: "可以播放、下载，或去成片", done: 4, tone: "ok" };
  if (phase === "failed") return { label: "未完成", detail: state.error || "这条没有剪成功，可以单独重试", done: 0, tone: "bad" };
  const index = STEPS.findIndex(step => step.phase === phase);
  return { label: `${STEPS[index]?.label ?? "处理中"}中`, detail: index === 2 ? "按口播内容安排字幕、花字和动效" : index === 3 ? "渲染完成后自动导出高清" : "", done: Math.max(0, index), tone: "work" };
}

export const PROGRESS_LABELS = STEPS.map(step => step.label);

/** 全部条目都结束（完成或失败）且至少有一条完成：可以「去成片」。 */
export function batchFinished(states: EditingItemState[]): { finished: boolean; done: number; failed: number; active: number } {
  const joined = states.filter(state => state.phase);
  const done = joined.filter(state => state.phase === "done").length;
  const failed = joined.filter(state => state.phase === "failed").length;
  const active = joined.length - done - failed;
  return { finished: joined.length > 0 && active === 0 && done > 0, done, failed, active };
}

/** ④ 生成前的汇总：条数、积分（编排 + 出片，每条）、耗时（全站单通道串行，每条约 6 分钟）。 */
export function generationSummary(count: number, perItemCredits: number | null | undefined, minutesPerItem = 6): { credits: string; time: string } {
  const credits = typeof perItemCredits === "number" ? `预计 ${(perItemCredits * count).toLocaleString("zh-CN")} 积分（每条 ${perItemCredits}）` : "按实际用量计费";
  const total = count * minutesPerItem;
  const time = count <= 1 ? `约 ${minutesPerItem} 分钟` : `约 ${total} 分钟（逐条处理，每条约 ${minutesPerItem} 分钟，可以关掉页面，完成后在作品里查看）`;
  return { credits, time };
}

/** 模板对素材的要求，用一句话告诉商家。 */
export function templateNeeds(card: { capabilities?: string[] | null; material_mode?: string | null; engine?: string | null }): string {
  const caps = card.capabilities ?? [];
  const images = caps.includes("images") || card.material_mode === "images";
  const parts = ["需要人物口播视频（竖屏 9:16）"];
  parts.push(images ? "支持配图，可在第 3 步添加" : "以口播和文字呈现，不需要配图");
  if (card.engine === "bihuo-full-suite") parts.push("支持 MG 动效");
  return parts.join(" · ");
}
