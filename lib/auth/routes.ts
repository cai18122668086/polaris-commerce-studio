import { AUTH_WEBSITE_BASE_PATH } from "./config";

export const AUTH_ROUTES = {
  login: `${AUTH_WEBSITE_BASE_PATH}/login`,
  register: `${AUTH_WEBSITE_BASE_PATH}/register`,
  verifyEmail: `${AUTH_WEBSITE_BASE_PATH}/verify-email`,
  forgotPassword: `${AUTH_WEBSITE_BASE_PATH}/forgot-password`,
  resetPassword: `${AUTH_WEBSITE_BASE_PATH}/reset-password`,
  account: "/account",
} as const;

export function isPublicRoute(pathname: string): boolean {
  return pathname === AUTH_WEBSITE_BASE_PATH || pathname.startsWith(`${AUTH_WEBSITE_BASE_PATH}/`);
}

export function routeRequiresWorkspace(pathname: string): boolean {
  return !isPublicRoute(pathname) && pathname !== AUTH_ROUTES.account;
}
