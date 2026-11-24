/* 首页价格区使用的公开价目。
   真实价目由后端 backend/app/credit_products.py（套餐、积分包）和 backend/app/welcome_credits.py（新用户赠送积分）决定；
   首页不登录也要能看价格，而后端价目接口挂在工作区下、需要登录，所以这里镜像一份。
   tests/pricing-catalog.test.mjs 会逐项对照后端源码，改价时两边必须一起改。 */

export type MembershipPlan = {
  id: "light" | "pro" | "team";
  name: string;
  /** 月付价格（分） */
  monthlyFen: number;
  /** 年付价格（分） */
  annualFen: number;
  /** 每月发放积分 */
  monthlyCredits: number;
};

export type CreditPack = {
  id: "pack_small" | "pack_medium" | "pack_large";
  name: string;
  amountFen: number;
  credits: number;
  validityMonths: number;
};

export const WELCOME_CREDITS = 50;
export const WELCOME_CREDITS_VALIDITY_DAYS = 30;

export const MEMBERSHIP_PLANS: readonly MembershipPlan[] = [
  { id: "light", name: "轻享版", monthlyFen: 4900, annualFen: 46800, monthlyCredits: 600 },
  { id: "pro", name: "专业版", monthlyFen: 9900, annualFen: 94800, monthlyCredits: 1500 },
  { id: "team", name: "团队版", monthlyFen: 29900, annualFen: 286800, monthlyCredits: 5000 },
];

export const CREDIT_PACKS: readonly CreditPack[] = [
  { id: "pack_small", name: "灵感补给", amountFen: 2990, credits: 300, validityMonths: 12 },
  { id: "pack_medium", name: "日常创作", amountFen: 9900, credits: 1100, validityMonths: 12 },
  { id: "pack_large", name: "高频出图", amountFen: 29900, credits: 3600, validityMonths: 12 },
];

/** 分 → “99” / “29.9” 这样的元金额 */
export function yuan(fen: number) {
  const value = fen / 100;
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/0$/, "");
}

export function formatCredits(credits: number) {
  return new Intl.NumberFormat("zh-CN").format(credits);
}
