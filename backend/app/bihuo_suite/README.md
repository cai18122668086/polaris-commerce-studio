# Whole-template runtimes

`catalog.json` declares the actual 25 additional video styles. The previously
deployed `apple-minimal-v1` remains the first style. Only installed, hash-valid,
enabled bundles are offered in the website catalog.

Each bundle implements `compile_request` and `render_mp4`; its manifest binds
the Python implementation, native parameters and fonts. Install a new bundle
with `tools/install_bihuo_template.py`. Encoded examples belong in the separately
versioned, read-only template-example store, rather than Git or user projects.

All styles use the existing durable planning/render queues. One full-script
semantic request resolves actual transcript token IDs. Preparation is free;
generation retains the existing explicit paid action, frozen inputs, ownership
checks, uncertain-outcome handling and idempotency. No per-frame provider calls
or automatic paid retry is added.

Body points and feature phrases are independently ordered by their actual word
spans. They may interleave in Bihuo templates; Apple's sequential feature-card
constraint remains unchanged. Saved responses can be revalidated without a new
provider request. Already accepted plans retain their original compilation.

Capabilities drive the form and planning input. Name cards are optional and
hidden when disabled or empty; supported adapters permit either name or
description alone. Styles without native image slots do not accept selected
project materials. Other styles adjust the composition to the materials that
actually match the recorded speech; empty uploads do not create blank slots.

Native execution uses 1080×1920 at 25fps. Other supported 9:16 sources are
prepared once by the worker, preserving the original transcript clock and a
hash-bound original/prepared-source receipt. Original bytes are never replaced.
Foreground styles use the existing installed, pinned local model and a
source/model-bound cache. Public creative fields cannot select model/cache paths.

The renderer runs in its existing isolated process. The normal delivery path
fully decodes the output once and checks duration, dimensions and H.264 encoding.
These operational checks do not certify aesthetic approval or formal reference
reconstruction gates; historical project approvals remain separate records.
