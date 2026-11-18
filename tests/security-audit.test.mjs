import assert from "node:assert/strict";
import test from "node:test";

import { evaluateAudit } from "../tools/audit-security.mjs";

const advisory = {
  name: "picomatch", source: 1247710, severity: "high", range: "<=4.0.7",
  title: "ReDoS through single-branch repeated extglobs",
  url: "https://github.com/advisories/GHSA-fc5q-39xc-vjpf",
};
const verifiedPackages = new Set([
  "node_modules/picomatch",
  "node_modules/tinyglobby/node_modules/picomatch",
  "node_modules/vite/node_modules/picomatch",
]);

function fixture() {
  return { auditReportVersion: 2, vulnerabilities: {
    picomatch: { severity: "high", via: [{ ...advisory }], nodes: [...verifiedPackages] },
    tinyglobby: { severity: "high", via: ["picomatch"] },
    vite: { severity: "high", via: ["picomatch", "tinyglobby"] },
    vinext: { severity: "high", via: ["vite"] },
  } };
}

test("a verified fix resolves the advisory and its inherited findings", () => {
  assert.deepEqual(evaluateAudit(fixture(), verifiedPackages), {
    blocking: [], mitigated: [advisory.url],
  });
});

test("verified code continues to pass after the old waiver deadline", context => {
  context.mock.timers.enable({ apis: ["Date"], now: Date.parse("2099-01-01T00:00:00Z") });
  assert.deepEqual(evaluateAudit(fixture(), verifiedPackages), {
    blocking: [], mitigated: [advisory.url],
  });
});

test("unpatched or partially patched installations block the known advisory", () => {
  assert.equal(evaluateAudit(fixture()).blocking.length, 1);
  const partial = new Set(verifiedPackages);
  partial.delete("node_modules/vite/node_modules/picomatch");
  assert.equal(evaluateAudit(fixture(), partial).blocking.length, 1);
});

test("new affected copies require their own verified patch", () => {
  const report = fixture();
  report.vulnerabilities.picomatch.nodes.push("node_modules/another/node_modules/picomatch");
  assert.equal(evaluateAudit(report, verifiedPackages).blocking.length, 1);
});

test("metadata renumbering, equivalent ranges and narrowing do not invalidate verified code", () => {
  for (const change of [
    { source: 999 }, { range: "<4.0.8" }, { range: "<= 4.0.7" }, { range: "<4.0.8-0" },
    { range: "<=2.3.2 || >=4.0.4 <4.0.8" }, { range: ">=2.0.0 <=4.0.7" },
  ]) {
    const report = fixture();
    Object.assign(report.vulnerabilities.picomatch.via[0], change);
    assert.equal(evaluateAudit(report, verifiedPackages).blocking.length, 0);
  }
});

test("expanded advisory scope and severity still require another review", () => {
  for (const change of [{ severity: "critical" }, { range: "<=4.0.8" }, { range: "*" }]) {
    const report = fixture();
    Object.assign(report.vulnerabilities.picomatch.via[0], change);
    assert.equal(evaluateAudit(report, verifiedPackages).blocking.length, 1);
  }
});

test("unrelated high and critical advisories still block on patched dependencies", () => {
  for (const severity of ["high", "critical"]) {
    const report = fixture();
    report.vulnerabilities.vite.via.push({
      name: "vite", severity, title: "Another issue", url: "https://example.test/new",
    });
    assert.equal(evaluateAudit(report, verifiedPackages).blocking.length, 1);
  }
  for (const change of [{ name: "other" }, { url: "https://example.test/other" }]) {
    const report = fixture();
    Object.assign(report.vulnerabilities.picomatch.via[0], change);
    assert.equal(evaluateAudit(report, verifiedPackages).blocking.length, 1);
  }
});

test("the original high threshold continues to allow moderate findings", () => {
  const report = { auditReportVersion: 2, vulnerabilities: {
    example: { severity: "moderate", via: [{ severity: "moderate", url: "https://example.test" }] },
  } };
  assert.deepEqual(evaluateAudit(report), { blocking: [], mitigated: [] });
});

test("a clean upstream version needs no local mitigation or waiver", () => {
  assert.deepEqual(evaluateAudit({ auditReportVersion: 2, vulnerabilities: {} }), {
    blocking: [], mitigated: [],
  });
});

test("incomplete reports and unresolved high findings fail closed", () => {
  const reports = [
    { ...fixture(), auditReportVersion: 1 },
    { ...fixture(), error: { code: "NETWORK_ERROR" } },
    { ...fixture(), vulnerabilities: null },
    { ...fixture(), vulnerabilities: [] },
    { auditReportVersion: 2, vulnerabilities: {
      picomatch: { severity: "high", via: [{ ...advisory, range: "invalid-range" }], nodes: [...verifiedPackages] },
    } },
    { auditReportVersion: 2, vulnerabilities: { missing: { severity: "high", via: [] } } },
    { auditReportVersion: 2, vulnerabilities: { missing: { severity: "high", via: ["unknown"] } } },
    { auditReportVersion: 2, vulnerabilities: { cycle: { severity: "high", via: ["cycle"] } } },
  ];
  for (const report of reports) assert.throws(() => evaluateAudit(report, verifiedPackages));
});
