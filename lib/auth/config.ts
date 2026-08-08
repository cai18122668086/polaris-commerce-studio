export const AUTH_APP_NAME = "极光商绘";
export const AUTH_WEBSITE_BASE_PATH = "/auth";
export const AUTH_API_BASE_PATH = "/api/auth";

export type AuthRuntimeConfig = {
  appName: string;
  websiteDomain: string;
  apiDomain: string;
  websiteBasePath: string;
  apiBasePath: string;
};

export function getAuthRuntimeConfig(): AuthRuntimeConfig {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return {
    appName: AUTH_APP_NAME,
    websiteDomain: origin,
    apiDomain: origin,
    websiteBasePath: AUTH_WEBSITE_BASE_PATH,
    apiBasePath: AUTH_API_BASE_PATH,
  };
}
