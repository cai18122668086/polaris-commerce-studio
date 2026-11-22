export type PricedAction = "lipsync" | "avatar_motion" | "avatar_register" | "voice_clone" | "editing_planning" | "editing_render" | "benchmark_search" | "writing_generate";
export type PriceTable = Partial<Record<PricedAction, number | null>>;
export type CreditAccount = { available: number; enforced: boolean };
export type CostNote = { text: string; credits: number | null; insufficient: boolean };

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
  if (credits === null) return { text: ["价格待定", balance].filter(Boolean).join(" · "), credits: null, insufficient: false };
  const insufficient = !!account && account.enforced && account.available < credits;
  const head = actions.length > 1 ? `共需 ${credits} 积分（分 ${actions.length} 步扣）` : `预计 ${credits} 积分`;
  return { text: [head, balance, insufficient ? "余额不足" : ""].filter(Boolean).join(" · "), credits, insufficient };
}
