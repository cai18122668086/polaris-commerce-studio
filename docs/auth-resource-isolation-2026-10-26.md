# Authentication resource isolation follow-up (2026-10-26)

This follow-up fixes other request paths that could reproduce the inspiration
image incident: synchronous SQLAlchemy work blocked the ASGI event loop, and
storage waits retained scarce database connections.

- Announcement images load and detach their authorized metadata in a worker
  thread, returning the connection before reading storage.
- Admin log details materialize their complete database view before awaiting
  asset URL signing. Existing permission checks and response fields remain.
- Worker result uploads validate scope and fencing in a short read transaction.
  Workspace reads, asset commits, snapshot commits and completion run outside
  the event loop. Commit-time lease checks use the current transaction rather
  than acquiring a second connection, and refresh previously loaded lease state.
  Both local-worker and server-side snapshot callers use this path.
- Deliverable ZIP downloads detach their verified metadata before storage reads.
  Native detail downloads retain their original review/lineage checks, but use
  separate read snapshots for database lookups and offload pair pixel verification.
  ZIP writes run in worker threads. Archives spool above 8 MiB into anonymous
  temporary files on existing writable task storage, then stream in 64 KiB
  chunks. The 8 MiB threshold is per archive, not a total process memory bound.
  Failed builds and disconnected responses close their temporary files.

`read_snapshot` is exclusively for read-only work. It detaches loaded scalar
records and rolls back the read transaction; it must not wrap pending writes.
No schema, provider routing, authentication timeout or API contract changes are
required. The exported OpenAPI document remains identical (112 paths).

## Validation

The final selected suite passed 168 tests, including 14 new resource-isolation
cases. Coverage includes 48 waiting downloads/images, unrelated authentication
and health requests, single-connection worker persistence, stale fencing,
archive disk rollover, disconnect cleanup, damaged content and native archive
I/O with a preverified synthetic contract. Ruff passes for changed Python files;
Mypy passes for all 205 backend source files.

A separate broader run of API/storage/native-delivery suites had 92 passes and
16 failures. The failing native scenarios stopped during generation with
`AURORA_NATIVE_ATOMIC_CONTEXT_INVALID` / `Native review contracts differ from
the approved session`, before exercising the download changes. An unmodified
shared-repository representative test reproduces that same failure. The focused
native archive tests use preverified synthetic inputs and do not replace full
native generation-to-delivery validation. Preserve this local baseline limitation
in review and require the normal CI gates before integration.

The branch also contains the prior inspiration fix (`35c93ee`). Integration and
production rollout stay separate from the other chat's in-progress release.
