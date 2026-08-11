import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const root = path.resolve(new URL("..", import.meta.url).pathname.replace(/^\/(?:[A-Za-z]:)/, (value) => value.slice(1)));
const utf8 = (relativePath) => readFile(path.join(root, relativePath), "utf8");

async function importBundled(entry) {
  const directory = await mkdtemp(path.join(os.tmpdir(), "polaris-auth-test-"));
  const output = path.join(directory, "module.mjs");
  await build({
    entryPoints: [path.join(root, entry)],
    bundle: true,
    format: "esm",
    platform: "node",
    outfile: output,
    logLevel: "silent",
  });
  const importedModule = await import(`${pathToFileURL(output).href}?t=${Date.now()}`);
  await rm(directory, { recursive: true, force: true });
  return importedModule;
}

test("auth and legal routes are public and account does not require a workspace", async () => {
  const routes = await importBundled("lib/auth/routes.ts");
  assert.equal(routes.isPublicRoute("/auth/login"), true);
  assert.equal(routes.isPublicRoute("/auth/register"), true);
  assert.equal(routes.isPublicRoute("/legal/terms"), true);
  assert.equal(routes.isPublicRoute("/legal/privacy"), true);
  assert.equal(routes.isPublicRoute("/"), false);
  assert.equal(routes.isPublicRoute("/assets"), false);
  assert.equal(routes.routeRequiresWorkspace("/account"), false);
  assert.equal(routes.routeRequiresWorkspace("/legal/privacy"), false);
  assert.equal(routes.routeRequiresWorkspace("/assets"), true);
});

test("registration requires explicit agreement and opens legal documents without leaving the form", async () => {
  const [registerForm, registerPage] = await Promise.all([
    utf8("features/auth/components/register-form.tsx"),
    utf8("app/auth/register/page.tsx"),
  ]);
  assert.match(registerForm, /if \(!acceptedAgreements\)/);
  assert.doesNotMatch(registerForm, /acceptedCrossBorder/);
  assert.doesNotMatch(registerPage, /description=/);
  assert.match(registerForm, /signUpWithEmailPassword\(email, password\)/);
  assert.ok(registerForm.indexOf("if (!acceptedAgreements)") < registerForm.indexOf("signUpWithEmailPassword(email, password)"));
  assert.match(registerForm, /target="_blank"/);
  assert.match(registerForm, /rel="noreferrer"/);
});

test("legal documents use confirmed operator details and actual data flows", async () => {
  const terms = await utf8("app/legal/terms/page.tsx");
  const privacy = await utf8("app/legal/privacy/page.tsx");

  for (const document of [terms, privacy]) {
    assert.match(document, /揭阳市腾利科技服务有限公司/);
    assert.match(document, /人工智能处理环境/);
    assert.match(document, /一个月/);
    assert.doesNotMatch(document, /蕉点AI|武汉光瞳科技有限公司/);
  }

  assert.match(terms, /用于模型训练/);
  assert.match(privacy, /1474953130@qq\.com/);
  assert.match(privacy, /广东省揭阳市揭东区新亨商务中心1407/);
  assert.match(privacy, /中国香港/);
  assert.match(privacy, /用于模型训练/);
});

test("returnTo accepts internal business routes and rejects open redirects or auth loops", async () => {
  const { sanitizeReturnTo } = await importBundled("lib/auth/return-to.ts");
  assert.equal(sanitizeReturnTo("/assets?kind=image#recent"), "/assets?kind=image#recent");
  for (const unsafe of [
    "https://evil.example/steal",
    "//evil.example/steal",
    "/\\evil.example/steal",
    "/%5cevil.example/steal",
    "/auth/login",
    "/auth/register?returnTo=/assets",
  ]) {
    assert.equal(sanitizeReturnTo(unsafe), "/", unsafe);
  }
});

test("final API 401 is centralised without browser token storage", async () => {
  const [client, boundary, sessionEvents, providers] = await Promise.all([
    utf8("lib/api/client.ts"),
    utf8("components/auth/auth-boundary.tsx"),
    utf8("lib/auth/session-events.ts"),
    utf8("app/providers.tsx"),
  ]);

  assert.match(client, /response\.status !== 401/);
  assert.match(client, /emitAuthUnauthorised\("api-401"\)/);
  assert.match(client, /credentials: "include"/);
  assert.match(client, /globalThis\.fetch\(request\)/);
  assert.match(client, /fetch: runtimeFetch/);
  assert.match(boundary, /queryClient\.clear\(\)/);
  assert.match(boundary, /onAuthUnauthorised\(redirectToLogin\)/);
  assert.match(boundary, /if \(publicRoute\) return;\s*return onAuthUnauthorised/);
  assert.match(sessionEvents, /polaris:auth:unauthorised/);
  assert.match(providers, /<AuthBoundary>\{children\}<\/AuthBoundary>/);

  const authSources = await Promise.all([
    utf8("lib/auth/client.ts"),
    utf8("features/auth/api/auth.ts"),
    utf8("components/auth/auth-boundary.tsx"),
  ]);
  for (const source of authSources) {
    assert.doesNotMatch(source, /localStorage\s*\./);
    assert.doesNotMatch(source, /sessionStorage\s*\./);
    assert.doesNotMatch(source, /Authorization\s*:/i);
  }
});
