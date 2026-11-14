# Template browsing, curated covers and render reuse

The previous production baseline is `c0ebe1819ed9aeca3190a7a6816d9cc2096d55aa`.
The accepted white-capsule four-combination regression remains authoritative at
`C:/tl/bihuo-live-four-combinations-20261114/final-regression-receipt.json`.
This change does not repeat its model requests, recognition or full-video tests.

The signed-in Bihuo smart-editing page was inspected on 2026-11-14 at
https://www.bihuoai.com/workspace/create/ai-tools/smart-editing . Its template
cards use independent portrait covers and explicit preview buttons. Its full
library has categories, search and an explicit selection action. Reference
covers were observed for composition only; they are not installed on Tengli.

The Tengli gallery now has an eight-style shortlist, a searchable full library,
two-line template names, visible selection and an independent larger preview.
Library choices can be cancelled without modifying the current template. Only
the opened preview mounts a sample video. Covers retain their complete portrait
composition, and broken image loads have an explicit style fallback.

`tools/curate_editing_template_covers.py` samples existing videos for review,
then requires a source SHA, exact time and written review reason for every
visible cover. It builds a new versioned example store, preserving all videos
and their hashes. It reuses covers whose choices have not changed. The current
batch has 34 reviewed covers; first-round candidates, explicit choices and the
final manifest/receipt are retained under
`C:/tl/bihuo-gallery-speed-20261114/`. No provider call or full-video encoding
is part of this workflow. Covers are representative sample frames; they are
not a promise that every optional combination has been visually accepted.

The catalog reuses media verification only while device, inode, size, mtime
and ctime remain unchanged. Every access still resolves the allowed root and
collection. The store remains read-only and workspace authorization is
unchanged. A replacement file is checked again even if its size and mtime match.
Local measurement across 34 existing examples, each video plus poster, fell
from 0.2474 s to 0.0134 s after warming (18.5x for file verification alone).
This is not an end-to-end page latency measurement.

The isolated full-suite renderer can reuse established pure `pilot.text_image`
rasters within a 32 MiB image budget. Each returned image is copied, preserving
later alpha and blur operations. The scope restores all aliases on success or
failure and never caches source frames, materials, clocks or layout decisions.
The native entry point and engine identity stay unchanged, permitting saved
responses and frozen plans to continue. An outer execution entry point adds the
cache and records both accelerator source hashes, elapsed time and hit/miss
counts in the receipt. This does not alter the immutable bundles.

In a local white-capsule comparison, 57 frames including transitions and a
continuous body segment were pixel-identical before and after reuse. Time was
23.719 s versus 21.746 s (1.091x); 148 hits and 21 misses used about 2.5 MiB.
This is a sampled native painting benchmark, not a whole-video latency claim.

Validation includes cache mutation/eviction/failure isolation, example tamper
and range/ownership tests, existing full-suite queue tests, type checks and
desktop/390px UI inspection. Search, large preview, template application and
mobile dialog containment were checked in a local fixture using the production
catalog and existing videos. No live generation action was invoked.

Remaining scope: other templates still need representative condition checks.
Do not turn the 26-template inventory into 104 live model submissions. Reuse
saved responses and approved components; prefer offline keyframes and select
only necessary representative full-film runs.

Release uses the existing four-role upgrade helper, pinned production base
images, a new read-only example store and rollback to the preceding examples
mount. Database schema, authentication and unrelated services are preserved.
