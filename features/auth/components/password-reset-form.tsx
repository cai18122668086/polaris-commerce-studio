"use client";
import Link from "next/link";
import { useState } from "react";
import { authErrorMessage, fieldErrorsToMap, sendPasswordResetEmail, submitNewPassword } from "@/features/auth/api/auth";
import { AUTH_ROUTES } from "@/lib/auth/routes";

export function ForgotPasswordForm() {
  const [email, setEmail] = useState(""); const [error, setError] = useState<string>(); const [sent, setSent] = useState(false); const [submitting, setSubmitting] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) { event.preventDefault(); setSubmitting(true); setError(undefined); try { const result = await sendPasswordResetEmail(email); if (result.status === "FIELD_ERROR") { setError(fieldErrorsToMap(result.formFields).email || "请输入有效邮箱地址。"); return; } setSent(true); } catch (caught) { setError(authErrorMessage(caught, "重置邮件发送失败，请稍后重试。")); } finally { setSubmitting(false); } }
  if (sent) return <div className="auth-result auth-result--success"><h2>请检查邮箱</h2><p>如果该邮箱已注册，你将收到密码重置链接。为保护账号安全，我们不会披露邮箱是否存在。</p><Link className="auth-button auth-button--primary auth-button--full" href={AUTH_ROUTES.login}>返回登录</Link></div>;
  return <form className="auth-form" onSubmit={submit}><label className="auth-field"><span>注册邮箱</span><input autoComplete="email" inputMode="email" onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com" required type="email" value={email} /></label>{error ? <p className="auth-form__error" role="alert">{error}</p> : null}<button className="auth-button auth-button--primary auth-button--full" disabled={submitting} type="submit">{submitting ? "正在发送…" : "发送重置邮件"}</button><p className="auth-form__switch"><Link href={AUTH_ROUTES.login}>返回登录</Link></p></form>;
}

export function ResetPasswordForm() {
  const [password, setPassword] = useState(""); const [confirmation, setConfirmation] = useState(""); const [error, setError] = useState<string>(); const [completed, setCompleted] = useState(false); const [submitting, setSubmitting] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) { event.preventDefault(); setError(undefined); if (password !== confirmation) { setError("两次输入的密码不一致。"); return; } setSubmitting(true); try { const result = await submitNewPassword(password); if (result.status === "RESET_PASSWORD_INVALID_TOKEN_ERROR") { setError("密码重置链接已失效，请重新申请。"); return; } if (result.status === "FIELD_ERROR") { setError(fieldErrorsToMap(result.formFields).password || "新密码不符合安全要求。"); return; } setCompleted(true); } catch (caught) { setError(authErrorMessage(caught, "密码重置失败，请稍后重试。")); } finally { setSubmitting(false); } }
  if (completed) return <div className="auth-result auth-result--success"><h2>密码已更新</h2><p>请使用新密码重新登录。</p><Link className="auth-button auth-button--primary auth-button--full" href={AUTH_ROUTES.login}>前往登录</Link></div>;
  return <form className="auth-form" onSubmit={submit}><label className="auth-field"><span>新密码</span><input autoComplete="new-password" minLength={8} onChange={(e) => setPassword(e.target.value)} required type="password" value={password} /><small className="auth-field__hint">至少 8 位，建议使用未在其他网站使用过的密码。</small></label><label className="auth-field"><span>确认新密码</span><input autoComplete="new-password" minLength={8} onChange={(e) => setConfirmation(e.target.value)} required type="password" value={confirmation} /></label>{error ? <p className="auth-form__error" role="alert">{error}</p> : null}<button className="auth-button auth-button--primary auth-button--full" disabled={submitting} type="submit">{submitting ? "正在更新…" : "更新密码"}</button><p className="auth-form__switch"><Link href={AUTH_ROUTES.forgotPassword}>重新申请重置链接</Link></p></form>;
}
