import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({
  entryPoints: ["features/video-studio/editing-density.ts"],
  bundle: true,
  write: false,
  format: "esm",
  platform: "node",
  logLevel: "silent",
});
const { repeatedEffectsForReduction } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

test("density reduction keeps the first use, manual edits and every distinct group", () => {
  const active = [
    { id: "opening", group_id: "AH-S08", source_only_available: true },
    { id: "original", group_id: "Z-M00", source_only_available: true },
    { id: "details", group_id: "BG-S04", source_only_available: true },
    { id: "repeat", group_id: "AH-S08", source_only_available: true },
    { id: "edited", group_id: "AH-S08", source_only_available: true },
    { id: "locked", group_id: "BG-S04", source_only_available: false },
  ];
  assert.deepEqual(repeatedEffectsForReduction(active, new Set(["edited"])), ["repeat"]);
  assert.deepEqual(repeatedEffectsForReduction(active.slice(3), new Set(["edited"])), []);
});
