import assert from "node:assert/strict";
import test from "node:test";

import { evaluateAudit } from "../tools/audit-security.mjs";

const reviewDate = new Date("2026-11-18T00:00:00+08:00");
const advisory = {
  name: "picomatch", source: 1247710, severity: "high", range: "<=4.0.7",
  title: "ReDoS through single-branch repeated extglobs",
  url: "https://github.com/advisories/GHSA-fc5q-39xc-vjpf",
};
const lockfile = { packages: {
  "node_modules/picomatch": { dev: true, version: "2.3.2" },
  "node_modules/tinyglobby/node_modules/picomatch": { dev: true, version: "4.0.4" },
  "node_modules/vite/node_modules/picomatch": { dev: true, version: "4.0.7" },
} };

function fixture() {
  return { auditReportVersion: 2, vulnerabilities: {
    picomatch: { severity: "high", via: [{ ...advisory }], nodes: Object.keys(lockfile.packages) },
    tinyglobby: { severity: "high", via: ["picomatch"] },
    vite: { severity: "high", via: ["picomatch", "tinyglobby"] },
    vinext: { severity: "high", via: ["vite"] },
  } };
}

test("the reviewed advisory and its transitive findings share one temporary exception", () => {
  assert.deepEqual(evaluateAudit(fixture(), lockfile, reviewDate), {
    blocking: [], exceptions: [advisory.url],
  });
});

test("the original high threshold continues to allow moderate findings", () => {
  const report = { auditReportVersion: 2, vulnerabilities: {
    example: { severity: "moderate", via: [{ severity: "moderate", url: "https://example.test" }] },
  } };
  assert.deepEqual(evaluateAudit(report, lockfile, reviewDate), { blocking: [], exceptions: [] });
});

test("a different high advisory on an excepted dependency still blocks", () => {
  const report = fixture();
  report.vulnerabilities.vite.via.push({
    name: "vite", severity: "high", title: "Another issue", url: "https://example.test/new",
  });
  assert.equal(evaluateAudit(report, lockfile, reviewDate).blocking.length, 1);
});

test("critical findings continue to block", () => {
  const report = fixture();
  report.vulnerabilities.other = { severity: "critical", via: [{
    name: "other", severity: "critical", title: "Another issue", url: "https://example.test/critical",
  }] };
  assert.equal(evaluateAudit(report, lockfile, reviewDate).blocking.length, 1);
});

test("the advisory blocks at the exact exception expiry", () => {
  assert.equal(evaluateAudit(fixture(), lockfile, new Date("2026-11-25T00:00:00+08:00")).blocking.length, 1);
});

test("the exception expiry does not block a clean report after upstream is fixed", () => {
  const report = { auditReportVersion: 2, vulnerabilities: {} };
  assert.deepEqual(evaluateAudit(report, lockfile, new Date("2026-11-26T00:00:00+08:00")), {
    blocking: [], exceptions: [],
  });
});

test("unreviewed installations and changed advisory scope require another review", () => {
  for (const installation of [{ dev: false, version: "4.0.7" }, { dev: true, version: "4.0.8" }, undefined]) {
    const changed = structuredClone(lockfile);
    changed.packages["node_modules/vite/node_modules/picomatch"] = installation;
    assert.equal(evaluateAudit(fixture(), changed, reviewDate).blocking.length, 1);
  }
  for (const change of [{ source: 999 }, { range: "*" }, { name: "other" }, { severity: "critical" }]) {
    const report = fixture();
    Object.assign(report.vulnerabilities.picomatch.via[0], change);
    assert.equal(evaluateAudit(report, lockfile, reviewDate).blocking.length, 1);
  }
});

test("incomplete reports and unresolved high findings fail closed", () => {
  const reports = [
    { ...fixture(), auditReportVersion: 1 },
    { ...fixture(), error: { code: "NETWORK_ERROR" } },
    { ...fixture(), vulnerabilities: null },
    { ...fixture(), vulnerabilities: [] },
    { auditReportVersion: 2, vulnerabilities: { missing: { severity: "high", via: [] } } },
    { auditReportVersion: 2, vulnerabilities: { missing: { severity: "high", via: ["unknown"] } } },
    { auditReportVersion: 2, vulnerabilities: { cycle: { severity: "high", via: ["cycle"] } } },
  ];
  for (const report of reports) assert.throws(() => evaluateAudit(report, lockfile, reviewDate));
});
