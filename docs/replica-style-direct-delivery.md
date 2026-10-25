# Style generation and direct file delivery

`replication_method="style"` retains native product/reference intake, physical
panel analysis, safe style crops, facts, route planning, plan audit and ordered
product/reference bindings from `all-category-style-benchmark-still`.

The production provider factory in `execution.py` installs
`ReplicaDeliveryProvider`. Its style override replaces the old sequence
`record → pixel audit → revision → pixel audit → accept → global audit → finalize`
with generation and file delivery. No post-generation AI review or automatic
repair is called. The original Skill and shared provider files remain byte
identical because the released exact v5 protocol hashes those dependencies.
Exact continues through its existing implementation and binding.

The original `workflow.json`, route plan, inputs, facts and historical verdicts
remain immutable. `style-direct-session.json` records `GENERATED` and
`NOT_REVIEWED` separately. The native request compiler and image handoff run in
a separate generation workspace with honest `generated` markers for completed
targets. This preserves sequential compilation without inventing audit passes.

File checks follow the style contract: singles require their native route
dimensions; detail masters use the existing absolute 0.01 ratio tolerance,
equal-height splits, and G01's adopted screen ratio. There is no new minimum
edge or total-call/time budget. Corrupt images, wrong geometry, changed hashes,
missing files, or wrong order/count stop delivery. Detail output uses native
equal-height crops; single output retains original bytes.

Normal HTTP retries require the same workspace, document, confirmed plan,
source version, original assets and facts. Persisted snapshots verify every
JSON and object byte. Known canvases, including returned but unrecorded images,
are reused; an invoked request with unknown outcome cannot be dispatched again.
An explicitly created retry job may request an unfinished target again after a
known provider rejection, retaining the rejected token and all completed images.
The original execution snapshot and AI FAIL/PASS records remain unchanged.
Progress and usage metadata report generated counts and zero reviewed/accepted
images, and reuse the existing UI's “未进行自动审图” presentation.

Synthetic tests cover both native single/pair branches, format failures,
planning gates, immutable history, changed bindings, unknown results, returned
but unrecorded requests, deletion of temporary files, and a real HTTP/worker
retry through durable storage. They do not claim live visual quality.

The style analysis adapter (`replica_style_analysis.py`) verifies generation
reference coverage before page planning. Every observed source content step
must bind a reviewed physical crop from its corresponding source panel. Crop
origin, coordinates and actual bytes are server-recorded. Model-proposed crop
corrections are materialized and their new pixels receive a fresh pre-generation
review; changing flags or relabeling another panel's swatch cannot fill a gap.
The original native crop compiler, factual registration and plan audit remain
mandatory. Full analysis panels still supply global layout evidence, while safe
generation crops supply supplementary type, material and action details.

This addresses an observed failure: a twelve-step live plan had only four safe
crops bound to four steps. Eight steps lacked generation references, while the
old revision loop only rewrote page plans. The immutable native generation
compiler would also reject those missing bindings. Tests reproduce that failure
and verify corrected bindings with the unchanged native compiler.

Failed crop, facts and plan stages retain hash-verified native snapshots and a
style cursor. Normal retry/revision restores original inputs and the failed
stage without repeating completed intake or source observations. New crop
bytes must be reviewed again. Explicit plan revision retains prior FAIL
contracts and re-runs the real plan audit; it does not adopt an old rejection as
PASS. Legacy failed sessions without a durable checkpoint are not claimed to
support that restoration.
