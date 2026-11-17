const key = "polaris.signup-invitation";
export const invitationPattern = /^JG[A-F0-9]{10}$/;

export function rememberSignupInvitation(userId: string, code: string) {
  try {
    if (invitationPattern.test(code)) {
      localStorage.setItem(key, userId + ":" + code);
    } else {
      localStorage.removeItem(key);
    }
  } catch {
    // Storage restrictions must not block registration.
  }
}

export function pendingSignupInvitation() {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
