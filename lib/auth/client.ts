import SuperTokens from "supertokens-web-js";
import EmailPassword from "supertokens-web-js/recipe/emailpassword";
import EmailVerification from "supertokens-web-js/recipe/emailverification";
import Session from "supertokens-web-js/recipe/session";

import { emitAuthUnauthorised } from "./session-events";
import { isLocalDevelopmentAuthEnabled } from "./local-dev";
import { getAuthRuntimeConfig } from "./config";
import { boundedAuthRequest } from "./request-timeout";
import { configureAuthDiagnosticTransport, observeAuthResponse } from "./diagnostics";
import { observeAuthFetch } from "./fetch-observer";

let authClientInitialized = false;

export function initializeAuthClient(): void {
  if (authClientInitialized || typeof window === "undefined") return;
  // The local development backend intentionally uses a fixed development
  // identity instead of SuperTokens. Never enable this flag in production.
  if (isLocalDevelopmentAuthEnabled()) {
    authClientInitialized = true;
    return;
  }
  const config = getAuthRuntimeConfig();
  SuperTokens.init({
    appInfo: { appName: config.appName, apiDomain: config.apiDomain, apiBasePath: config.apiBasePath },
    recipeList: [
      EmailPassword.init({ preAPIHook: boundedAuthRequest, postAPIHook: observeAuthResponse }),
      EmailVerification.init({ preAPIHook: boundedAuthRequest, postAPIHook: observeAuthResponse }),
      Session.init({
        preAPIHook: boundedAuthRequest, postAPIHook: observeAuthResponse,
        override: {
          functions: (original) => ({
            ...original,
            addFetchInterceptorsAndReturnModifiedFetch: (input) => {
              configureAuthDiagnosticTransport(input.originalFetch);
              return observeAuthFetch(
                original.addFetchInterceptorsAndReturnModifiedFetch({ ...input, originalFetch: observeAuthFetch(input.originalFetch, "transport") }),
                "interceptor",
              );
            },
          }),
        },
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
