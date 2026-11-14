# Images and video in supplemental material slots

The upload API already stores owner-scoped MP4, MOV and WebM alongside JPG,
PNG and WebP. Most Bihuo templates were restricted to images by the picker,
planning snapshot, request filtering and frozen native image-slot compilers.

Image-capable suite cards now expose effective video support without changing
the byte-pinned catalog or native identities. The planner receives the real
video ID, SHA and measured duration, alongside images. Pure text templates keep
their existing composition; interactive-evidence uploads remain image records.

The three native video-capable window/capsule recipes retain their existing
video path. Other image-capable recipes consume a measured 25fps frame stream
through their own native media slots. Frame extraction is bounded by source and
speech duration, preserves aspect ratio within 1080x1920 and excludes clip audio.
Each concrete slot starts at its native display event, from the beginning of
the supplied clip; short clips hold their last frame. A unique frame path
advances the established image samplers and caches rather than freezing the
first frame. The source speech remains the only soundtrack.

The raw response, FA tokens, original plan, image assignments, source hashes and
spoken timing are retained. Compiled input and render receipts record the host
video policy version/source SHA, video IDs, source hashes, frame hashes, slot
starts, muted clip audio and hold behavior. The execution scope restores native
functions on failure and success. Old payloads and image-only rendering do not
enter this adapter. Existing model responses and already encoded full films are
reused; video support is not a reason to regenerate their plans or videos.

Validation covers actual video extraction/cache reuse, frame progression and
EOF hold, all three native entrypoint families, source/frame tampering,
owner-scoped upload/preparation and real video metadata in the full-script
request. Offline mixed image/video checks use one explicit synthetic motion
pattern; it is a technical fixture, not product footage or aesthetic acceptance.
Foreground-dependent styles retain their existing matte dependency; no new
inference is invoked simply to broaden these checks.

The combined release also includes the four previously verified conditional
layout fixes. Their three 21.043-second production full films are retained, each
with one render attempt. CI's maximum backend shard passed all 1436 tests in
42m34s, then crossed the previous 45-minute job deadline during process cleanup.
The deadline is 60 minutes to allow its existing setup/cleanup to complete; no
checks or tests are removed. The video tests extend existing test files, keeping
the previous shard allocation stable. A tuple annotation fixes the same existing
type inference under the fresh local checkout without changing runtime behavior.
