export type PricedAction = "lipsync" | "avatar_motion" | "avatar_register" | "voice_clone" | "editing_planning" | "editing_render" | "benchmark_search" | "writing_generate" | "cover_generate" | "editing_auto_image" | "avatar_polish" | "writing_publish_fill";
export type PriceTable = Partial<Record<PricedAction, number | null>>;
export type CreditAccount = { available: number; enforced: boolean };
export type CostNote = { text: string; credits: number | null; insufficient: boolean };

/**
 * 价格未配置（灰度期 POLARIS_VIDEO_CREDIT_PRICES={}）时，全站统一显示这一句。
 * 由「价格是否为空」驱动：dev/正式站一旦配上价格，所有地方自动切回具体积分，不要在页面里写死。
 */
export const FREE_TRIAL_TEXT = "灰度测试期间不扣积分";
/** 按钮上的短版：「生成预览 · 不扣积分」。 */
export const FREE_TRIAL_SHORT = "不扣积分";
/** 旧名字，保留兼容；含义与 FREE_TRIAL_TEXT 相同。 */
export const UNPRICED_TEXT = FREE_TRIAL_TEXT;

/** 这一个动作（或一个合计）有没有配置价格。0 也算配置了（显示「0 积分」）。 */
export function isPriced(credits: number | null | undefined): credits is number {
  return typeof credits === "number" && Number.isFinite(credits);
}

/**
 * 价格表里这些动作是否都配置了价格；不传 actions 时判断「整张价格表是否为空」。
 * 页面据此决定显示具体积分还是 FREE_TRIAL_TEXT。
 */
export function pricesConfigured(prices: PriceTable, actions?: PricedAction[]): boolean {
  if (actions) return actions.length > 0 && actions.every(action => isPriced(prices[action]));
  return Object.values(prices).some(value => isPriced(value));
}

const fmt = (credits: number) => credits.toLocaleString("zh-CN");

/**
 * 一段说明里的积分短语。有价格：「20 积分」「7 积分/张，失败不扣」；没价格：「灰度测试期间不扣积分」。
 * 「失败不扣」「按张扣」这类只在真的会扣积分时才有意义，所以价格为空时一律不出现。
 */
export function creditPhrase(credits: number | null | undefined, options: { per?: string; failureFree?: boolean } = {}): string {
  if (!isPriced(credits)) return FREE_TRIAL_TEXT;
  const head = `${fmt(credits)} 积分${options.per ? `/${options.per}` : ""}`;
  return options.failureFree ? `${head}，失败不扣` : head;
}

/** 只在有价格时才显示的句子（例如「失败的不扣积分」「重复点击不会重复扣费」）；价格为空时返回空串。 */
export function whenPriced(credits: number | null | undefined, text: string): string {
  return isPriced(credits) ? text : "";
}

/**
 * What a paid button tells the user before they click. Several actions are
 * summed (e.g. avatar motion + registration are charged in two steps but shown
 * as one total up front). Unconfigured prices show the gray-test line; nothing is made up.
 */
export function costNote(actions: PricedAction[], prices: PriceTable, account?: CreditAccount): CostNote {
  const values = actions.map(action => prices[action]);
  const known = values.every((value): value is number => isPriced(value));
  const credits = known ? values.reduce((sum, value) => sum + value, 0) : null;
  const balance = account ? `可用 ${fmt(account.available)} 积分` : "";
  if (credits === null) return { text: [FREE_TRIAL_TEXT, balance].filter(Boolean).join(" · "), credits: null, insufficient: false };
  const insufficient = !!account && account.enforced && account.available < credits;
  const head = actions.length > 1 ? `共需 ${credits} 积分（分 ${actions.length} 步扣）` : `预计 ${credits} 积分`;
  return { text: [head, balance, insufficient ? "余额不足" : ""].filter(Boolean).join(" · "), credits, insufficient };
}

/**
 * One rule for every billable button: the action, then its credit cost
 * ("生成预览 · 20 积分"). Without a configured price: "生成预览 · 不扣积分".
 */
export function billableLabel(action: string, credits: number | null | undefined): string {
  return isPriced(credits) ? `${action} · ${fmt(credits)} 积分` : `${action} · ${FREE_TRIAL_SHORT}`;
}
