import SuperTokens from "supertokens-web-js";
import EmailPassword from "supertokens-web-js/recipe/emailpassword";
import EmailVerification from "supertokens-web-js/recipe/emailverification";
import Session from "supertokens-web-js/recipe/session";

import { getAuthRuntimeConfig } from "./config";
import { emitAuthUnauthorised } from "./session-events";

let authClientInitialized = false;

export function initializeAuthClient(): void {
  if (authClientInitialized || typeof window === "undefined") return;
  const config = getAuthRuntimeConfig();
  SuperTokens.init({
    appInfo: { appName: config.appName, apiDomain: config.apiDomain, apiBasePath: config.apiBasePath },
    recipeList: [
      EmailPassword.init(),
      EmailVerification.init(),
      Session.init({
        onHandleEvent(event) {
          if (event.action === "UNAUTHORISED") emitAuthUnauthorised("session");
          else if (event.action === "SIGN_OUT") emitAuthUnauthorised("sign-out");
        },
      }),
    ],
  });
  authClientInitialized = true;
}

export function isAuthClientInitialized(): boolean {
  return authClientInitialized;
}
