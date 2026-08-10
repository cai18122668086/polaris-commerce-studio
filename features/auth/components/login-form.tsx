"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  authErrorMessage,
  fieldErrorsToMap,
  isEmailVerified,
  signInWithEmailPassword,
} from "@/features/auth/api/auth";
import { verifyEmailHref, withReturnTo } from "@/lib/auth/return-to";
import { AUTH_ROUTES } from "@/lib/auth/routes";

export function LoginForm({ returnTo = "/" }: { returnTo?: string }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(undefined);
    setFieldErrors({});
    setSubmitting(true);

    try {
      const result = await signInWithEmailPassword(email, password);
      if (result.status === "FIELD_ERROR") {
        setFieldErrors(fieldErrorsToMap(result.formFields));
        return;
      }
      if (result.status === "WRONG_CREDENTIALS_ERROR") {
        setError("邮箱或密码不正确。请检查后重试。");
        return;
      }
      if (result.status === "SIGN_IN_NOT_ALLOWED") {
        setError(result.reason || "当前账号暂时无法登录。");
        return;
      }

      router.replace((await isEmailVerified()) ? returnTo : verifyEmailHref(returnTo));
      router.refresh();
    } catch (caught) {
      setError(authErrorMessage(caught, "登录失败，请稍后重试。"));
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
          autoComplete="current-password"
          minLength={8}
          name="password"
          onChange={(event) => setPassword(event.target.value)}
          required
          type="password"
          value={password}
        />
        {fieldErrors.password ? <small className="auth-field__error">{fieldErrors.password}</small> : null}
      </label>
      <div className="auth-form__aside">
        <Link href={AUTH_ROUTES.forgotPassword}>忘记密码？</Link>
      </div>
      {error ? <p className="auth-form__error" role="alert">{error}</p> : null}
      <button className="auth-button auth-button--primary auth-button--full" disabled={submitting} type="submit">
        {submitting ? "正在登录…" : "登录"}
      </button>
      <p className="auth-form__switch">
        还没有账号？<Link href={withReturnTo(AUTH_ROUTES.register, returnTo)}>免费注册</Link>
      </p>
    </form>
  );
}
