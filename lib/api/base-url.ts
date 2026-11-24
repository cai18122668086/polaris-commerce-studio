/* 后端接口的地址前缀，和 openapi 客户端（lib/api/client.ts）用同一个来源。
   正式环境为空（同源 /api）；开发预览挂在子路径下时为 NEXT_PUBLIC_API_BASE_URL（如 /site），本地也可以是完整地址。
   不经过 openapi 客户端、直接 fetch 的地方都要用 apiUrl / apiFetch，否则会绕开这个前缀。 */

const viteEnv = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env;

export function resolveApiBaseUrl(
  value = (typeof process !== "undefined" ? process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || "" : "") ||
    viteEnv?.VITE_API_BASE_URL?.trim() ||
    "",
) {
  return value.replace(/\/+$/, "");
}

export const API_BASE_URL = resolveApiBaseUrl();

/** "/api/v1/…" → 带前缀的接口地址 */
export function apiUrl(path: string, base = API_BASE_URL) {
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

/** 直接 fetch 后端接口时使用，自动加上接口前缀 */
export function apiFetch(path: string, init?: RequestInit) {
  return fetch(apiUrl(path), init);
}

/** 后端 WebSocket 地址（同样带前缀，按页面协议选 ws / wss） */
export function apiWebSocketUrl(path: string, location: Pick<Location, "href" | "protocol"> = window.location) {
  const url = new URL(apiUrl(path), location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

/** 后端返回的媒体地址（如 "/api/v1/…/cover"）补上接口前缀；完整地址、blob/data 地址原样返回 */
export function mediaUrl(url: string | null | undefined, base = API_BASE_URL): string | undefined {
  if (!url) return undefined;
  return url.startsWith("/api/") ? apiUrl(url, base) : url;
}
