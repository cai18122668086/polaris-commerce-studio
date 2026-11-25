// 注册来源：访客从带 ?from=<账号代码> 的链接进站时记下来（同一浏览器 30 天内，最近一次点的链接算数），
// 之后的 API 请求带上 X-Signup-Source。后端只在第一次建账号时记录，老用户不会被改。
// 代码和运营工作台里的平台账号代码一致，例如 xhs-01、dy-02。
const key = "polaris.signup-source";
const ttlMs = 30 * 24 * 60 * 60 * 1000;
export const signupSourcePattern = /^[a-z0-9][a-z0-9_-]{0,29}$/;

export function captureSignupSource(search: string, now = Date.now()) {
  try {
    const raw = new URLSearchParams(search).get("from");
    if (raw === null) return;
    const code = raw.trim().toLowerCase();
    if (signupSourcePattern.test(code)) {
      localStorage.setItem(key, JSON.stringify({ code, at: now }));
    }
  } catch {
    // Storage restrictions must not block browsing or registration.
  }
}

export function pendingSignupSource(now = Date.now()): string | null {
  if (typeof window === "undefined") return null;
  try {
    const stored = localStorage.getItem(key);
    if (!stored) return null;
    const value = JSON.parse(stored) as { code?: unknown; at?: unknown };
    if (
      typeof value.code !== "string" ||
      typeof value.at !== "number" ||
      !signupSourcePattern.test(value.code) ||
      now - value.at > ttlMs
    ) {
      localStorage.removeItem(key);
      return null;
    }
    return value.code;
  } catch {
    return null;
  }
}
