import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/publish-export.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { csvFileName, exportRows, safeName, toCsv, topicsOf } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

const items = [
  { id: "c", position: 2, stage: "finishing", publish_title: "还没成片", publish_body: "x", cover_asset_id: null },
  { id: "b", position: 1, stage: "done", publish_title: "手比脸老得快？做美甲6年", publish_body: "第一行，带逗号\n第二行 \"引号\"\n#美甲 #护手 #美甲", cover_asset_id: "cov-b" },
  { id: "a", position: 0, stage: "done", publish_title: "开店第三年/冬天最该备的:", publish_body: "冬天来了 #开店", cover_asset_id: null },
];

test("只导出已完成的条目，按批次内顺序编号，中文文件名", () => {
  const rows = exportRows(items);
  assert.deepEqual(rows.map(row => row.itemId), ["a", "b"]);
  assert.equal(rows[0].video, "01-开店第三年 冬天最该备的.mp4");
  assert.equal(rows[0].cover, "");
  assert.equal(rows[1].video, "02-手比脸老得快？做美甲6年.mp4");
  assert.equal(rows[1].cover, "02-手比脸老得快？做美甲6年-封面.jpg");
});

test("文案一字不差：标题、正文原样进表", () => {
  const rows = exportRows(items);
  assert.equal(rows[1].title, items[1].publish_title);
  assert.equal(rows[1].body, items[1].publish_body);
  assert.equal(rows[1].topics, "#美甲 #护手");
});

test("CSV：带 BOM、表头中文、引号与换行转义后能还原", () => {
  const csv = toCsv(exportRows(items));
  assert.ok(csv.startsWith("﻿序号,标题,发布正文,话题,视频文件名,封面文件名\r\n"));
  assert.ok(csv.includes('"第一行，带逗号\n第二行 ""引号""\n#美甲 #护手 #美甲"'));
  // 最小 CSV 解析，确认还原后与保存的正文完全一致
  const parse = text => { const out = [[]]; let cur = "", q = false; for (let i = 0; i < text.length; i++) { const ch = text[i];
    if (q) { if (ch === '"' && text[i + 1] === '"') { cur += '"'; i++; } else if (ch === '"') q = false; else cur += ch; }
    else if (ch === '"') q = true; else if (ch === ",") { out.at(-1).push(cur); cur = ""; } else if (ch === "\r") {} else if (ch === "\n") { out.at(-1).push(cur); cur = ""; out.push([]); } else cur += ch; }
    return out.filter(row => row.length > 1); };
  const table = parse(csv.slice(1));
  assert.equal(table.length, 3);
  assert.equal(table[2][1], items[1].publish_title);
  assert.equal(table[2][2], items[1].publish_body);
  assert.equal(table[1][2], items[2].publish_body);
});

test("文件名清理", () => {
  assert.equal(safeName('a/b\\c:d*e?f"g<h>i|j'), "a b c d e f g h i j");
  assert.equal(safeName("   "), "作品");
  assert.equal(safeName("结尾有点..."), "结尾有点");
  assert.equal(Array.from(safeName("长".repeat(60))).length, 40);
  assert.equal(topicsOf("没有话题"), "");
  assert.equal(csvFileName("11月28日 14:05", 3), "发布清单-11月28日 14 05-3条.csv");
});
