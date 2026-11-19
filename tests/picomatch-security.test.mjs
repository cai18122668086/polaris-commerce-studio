import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  parserReplacements,
  parserHashes,
  picomatchPackagePath,
  patchPicomatchSecurity,
  verifiedPicomatchPatches,
} from "../build/patch-picomatch-security.mjs";

const installedLockfile = JSON.parse(await readFile("package-lock.json", "utf8"));
const reviewedPackages = Object.entries(installedLockfile.packages)
  .filter(([name, item]) => picomatchPackagePath.test(name) && Object.hasOwn(parserHashes, item.version));
const legacyTestOptions = { skip: reviewedPackages.length === 0 };

async function fixture(context) {
  const root = await mkdtemp(path.join(os.tmpdir(), "polaris-picomatch-test-"));
  context.after(() => rm(root, { recursive: true, force: true }));
  const packages = reviewedPackages;
  for (const [name] of packages) {
    const directory = path.join(root, name);
    await cp(path.resolve(name), directory, { recursive: true });
    const filename = path.join(directory, "lib", "parse.js");
    let source = await readFile(filename, "utf8");
    for (const [before, after] of [...parserReplacements].reverse()) {
      if (source.includes(after)) source = source.replace(after, before);
      else assert.ok(source.includes(before));
    }
    await writeFile(filename, source);
  }
  await writeFile(path.join(root, "package-lock.json"), JSON.stringify({ packages: Object.fromEntries(packages) }));
  return { root, packages };
}

test("fresh installs, repeated application and partial retries retain verified parser bytes", legacyTestOptions, async context => {
  const { root, packages } = await fixture(context);
  assert.equal(verifiedPicomatchPatches(root).size, 0);
  patchPicomatchSecurity(root);
  assert.equal(verifiedPicomatchPatches(root).size, packages.length);
  const filename = path.join(root, packages[0][0], "lib", "parse.js");
  const first = await readFile(filename, "utf8");
  patchPicomatchSecurity(root);
  assert.equal(await readFile(filename, "utf8"), first);

  let original = first;
  for (const [before, after] of [...parserReplacements].reverse()) original = original.replace(after, before);
  await writeFile(filename, original);
  assert.equal(verifiedPicomatchPatches(root).size, packages.length - 1);
  patchPicomatchSecurity(root);
  assert.equal(verifiedPicomatchPatches(root).size, packages.length);
});

test("changed source and package identities cannot obtain verified mitigation", legacyTestOptions, async context => {
  const { root, packages } = await fixture(context);
  patchPicomatchSecurity(root);
  const directory = path.join(root, packages[0][0]);
  const filename = path.join(directory, "lib", "parse.js");
  const patched = await readFile(filename, "utf8");
  await writeFile(filename, patched + "\n// unexpected source change\n");
  assert.equal(verifiedPicomatchPatches(root).size, packages.length - 1);
  assert.throws(() => patchPicomatchSecurity(root), /Unreviewed picomatch source/);
  await writeFile(filename, patched);

  const packageJson = path.join(directory, "package.json");
  const metadata = JSON.parse(await readFile(packageJson, "utf8"));
  metadata.version = "0.0.0";
  await writeFile(packageJson, JSON.stringify(metadata));
  assert.equal(verifiedPicomatchPatches(root).size, packages.length - 1);
  assert.throws(() => patchPicomatchSecurity(root), /Unexpected installed version/);
});

test("future upstream versions and similarly named packages remain untouched", async context => {
  const root = await mkdtemp(path.join(os.tmpdir(), "polaris-picomatch-future-"));
  context.after(() => rm(root, { recursive: true, force: true }));
  const lockfile = { packages: {
    "node_modules/picomatch": { version: "99.0.0" },
    "node_modules/@types/picomatch": { version: "2.3.2" },
    "node_modules/@custom/picomatch": { version: "4.0.7" },
  } };
  await writeFile(path.join(root, "package-lock.json"), JSON.stringify(lockfile));
  const original = "// Future or unrelated upstream implementation\n";
  for (const [name, item] of Object.entries(lockfile.packages)) {
    await mkdir(path.join(root, name, "lib"), { recursive: true });
    await writeFile(path.join(root, name, "package.json"), JSON.stringify({ version: item.version }));
    await writeFile(path.join(root, name, "lib", "parse.js"), original);
  }
  patchPicomatchSecurity(root);
  for (const name of Object.keys(lockfile.packages)) {
    assert.equal(await readFile(path.join(root, name, "lib", "parse.js"), "utf8"), original);
  }
  assert.equal(verifiedPicomatchPatches(root).size, 0);
});

test("locked package paths cannot write outside the project", async context => {
  const root = await mkdtemp(path.join(os.tmpdir(), "polaris-picomatch-path-"));
  context.after(() => rm(root, { recursive: true, force: true }));
  const outside = path.resolve(root, "..", "outside", "node_modules", "picomatch").split(path.sep).join("/");
  await writeFile(path.join(root, "package-lock.json"), JSON.stringify({
    packages: { [outside]: { version: "2.3.2" } },
  }));
  assert.throws(() => patchPicomatchSecurity(root), /Package path escapes project/);
  assert.throws(() => verifiedPicomatchPatches(root), /Package path escapes project/);
});

test("all reviewed installed versions preserve ordinary matches and bound known malicious patterns", legacyTestOptions, async context => {
  const { root, packages } = await fixture(context);
  patchPicomatchSecurity(root);
  for (const [name] of packages) {
    const script = String.raw`
      const assert = require('node:assert/strict');
      const pm = require(process.argv[1]);
      for (const options of [{}, { dot: true }, { windows: true }, { windows: false }, { bash: true }, { nocase: true }]) {
        for (const [pattern, input, expected] of [
          ['**/*.{ts,tsx}', 'app/page.tsx', true],
          ['**/*.ts', 'lib/api.ts', true],
          ['!(*.d).ts', 'index.ts', true],
          ['!(*.d).ts', 'index.d.ts', false],
          ['*(a*|b)', 'ax', true],
          ['+(a*|b)', 'bbab', true],
          ['+(ab*|c)', 'ccabcc', true],
          ['*(a*|b)', 'bbb', true],
          ['*(a*|b)', 'cx', false],
          ['*/*(W*, *)*', 'my/folder (Work, Accts)', true],
          ['+(W*, *)', 'W, W, ', true],
          ['+(*a)', 'aaa', true],
          ['+(a*b)', 'abab', true],
          ['*(a*(ba)|a)', 'ababa', true],
          ['*(ab*(a)|ab)', 'abaaba', true],
          ['*(ab?(a)|ab)', 'abaabab', true],
          ['*(a*(bc)|a|bc)', 'bcaabc', true],
          ['+([*])', '***', true],
          ['+("*")', '***', true],
          ['+(\\*)', '***', true],
        ]) assert.equal(pm(pattern, options)(input), expected, pattern + ' / ' + input);
      }
      const input = 'a'.repeat(60000) + '/';
      const patterns = ['+(*a)', '*(*a)', '+(*)b', '+(a*)b', '+(@(*a))', '+(@(*)a)',
        '+(*a|b)', '+(*a|b)b', '*(*a|b)b', '+(a*a*a*a*a*)', '*(a*|b)z', '+(a*|b)z'];
      for (const options of [{}, { dot: true }, { windows: true }, { windows: false }, { bash: true }, { capture: true }]) {
        for (const pattern of patterns) assert.equal(pm(pattern, options)(input), false, pattern);
      }
      for (const options of [{ nocase: true }, { flags: 'i' }]) {
        assert.equal(pm('+(A*|a)', options)(input), false);
        assert.equal(pm('*(A*|a)', options)(input), false);
      }
      for (const options of [{}, { nobracket: true }]) {
        assert.equal(pm('+([*a)', options)('[a'.repeat(10000) + '!'), false);
        assert.equal(pm('+([*a])', options)('[a]'.repeat(10000) + '!'), false);
      }
      assert.equal(pm('+(W*, *)z')('W, '.repeat(10000) + '!'), false);
      assert.equal(pm('*(W*, *)z')('W, '.repeat(10000) + '!'), false);
      const nested = [
        ['*(a*(ba)|a)', 'a'], ['*(a?(ba)|a)', 'a'],
        ['*(ab*(a)|ab)', 'ab'], ['*(ab?(a)|ab)', 'ab'],
        ['*(a*(ba)|a|c)', 'a'], ['*(a*(aba)|a)', 'a'],
        ['*(ab*(a)|ab|c)', 'ab'], ['+(a*(ba)|c)', 'a'],
      ];
      for (const options of [{}, { windows: false }, { windows: true }, { capture: true }]) {
        for (const [pattern, unit] of nested) {
          assert.equal(pm(pattern, options)(unit.repeat(10000) + '/'), false, pattern);
        }
      }
      for (const options of [{ nocase: true }, { flags: 'i' }]) {
        assert.equal(pm('*(a*(ba)|A)', options)('aaba'), true);
        assert.equal(pm('*(a*(ba)|A)', options)('a'.repeat(10000) + '/'), false);
        assert.equal(pm('*(ab*(a)|AB)', options)('ab'.repeat(10000) + '/'), false);
      }
    `;
    // A backtracking regex cannot enforce its own timeout on a blocked event loop.
    const result = spawnSync(process.execPath, ["-e", script, path.join(root, name)], {
      encoding: "utf8", timeout: 5000, killSignal: "SIGKILL", windowsHide: true,
    });
    assert.ifError(result.error);
    assert.equal(result.status, 0, name + "\n" + result.stderr);
  }
});
