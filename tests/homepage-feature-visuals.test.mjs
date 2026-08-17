import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import { FEATURE_REGISTRY } from "../lib/feature-registry.ts";
import {
  HOME_FEATURE_VISUALS,
} from "../lib/home-feature-visuals.ts";

const root = process.cwd();
const assetDirectory = path.join(root, "public", "images", "homepage-features");
const utf8 = (file) => readFile(path.join(root, file), "utf8");

const EXPECTED_FEATURE_IDS = [
  "local-edit",
  "change-background",
  "reference-remix",
  "detail-pack",
  "domestic-main-image",
  "amazon-visual-suite",
];

const EXPECTED_RICH_VISUAL_IDS = EXPECTED_FEATURE_IDS.filter(
  (featureId) => featureId !== "domestic-main-image",
);

const EXPECTED_FILES = [
  "card-01-local-edit-after-v1.webp",
  "card-01-local-edit-before-v1.webp",
  "card-02-background-after-v1.webp",
  "card-02-background-before-v1.webp",
  "card-03-remix-after-v1.webp",
  "card-03-remix-before-v1.webp",
  "card-03-remix-reference-v1.webp",
  "card-04-detail-after-cover-v1.webp",
  "card-04-detail-after-long-v1.webp",
  "card-04-detail-before-v1.webp",
  "card-05-amazon-after-v1.webp",
  "card-05-amazon-before-v1.webp",
];

function webpDimensions(buffer) {
  assert.equal(buffer.toString("ascii", 0, 4), "RIFF");
  assert.equal(buffer.toString("ascii", 8, 12), "WEBP");
  const format = buffer.toString("ascii", 12, 16);

  if (format === "VP8X") {
    return {
      width: 1 + buffer.readUIntLE(24, 3),
      height: 1 + buffer.readUIntLE(27, 3),
    };
  }

  if (format === "VP8 ") {
    for (let offset = 20; offset < Math.min(buffer.length - 10, 60); offset += 1) {
      if (
        buffer[offset] === 0x9d &&
        buffer[offset + 1] === 0x01 &&
        buffer[offset + 2] === 0x2a
      ) {
        return {
          width: buffer.readUInt16LE(offset + 3) & 0x3fff,
          height: buffer.readUInt16LE(offset + 5) & 0x3fff,
        };
      }
    }
  }

  throw new Error(`Unsupported WebP header: ${format}`);
}

function mappedImages() {
  return Object.values(HOME_FEATURE_VISUALS).flatMap((visual) => {
    const images = [visual.before, visual.after];
    if (visual.kind === "remix") images.push(visual.reference);
    if (visual.kind === "detail-scroll") images.push(visual.reducedMotionCover);
    return images;
  });
}

test("the homepage grid covers all six one-click tasks without changing navigation", () => {
  const featured = FEATURE_REGISTRY.filter((feature) => feature.featured);
  assert.deepEqual(
    featured.map((feature) => feature.id),
    EXPECTED_FEATURE_IDS,
  );
  assert.deepEqual(Object.keys(HOME_FEATURE_VISUALS), EXPECTED_RICH_VISUAL_IDS);
  assert.deepEqual(
    featured.map((feature) => feature.route),
    [
      "/workspace/local-edit",
      "/workspace/product-image/change-background",
      "/workspace/reference-remix",
      "/workspace/detail-pack",
      "/workspace/domestic-main-image",
      "/workspace/amazon-visual-suite",
    ],
  );
});

test("all twelve production assets are WebP files with the declared stable dimensions", async () => {
  const files = (await readdir(assetDirectory)).sort();
  assert.deepEqual(files, EXPECTED_FILES);
  assert.equal(files.some((file) => file.toLowerCase().endsWith(".gif")), false);

  const images = mappedImages();
  assert.equal(images.length, 12);
  assert.deepEqual(
    images.map((image) => path.basename(image.src)).sort(),
    EXPECTED_FILES,
  );

  for (const image of images) {
    const buffer = await readFile(path.join(root, "public", image.src));
    assert.deepEqual(webpDimensions(buffer), {
      width: image.width,
      height: image.height,
    });
  }
});

test("homepage cards expose hover, keyboard, mobile-once, and reduced-motion states", async () => {
  const component = await utf8("components/tool-directory.tsx");
  const css = await utf8("app/focus-inspired.css");
  const mapping = await utf8("lib/home-feature-visuals.ts");
  const productionSource = `${component}\n${css}\n${mapping}`;

  assert.match(component, /data-feature-visual=\{HOME_FEATURE_VISUALS\[tool\.id\]\?\.kind\}/);
  assert.match(component, /new IntersectionObserver/);
  assert.match(component, /classList\.add\("is-mobile-played"\)/);
  assert.match(component, /observer\.unobserve\(entry\.target\)/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /:focus-within/);
  assert.match(css, /\.is-mobile-played/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /home-feature-card__image--detail-cover/);
  assert.match(css, /animation:\s*none !important/);
  assert.match(css, /grid-template-columns: repeat\(6, minmax\(0, 1fr\)\)/);
  assert.doesNotMatch(css, /home-feature-card:nth-child/);
  assert.doesNotMatch(component, /home-aurora-entry/);
  assert.doesNotMatch(component, /home-feature-card__remix-reference/);
  assert.doesNotMatch(productionSource, /\.gif\b/i);
});
