import { AUTH_WEBSITE_BASE_PATH } from "./config";

export const AUTH_ROUTES = {
  login: `${AUTH_WEBSITE_BASE_PATH}/login`,
  register: `${AUTH_WEBSITE_BASE_PATH}/register`,
  verifyEmail: `${AUTH_WEBSITE_BASE_PATH}/verify-email`,
  forgotPassword: `${AUTH_WEBSITE_BASE_PATH}/forgot-password`,
  resetPassword: `${AUTH_WEBSITE_BASE_PATH}/reset-password`,
  account: "/account",
} as const;

export const LEGAL_ROUTES = {
  terms: "/legal/terms",
  privacy: "/legal/privacy",
} as const;

/** 未登录访客也能看的页面：首页（含价格）、帮助中心、灵感专区。
    这些页面在未登录时只展示公开内容，需要账号的操作会引导去登录。 */
export const MARKETING_PUBLIC_ROUTES = ["/", "/help", "/inspiration"] as const;

export function isPublicRoute(pathname: string): boolean {
  return (MARKETING_PUBLIC_ROUTES as readonly string[]).includes(pathname) ||
    pathname === AUTH_WEBSITE_BASE_PATH ||
    pathname.startsWith(`${AUTH_WEBSITE_BASE_PATH}/`) ||
    pathname === "/legal" ||
    pathname.startsWith("/legal/");
}

export function routeRequiresWorkspace(pathname: string): boolean {
  return !isPublicRoute(pathname) && pathname !== AUTH_ROUTES.account;
}
