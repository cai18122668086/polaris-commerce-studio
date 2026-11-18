// Preserve the observed live frontend and change only the template duration copy.
const fs = require("node:fs");
const path = "/app/components/video-studio/video-studio.tsx";
const before = "15 秒 · 自然讲述动作";
const after = "10 秒 · 自然讲述动作";
const source = fs.readFileSync(path, "utf8");
if (source.split(before).length !== 2 || source.includes(after)) {
  throw new Error("Unexpected live template duration label; inspect before rebuilding");
}
fs.writeFileSync(path, source.replace(before, after));
