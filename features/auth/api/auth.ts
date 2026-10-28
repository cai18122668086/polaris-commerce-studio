import EmailPassword from "supertokens-web-js/recipe/emailpassword";
import EmailVerification from "supertokens-web-js/recipe/emailverification";
import Session from "supertokens-web-js/recipe/session";

import { initializeAuthClient } from "@/lib/auth/client";
import { isLocalDevelopmentAuthEnabled, LOCAL_DEV_AUTH_USER_ID } from "@/lib/auth/local-dev";
import type { AuthTraceContext } from "@/lib/auth/diagnostics";

export type AuthFieldError = { id: string; error: string };
const PASSWORD_ERROR_MESSAGES: Record<string, string> = {
  "Password must contain at least 8 characters, including a number": "密码至少需要 8 位，并包含至少一个数字。",
  "Password's length must be lesser than 100 characters": "密码不能超过 99 位。",
  "Password must contain at least one alphabet": "密码至少需要包含一个英文字母。",
  "Password must contain at least one number": "密码至少需要包含一个数字。",
};
const initialise = () => initializeAuthClient();

export async function sessionExists(trace?: AuthTraceContext) {
  if (isLocalDevelopmentAuthEnabled()) return true;
  initialise();
  return Session.doesSessionExist(trace ? { userContext: { polarisAuthTrace: trace } } : undefined);
}
export async function getSessionUserId() {
  if (isLocalDevelopmentAuthEnabled()) return LOCAL_DEV_AUTH_USER_ID;
  initialise();
  return Session.getUserId();
}
export async function signOut() {
  if (isLocalDevelopmentAuthEnabled()) return;
  initialise();
  await Session.signOut();
}
export async function signInWithEmailPassword(email: string, password: string) {
  if (isLocalDevelopmentAuthEnabled()) return { status: "OK" as const };
  initialise();
  return EmailPassword.signIn({ formFields: [{ id: "email", value: email.trim() }, { id: "password", value: password }] });
}
export async function signUpWithEmailPassword(email: string, password: string) {
  initialise();
  return EmailPassword.signUp({ formFields: [{ id: "email", value: email.trim() }, { id: "password", value: password }] });
}
export async function sendPasswordResetEmail(email: string) {
  initialise();
  return EmailPassword.sendPasswordResetEmail({ formFields: [{ id: "email", value: email.trim() }] });
}
export async function submitNewPassword(password: string) {
  initialise();
  return EmailPassword.submitNewPassword({ formFields: [{ id: "password", value: password }] });
}
export async function isEmailVerified(trace?: AuthTraceContext) {
  if (isLocalDevelopmentAuthEnabled()) return true;
  initialise();
  return (await EmailVerification.isEmailVerified(trace ? { userContext: { polarisAuthTrace: trace } } : undefined)).isVerified;
}
export async function verifyEmail() {
  initialise();
  return EmailVerification.verifyEmail();
}
export async function verifyEmailCode(code: string) {
  initialise();
  return EmailVerification.verifyEmail({ userContext: { verificationCode: code.trim() } });
}
export async function sendVerificationEmail() {
  initialise();
  return EmailVerification.sendVerificationEmail();
}
export function authErrorMessage(error: unknown, fallback = "请求未能完成，请稍后重试。"): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
export function fieldErrorsToMap(errors: AuthFieldError[]): Record<string, string> {
  return Object.fromEntries(errors.map((field) => [field.id, PASSWORD_ERROR_MESSAGES[field.error] ?? field.error]));
}
