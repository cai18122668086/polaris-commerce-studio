# Paper template: mixed video and text scenes

The 52.24-second recorded case exposed two layout assumptions in `bihuo-09-v1`.
At 25 seconds, semantic slot 3 kept a narrow left-hand card even after the
previous card had exited. At 35 seconds, a text-only point inside a plan with
uploads inherited a full-size empty photo card and the overlapping person pose.

The host display adapter now uses the actual content of each scene. A single
landscape upload uses 972 pixels of the 1080-pixel canvas width; square and
portrait uploads retain their aspect ratio inside a bounded stage. A separate
heading and upper-right person window leave the complete upload unobstructed.
Text-only scenes use the existing compact paper panel and a separate left-hand
person window, including when other scenes in the same plan contain uploads.
The person moves before a new card arrives. Outgoing labels are suppressed
while changing between the media and text poses. Text-only points hold until
the next point or closing, with their original display events retained.

Captions retain their source text, glyph times and emphasis choices. Their
display uses safe word boundaries, up to two centered lines and a stable
baseline. Paper-colored backing and dark ink improve contrast. A narrow
material slot is no longer chosen from its ordinal index. Native bundle files,
catalog entries, source audio and saved planning responses are unchanged.

Validation before full-film rendering: 48 related tests passed, scoped Ruff and
Mypy passed. The recorded input produced 29 actual-case keyframes spanning all
five uploads and two text-only points, including entries, exits and handoffs.
Four additional portrait/square frames and three no-image frames passed.
The 36-frame report found no caption/heading intersection with the person and
kept all 25 native identities. No provider, recognition, video extraction or
full-film rendering was performed for that offline check.

Evidence root: `C:/tl/bihuo-paper-layout-20261115/`. The original movie remains
under `C:/tl/bihuo-ui-covers-20261114/recovered-film/`. Full-film verification and
publication are recorded separately in the final receipt in the new evidence
root. Existing white-capsule four-combination acceptance and unrelated template
checks are reused; this is not a claim that every template has been retested.
