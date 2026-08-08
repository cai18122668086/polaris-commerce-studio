import EmailPassword from "supertokens-web-js/recipe/emailpassword";
import EmailVerification from "supertokens-web-js/recipe/emailverification";
import Session from "supertokens-web-js/recipe/session";

import { initializeAuthClient } from "@/lib/auth/client";

export type AuthFieldError = { id: string; error: string };
const initialise = () => initializeAuthClient();

export async function sessionExists() { initialise(); return Session.doesSessionExist(); }
export async function getSessionUserId() { initialise(); return Session.getUserId(); }
export async function signOut() { initialise(); await Session.signOut(); }
export async function signInWithEmailPassword(email: string, password: string) {
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
export async function isEmailVerified() { initialise(); return (await EmailVerification.isEmailVerified()).isVerified; }
export async function verifyEmail() { initialise(); return EmailVerification.verifyEmail(); }
export async function sendVerificationEmail() { initialise(); return EmailVerification.sendVerificationEmail(); }
export function authErrorMessage(error: unknown, fallback = "请求未能完成，请稍后重试。"): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
export function fieldErrorsToMap(errors: AuthFieldError[]): Record<string, string> {
  return Object.fromEntries(errors.map((field) => [field.id, field.error]));
}
