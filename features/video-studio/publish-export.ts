/**
 * B13「导出这一批」（小版本）：一张总表（CSV）+ 逐个下载视频与封面。
 * 只导出已完成（stage=done）的条目；文案原样取自作品条目（成片页保存的 publish_title / publish_body），一字不改。
 */
export type ExportItem = { id: string; position: number; stage: string; publish_title: string; publish_body: string; cover_asset_id?: string | null };
export type ExportRow = { index: number; title: string; body: string; topics: string; video: string; cover: string; itemId: string; coverId: string | null };

/** 文件名里不能出现的字符换成空格；去掉首尾空白和结尾的点；最长 40 个字。空了就用「作品」。 */
export function safeName(text: string): string {
  const cleaned = Array.from(text.replace(/[\\/:*?"<>|\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").trim()).slice(0, 40).join("").trim().replace(/[.\s]+$/, "");
  return cleaned || "作品";
}

/** 正文里的话题（#xxx），按出现顺序去重，用空格连起来。 */
export function topicsOf(body: string): string {
  return [...new Set(Array.from(body.matchAll(/#[^\s#]+/gu), match => match[0]))].join(" ");
}

export function exportRows(items: ExportItem[]): ExportRow[] {
  const done = items.filter(item => item.stage === "done").sort((a, b) => a.position - b.position);
  const width = Math.max(2, String(done.length).length);
  return done.map((item, i) => {
    const index = i + 1;
    const base = `${String(index).padStart(width, "0")}-${safeName(item.publish_title)}`;
    return { index, title: item.publish_title, body: item.publish_body, topics: topicsOf(item.publish_body), video: `${base}.mp4`, cover: item.cover_asset_id ? `${base}-封面.jpg` : "", itemId: item.id, coverId: item.cover_asset_id ?? null };
  });
}

const cell = (value: string | number) => {
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

/** 带 BOM 的 UTF-8 CSV（Excel/WPS 直接打开不乱码），CRLF 换行；正文里的换行保留在引号内。 */
export function toCsv(rows: ExportRow[]): string {
  const head = ["序号", "标题", "发布正文", "话题", "视频文件名", "封面文件名"];
  const lines = [head, ...rows.map(row => [row.index, row.title, row.body, row.topics, row.video, row.cover])].map(line => line.map(cell).join(","));
  return `﻿${lines.join("\r\n")}\r\n`;
}

/** 「发布清单-11月28日-3条.csv」 */
export function csvFileName(batchLabel: string, count: number): string {
  return `${safeName(`发布清单-${batchLabel}-${count}条`)}.csv`;
}
