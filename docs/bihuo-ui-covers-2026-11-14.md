# Template browsing, material interaction and saved-response recovery

Production baseline: `747be091df31f1d80725c11365bb19cc7061a49d` (PR180).

The signed-in Bihuo smart-editing page was inspected at
https://www.bihuoai.com/workspace/create/ai-tools/smart-editing . The reference
separates template selection from preview, offers search, categories and
favorites in its library, and exposes material search/type filters with an
explicit selected count. No reference images or videos are installed here.

The gallery now uses four composition categories and short visual descriptions,
workspace-local favorites, complete portrait covers, and a larger preview with
previous/next navigation. Opening or cancelling the library leaves the current
selection intact; applying a template remains explicit. Existing project films
can be viewed alongside installed examples. Only the active preview loads its
sample video; playback starts muted, with normal audio controls available.

The materials area separates selection from media preview, offers image/video
filters and search, shows selected counts, and provides a keyboard-accessible
file picker with drag and drop. Existing creative-image import and evidenced
interaction records remain available. Uploads retain the existing request ID
on retries. The preview uses an object URL for a selected local image and revokes
it on replacement/unmount. Video tiles do not mount players; opening one mounts
the active player. New controls have their own scoped neutral/red styles instead
of inheriting legacy purple panel controls.

The existing 34 explicitly reviewed covers are retained. Six choices (14, 15,
32, 36, 47, 48) now show their stable body compositions instead of similar full
screen presenter openings: green light window, blue-white image card, warm
vertical composition, silver frame, layered grid and circular presenter/material
layout. The source SHA, exact timestamp and individual reason are stored under
`C:/tl/bihuo-ui-covers-20261114/cover-selections.json`. Original video hashes
are unchanged. This work does not generate an image, request a model or encode
a new template sample.

During this work, the user's latest 52.24-second task was found stopped after
recognition, at saved-response validation. The captured response omitted a
line break in the opening ASCII/Chinese cue and used paragraphs as chapter
labels. The Bihuo adapter supplies missing line breaks only at safe token/word
boundaries, keeping emphasis spans intact. Long chapter labels use their first
complete recorded clause; captions still include every source word exactly
once. The original provider capture and immutable contracts remain unchanged.
The strict validator runs again after fitting and still rejects missing words,
unknown IDs, unsafe explicit breaks and crossing highlights.

The native FA bridge also removes only Apple-inserted ASCII separators from
rendered Bihuo cue text and rebinds highlights to exact recorded characters.
Actual spaces inside recorded tokens are preserved. Audio and token times do
not change. Paper-template material headings occupy independent reading areas,
without the redundant example label or overlap with upper captions.

The primary action now distinguishes recognition, planning and rendering. A
render in progress opens its existing task; the hint explains that preview
arrives automatically and that HD export needs one confirmation, without a
second render. Failures are described as interruptions instead of progress. A failed or cancelled
job with a saved response makes the primary button retry that same job, rather
than prepare a new paid planning request. Uncertain submissions remain blocked.

Validation and recovery receipts, keyframes and UI screenshots are stored under
`C:/tl/bihuo-ui-covers-20261114/`. The white-capsule four-combination acceptance
and the prior representative full-film checks are reused; do not repeat them.
Only the interrupted user-requested task is resumed from its saved response.
