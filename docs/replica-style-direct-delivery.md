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
