import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import test from "node:test";

const manifest = JSON.parse(await readFile("lib/display-images.json", "utf8"));
const hero = ["/images/cases/olay-20261030/replica-07.png", "/images/cases/platform-v3/background-result.png", "/images/cases/history-20261030/asset_a47a47f308464d7ea2e928e8cc9f5c0c.png"];

test("registered public display variants preserve all originals and reduce the hero byte budget", async () => {
  let displayBudget = 0, originalBudget = 0;
  for (const [original, item] of Object.entries(manifest)) {
    assert.ok(original.startsWith("/images/"));
    const data = await readFile(`public${original}`);
    assert.equal(createHash("sha256").update(data).digest("hex"), item.originalSha256);
    for (const image of item.variants) {
      assert.match(image.src, /^\/images\/display\/[0-9a-f]{16}-\d+\.webp$/);
      const bytes = await readFile(`public${image.src}`);
      assert.equal(bytes.length, image.bytes);
      assert.equal(bytes.toString("ascii", 8, 12), "WEBP");
    }
    if (hero.includes(original)) {
      displayBudget += Math.max(...item.variants.map(image => image.bytes));
      originalBudget += data.length;
    }
  }
  assert.ok(hero.every(path => manifest[path]));
  assert.ok(displayBudget < 1_000_000);
  assert.ok(displayBudget < originalBudget / 10);
});
