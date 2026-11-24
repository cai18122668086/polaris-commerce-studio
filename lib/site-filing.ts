/* 页脚的运营主体与备案信息。
   备案号由部署环境提供：NEXT_PUBLIC_ICP_NUMBER（ICP 备案号，如“粤ICP备2026000000号-1”）、
   NEXT_PUBLIC_PSB_NUMBER（公安联网备案号，如“粤公网安备44520000000000号”）。没有设置就不显示，避免挂出不存在的备案号。 */

export const SITE_OPERATOR = "揭阳市腾利科技服务有限公司";
export const ICP_LOOKUP_URL = "https://beian.miit.gov.cn/";

export type SiteFiling = {
  operator: string;
  icp: { number: string; href: string } | null;
  psb: { number: string; href: string } | null;
};

export function siteFiling(env: { icp?: string | null; psb?: string | null }): SiteFiling {
  const icp = env.icp?.trim();
  const psb = env.psb?.trim();
  const psbCode = psb?.match(/\d{8,}/)?.[0];
  return {
    operator: SITE_OPERATOR,
    icp: icp ? { number: icp, href: ICP_LOOKUP_URL } : null,
    psb: psb
      ? { number: psb, href: psbCode ? `https://beian.mps.gov.cn/#/query/webSearch?code=${psbCode}` : "https://beian.mps.gov.cn/" }
      : null,
  };
}

/** 读取当前部署的备案信息；NEXT_PUBLIC_* 在构建时写入页面 */
export function currentSiteFiling() {
  return siteFiling({
    icp: typeof process !== "undefined" ? process.env.NEXT_PUBLIC_ICP_NUMBER : undefined,
    psb: typeof process !== "undefined" ? process.env.NEXT_PUBLIC_PSB_NUMBER : undefined,
  });
}
