export type PricedAction = "lipsync" | "avatar_motion" | "avatar_register" | "voice_clone" | "editing_planning" | "editing_render" | "benchmark_search" | "writing_generate" | "cover_generate" | "editing_auto_image" | "avatar_polish" | "writing_publish_fill";
export type PriceTable = Partial<Record<PricedAction, number | null>>;
export type CreditAccount = { available: number; enforced: boolean };
export type CostNote = { text: string; credits: number | null; insufficient: boolean };

/** Shown instead of a number when an action has no configured price. */
export const UNPRICED_TEXT = "按实际用量计费";

/**
 * What a paid button tells the user before they click. Several actions are
 * summed (e.g. avatar motion + registration are charged in two steps but shown
 * as one total up front). Unconfigured prices say so plainly; nothing is made up.
 */
export function costNote(actions: PricedAction[], prices: PriceTable, account?: CreditAccount): CostNote {
  const values = actions.map(action => prices[action]);
  const known = values.every((value): value is number => typeof value === "number");
  const credits = known ? values.reduce((sum, value) => sum + value, 0) : null;
  const balance = account ? `可用 ${account.available.toLocaleString("zh-CN")} 积分` : "";
  if (credits === null) return { text: [UNPRICED_TEXT, balance].filter(Boolean).join(" · "), credits: null, insufficient: false };
  const insufficient = !!account && account.enforced && account.available < credits;
  const head = actions.length > 1 ? `共需 ${credits} 积分（分 ${actions.length} 步扣）` : `预计 ${credits} 积分`;
  return { text: [head, balance, insufficient ? "余额不足" : ""].filter(Boolean).join(" · "), credits, insufficient };
}

/**
 * One rule for every billable button: the action, then its credit cost
 * ("生成预览 · 20 积分"). Without a configured price the button only marks
 * the action as billable ("生成预览（计费）") instead of showing a number.
 */
export function billableLabel(action: string, credits: number | null | undefined): string {
  return typeof credits === "number" ? `${action} · ${credits.toLocaleString("zh-CN")} 积分` : `${action}（计费）`;
}
