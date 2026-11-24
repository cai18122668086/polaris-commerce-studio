/* 搜索引擎相关的公开信息：站点地址、允许收录的公开页面、不应收录的内部路径。
   站点地址由 NEXT_PUBLIC_SITE_URL 指定，未设置时使用正式域名。 */

export const DEFAULT_SITE_URL = "https://www.jgshai.cn";

export function siteUrl(value = typeof process !== "undefined" ? process.env.NEXT_PUBLIC_SITE_URL : undefined) {
  const url = value?.trim().replace(/\/+$/, "");
  return url && /^https?:\/\//.test(url) ? url : DEFAULT_SITE_URL;
}

/** 未登录也能打开、适合被收录的页面 */
export const PUBLIC_SITEMAP_ROUTES = [
  { path: "/", priority: 1, changeFrequency: "weekly" },
  { path: "/auth/register", priority: 0.6, changeFrequency: "monthly" },
  { path: "/auth/login", priority: 0.4, changeFrequency: "monthly" },
  { path: "/legal/terms", priority: 0.3, changeFrequency: "yearly" },
  { path: "/legal/privacy", priority: 0.3, changeFrequency: "yearly" },
] as const;

/** 登录后才可用或仅内部使用的路径，不让搜索引擎抓取 */
export const DISALLOWED_PATHS = [
  "/api/", "/admin", "/account", "/assets", "/commerce-crawler", "/dashboard", "/diagnostics/",
  "/jobs", "/workspace", "/create", "/tools", "/style-replica", "/video-studio", "/auth/verify-email",
  "/auth/reset-password", "/auth/forgot-password",
] as const;
