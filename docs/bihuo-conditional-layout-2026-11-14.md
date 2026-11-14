# Conditional layout fixes with existing speech and planning

Baseline: production `8249c2d7a1dad0534bdf2fa830954aef52095106`.
The accepted white-capsule quartet and previous gallery/covers remain intact.
Evidence lives under `C:/tl/bihuo-condition-layout-20261114/`.

Four native layouts have deterministic display fixes:

- Application-window lecture: full step labels use measured lexical line breaks
  inside the horizontal no-image nodes. Two/three-line labels have additional
  vertical space, preserve punctuation and never truncate source wording. The
  provided-image vertical nodes receive their own measured reading width.
- Grass/sunlight: the first provided image keeps its native composition and
  motion. Summary text has an independent dark header above the sharp product
  image instead of white ink over embedded product copy. This header remains in
  screen coordinates during the original poster drift to avoid clipping.
- Orange scroll: without images, source-backed points hold until the next point
  or closing, in a compact text panel beside a larger presenter circle. All
  no-image phases use this layout instead of later empty photo-size cards. The
  progressive caption uses dark ink on the paper. Spoken cue and glyph times
  are unchanged; display hold events are recorded separately from original ones.
- Qingci: the opening presenter reserves space below the title/support and only
  returns after the title has exited. Material motion and identity timing remain
  native.

The frozen native bundles, registry, renderer and planning-contract identity
files are unchanged. A host display policy adds its version and exact source
SHA to the compiled payload and final receipt. The isolated execution scope
restores every native function on success or error. Old compiled payloads
without the policy retain their original behavior; a policy/source mismatch is
rejected rather than silently changing a compiled job. Saved raw responses,
plans, transcripts, image IDs and audio are not rewritten. This extends the
existing deterministic compilation bridge, without another provider request.

Regression checks cover long labels/reading bounds, retained source text and
FA clocks, header clearance through entry/exit, header containment, old payload
behavior and hook restoration. Visual checks use the existing 21.043-second
response across 14 supported option cases for these four templates, with entry,
settled, item handoff and closing frames. They do not repeat the accepted white
capsule quartet or claim acceptance of unrelated foreground-dependent styles.

Full-film verification is restricted to three representative cases: lecture
without images, grass/sunlight with images and a name card, orange scroll without
images and with a name card. Each source is already uploaded and FA-aligned.
Reuse the same encoded full film for preview/export/decode; do not rerender it
to collect another screenshot or request a new semantic plan.
