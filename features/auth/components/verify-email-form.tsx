"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { authErrorMessage, isEmailVerified, sendVerificationEmail, sessionExists, verifyEmail, verifyEmailCode } from "@/features/auth/api/auth";
import { readReturnTo, withReturnTo } from "@/lib/auth/return-to";
import { AUTH_ROUTES } from "@/lib/auth/routes";

type VerificationState = "checking" | "pending" | "verified" | "invalid" | "signed-out" | "error";

export type VerificationDelivery = { status: "sending" | "sent" | "failed" | "verified"; message?: string; retryAt?: number };

export function VerifyEmailForm({ email, returnTo, delivery, registration = false }: { email?: string; returnTo?: string; delivery?: VerificationDelivery; registration?: boolean } = {}) {
  const router = useRouter();
  const check = useRef<Promise<VerificationState> | null>(null);
  const [state, setState] = useState<VerificationState>("checking");
  const [code, setCode] = useState("");
  const [message, setMessage] = useState<string>();
  const [sending, setSending] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [resendAfter, setResendAfter] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const cooldown = Math.min(60, Math.max(0, Math.ceil((Math.max(delivery?.retryAt ?? 0, resendAfter) - now) / 1000)));

  useEffect(() => {
    let cancelled = false;
    check.current ??= (async () => {
      if (!(await sessionExists())) return "signed-out";
      if (new URLSearchParams(window.location.search).get("token")) {
        const result = await verifyEmail();
        if (result.status === "EMAIL_VERIFICATION_INVALID_TOKEN_ERROR") return "invalid";
      }
      return (await isEmailVerified()) ? "verified" : "pending";
    })();
    void check.current.then(value => { if (!cancelled) setState(value); }).catch(error => {
      if (!cancelled) { setMessage(authErrorMessage(error)); setState("error"); }
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!cooldown) return;
    const timer = setTimeout(() => setNow(Date.now()), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  async function resend() {
    setSending(true); setMessage(undefined);
    try {
      const result = await sendVerificationEmail();
      if (result.status === "EMAIL_ALREADY_VERIFIED_ERROR") setState("verified");
      else {
        setResendAfter(Date.now() + 60_000); setNow(Date.now()); setState("pending");
        setMessage("验证码已发送，请检查收件箱和垃圾邮件目录，10 分钟内有效。");
      }
    } catch (error) { setMessage(authErrorMessage(error, "验证码发送失败，请稍后重试。")); }
    finally { setSending(false); }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault(); setSubmitting(true); setMessage(undefined);
    try {
      const result = await verifyEmailCode(code);
      if (result.status === "EMAIL_VERIFICATION_INVALID_TOKEN_ERROR") {
        setMessage("验证码错误或已过期，请检查后重试；多次错误后需重新发送。");
        return;
      }
      if (!(await isEmailVerified())) throw new Error("邮箱尚未完成验证，请重新获取验证码。");
      setState("verified");
    } catch (error) { setMessage(authErrorMessage(error, "验证失败，请稍后重试。")); }
    finally { setSubmitting(false); }
  }

  if (state === "checking") return <p className="auth-inline-status">正在检查邮箱验证状态…</p>;
  if (state === "verified") return <div className="auth-result auth-result--success" role="status"><h2>{registration ? "注册成功" : "邮箱验证成功"}</h2><p>邮箱验证已完成，现在可以开始创作。</p><button className="auth-button auth-button--primary auth-button--full" onClick={() => router.replace(returnTo ?? readReturnTo(window.location.search))}>进入工作台</button></div>;
  if (state === "signed-out") return <div className="auth-result"><h2>请先登录</h2><p>登录后继续输入邮箱验证码。</p><Link className="auth-button auth-button--primary auth-button--full" href={withReturnTo(AUTH_ROUTES.login, returnTo ?? readReturnTo(window.location.search))}>前往登录</Link></div>;

  return <form className="auth-form" onSubmit={submit}>
    {registration && <div><h2>验证邮箱，完成注册</h2><p>账号已创建，完成邮箱验证后即可开始创作。</p></div>}
    {email && <p>验证邮箱：<strong>{email}</strong></p>}
    {delivery?.status === "sending" && <p className="auth-inline-status" role="status">正在发送验证码…</p>}
    {delivery?.status === "sent" && !message && <p className="auth-form__notice" role="status">验证码已发送，10 分钟内有效。请检查收件箱和垃圾邮件目录。</p>}
    {delivery?.status === "failed" && !message && <p className="auth-form__error" role="alert">{delivery.message} 账号已保留，请点击重新发送，无需重复注册。</p>}
    <p>{state === "invalid" ? "原验证链接已失效，请获取新的验证码。" : "请输入注册邮箱收到的 6 位验证码。无需在邮件中点击链接。"}</p>
    <label className="auth-field"><span>邮箱验证码</span><input autoComplete="one-time-code" inputMode="numeric" name="code" pattern="[0-9]{6}" maxLength={6} required value={code} onChange={event => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="6 位数字验证码" /></label>
    {message && <p className="auth-form__notice" role="status">{message}</p>}
    <button className="auth-button auth-button--primary auth-button--full" disabled={submitting || code.length !== 6} type="submit">{submitting ? "正在验证…" : registration ? "验证并完成注册" : "验证邮箱"}</button>
    <button className="auth-button auth-button--secondary auth-button--full" disabled={sending || delivery?.status === "sending" || cooldown > 0} type="button" onClick={() => void resend()}>{sending || delivery?.status === "sending" ? "正在发送…" : cooldown ? `${cooldown} 秒后可重新发送` : "发送 / 重新发送验证码"}</button>
  </form>;
}
