import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync, realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";

const advisoryUrl = "https://github.com/advisories/GHSA-fc5q-39xc-vjpf";
const exceptionExpires = new Date("2026-11-25T00:00:00+08:00");
const reviewedVersions = new Set(["2.3.2", "4.0.4", "4.0.7"]);

// Reviewed 2026-11-18. Vite and ESLint use these locked development dependencies
// for repository-controlled file patterns. Application code accepts no external
// glob patterns. Upstream has no patched release for this advisory. Reassess by
// 2026-11-25, or remove this exception when a patched release becomes available.
export function evaluateAudit(report, lockfile, now = new Date()) {
  assert.equal(report.auditReportVersion, 2, "Unsupported npm audit report");
  assert.ok(!report.error, "npm audit returned an error");
  assert.ok(
    report.vulnerabilities && typeof report.vulnerabilities === "object" &&
    !Array.isArray(report.vulnerabilities),
    "Missing npm vulnerability report",
  );
  assert.ok(Number.isFinite(now.getTime()), "Invalid audit date");

  const blocking = new Set();
  const exceptions = new Set();
  const picomatch = report.vulnerabilities.picomatch;
  const reviewedInstallation = picomatch?.nodes?.length > 0 && picomatch.nodes.every(node => {
    const installed = lockfile.packages?.[node];
    return installed?.dev === true && reviewedVersions.has(installed.version);
  });

  for (const [name, vulnerability] of Object.entries(report.vulnerabilities)) {
    assert.ok(Array.isArray(vulnerability.via), `Missing advisory sources for ${name}`);
    assert.ok(
      ["info", "low", "moderate", "high", "critical"].includes(vulnerability.severity),
      `Unknown severity for ${name}`,
    );
    if (!["high", "critical"].includes(vulnerability.severity)) continue;

    const sources = advisorySources(name, report.vulnerabilities)
      .filter(source => ["high", "critical"].includes(source.severity));
    assert.ok(sources.length > 0, `Unresolved high-severity finding for ${name}`);

    for (const source of sources) {
      if (
        source.name === "picomatch" && source.source === 1247710 &&
        source.url === advisoryUrl && source.range === "<=4.0.7" &&
        now < exceptionExpires && reviewedInstallation
      ) {
        exceptions.add(source.url);
      } else {
        blocking.add(`${source.name}: ${source.title} (${source.url})`);
      }
    }
  }
  return { blocking: [...blocking], exceptions: [...exceptions] };
}

function advisorySources(name, vulnerabilities, ancestors = new Set()) {
  assert.ok(!ancestors.has(name), `Circular audit reference for ${name}`);
  assert.ok(Array.isArray(vulnerabilities[name]?.via), `Unknown audit reference ${name}`);
  const visited = new Set([...ancestors, name]);
  return vulnerabilities[name].via.flatMap(source => {
    if (typeof source === "string") return advisorySources(source, vulnerabilities, visited);
    assert.ok(source && typeof source.url === "string", "Malformed npm advisory");
    assert.ok(
      ["info", "low", "moderate", "high", "critical"].includes(source.severity),
      "Unknown npm advisory severity",
    );
    return [source];
  });
}

function main() {
  assert.ok(process.env.npm_execpath, "Run with npm run audit:security");
  const audit = spawnSync(process.execPath, [
    process.env.npm_execpath, "audit", "--json", "--fetch-retries=0", "--fetch-timeout=20000",
  ], { encoding: "utf8", maxBuffer: 16 * 1024 * 1024, timeout: 60000, windowsHide: true });
  assert.ok(!audit.error && [0, 1].includes(audit.status), "npm audit could not complete");
  const report = JSON.parse(audit.stdout);
  const lockfile = JSON.parse(readFileSync(new URL("../package-lock.json", import.meta.url), "utf8"));
  const result = evaluateAudit(report, lockfile);
  console.log(JSON.stringify(report.metadata?.vulnerabilities ?? {}));
  for (const url of result.exceptions) {
    console.warn(`Temporary reviewed exception until 2026-11-25 00:00 Asia/Shanghai: ${url}`);
  }
  for (const finding of result.blocking) console.error(finding);
  process.exitCode = result.blocking.length ? 1 : 0;
}

if (process.argv[1] && realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url))) {
  try {
    main();
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
