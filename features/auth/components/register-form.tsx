"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  authErrorMessage,
  fieldErrorsToMap,
  sendVerificationEmail,
  signUpWithEmailPassword,
} from "@/features/auth/api/auth";
import { verifyEmailHref, withReturnTo } from "@/lib/auth/return-to";
import { AUTH_ROUTES } from "@/lib/auth/routes";

export function RegisterForm({ returnTo = "/" }: { returnTo?: string }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(undefined);
    setFieldErrors({});
    if (password !== confirmation) {
      setFieldErrors({ confirmation: "两次输入的密码不一致。" });
      return;
    }

    setSubmitting(true);
    try {
      const result = await signUpWithEmailPassword(email, password);
      if (result.status === "FIELD_ERROR") {
        setFieldErrors(fieldErrorsToMap(result.formFields));
        return;
      }
      if (result.status === "SIGN_UP_NOT_ALLOWED") {
        setError(result.reason || "当前暂时无法注册。");
        return;
      }

      try {
        await sendVerificationEmail();
      } catch {
        // The verification page offers a retry action when delivery fails.
      }
      router.replace(verifyEmailHref(returnTo));
      router.refresh();
    } catch (caught) {
      setError(authErrorMessage(caught, "注册失败，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="auth-form" onSubmit={handleSubmit}>
      <label className="auth-field">
        <span>邮箱</span>
        <input
          autoComplete="email"
          inputMode="email"
          name="email"
          onChange={(event) => setEmail(event.target.value)}
          placeholder="name@example.com"
          required
          type="email"
          value={email}
        />
        {fieldErrors.email ? <small className="auth-field__error">{fieldErrors.email}</small> : null}
      </label>
      <label className="auth-field">
        <span>密码</span>
        <input
          autoComplete="new-password"
          minLength={8}
          name="password"
          onChange={(event) => setPassword(event.target.value)}
          required
          type="password"
          value={password}
        />
        <small className="auth-field__hint">至少 8 位，建议使用未在其他网站使用过的密码。</small>
        {fieldErrors.password ? <small className="auth-field__error">{fieldErrors.password}</small> : null}
      </label>
      <label className="auth-field">
        <span>确认密码</span>
        <input
          autoComplete="new-password"
          minLength={8}
          name="confirmation"
          onChange={(event) => setConfirmation(event.target.value)}
          required
          type="password"
          value={confirmation}
        />
        {fieldErrors.confirmation ? <small className="auth-field__error">{fieldErrors.confirmation}</small> : null}
      </label>
      {error ? <p className="auth-form__error" role="alert">{error}</p> : null}
      <button className="auth-button auth-button--primary auth-button--full" disabled={submitting} type="submit">
        {submitting ? "正在注册…" : "创建账号"}
      </button>
      <p className="auth-form__switch">
        已有账号？<Link href={withReturnTo(AUTH_ROUTES.login, returnTo)}>直接登录</Link>
      </p>
      <p className="auth-form__legal">注册即表示你同意遵守平台服务约定与隐私规则。</p>
    </form>
  );
}
