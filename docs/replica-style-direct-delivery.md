# Style generation and direct file delivery

`replication_method="style"` retains native product/reference intake, physical
panel analysis, safe style crops, facts, route planning, plan audit and ordered
product/reference bindings from `all-category-style-benchmark-still`.

The production provider factory in `execution.py` installs
`ReplicaDeliveryProvider`. Its style override replaces the old sequence
`record → pixel audit → revision → pixel audit → accept → global audit → finalize`
with generation and file delivery. No post-generation AI review or automatic
repair is called. The original Skill remains unchanged. The released exact v5
adapter and its dependencies are archived with their original binding; the
current exact v6 adapter has its own source binding and recovery policy.

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


## Unified evidence and analysis recovery

PR126 and PR127 compose through one `style-analysis-checkpoints.json` journal.
`replica_style_evidence.py` owns deterministic source/panel/step crop validation
and physical recrop proposals; it does not own workflow state or an independent
model cache. The analysis adapter persists early stages, uses the same hash-bound
request cache for crop reviews, and materializes all proposed crops before
computing review image hashes. A changed crop can never inherit an old pixel
review merely because its filename or stage name is unchanged.

The analysis policy binds the analysis adapter, physical evidence service and
native adapter sources. Old failed analysis contracts remain unchanged; explicit
plan correction records its parent snapshot hash and preserves the original
snapshot in private lineage. Existing style tasks with no durable checkpoint
require one explicit new diagnosis using their retained original material.

Crop review uses a crop-only patch contract. The server owns frozen panel,
source-step, narrative and semantic observations; the model returns only unit
changes, crop proposals and optional mechanisms. Omitted frozen fields are not
treated as rewritten observations. A final review must explicitly cover every
current unit and all eight safety flags. Partial proposals may create real crops
but cannot pass until the new pixels receive a complete review. Old safe flags
never fill missing review fields, and true unsafe verdicts remain failures.

Normal retry admits one narrowly scoped v2-to-v3 policy upgrade for the known
v2 source hash at a failed pre-generation crop review. It requires unchanged
inputs, native Skill source and hash-verified review state, with no jobs or
approved plan. The complete old snapshot, source observations, raw responses and
usage attribution remain preserved. New review requests use the v3 policy;
completed intake is not repeated. Other policy changes require diagnosis.


The compiler's `(path, reference_input_id)` de-duplication can lose a second
source-step binding when one job uses the same reviewed crop for multiple steps
within the same physical panel. The generation workspace adds a real,
byte-identical file alias only for a step that this actual job would otherwise
lose. Each alias preserves the canonical crop, source/bbox, original review and
SHA, and is marked as inherited identical pixels. No new visual PASS is created.
Separate jobs with one step continue to share the canonical crop. Cross-panel
misbinding still fails. Both generation-workflow and manifest copies receive the
same normalized manifest before any generation token is issued; the confirmed
workflow, route plan and source manifest remain unchanged.
