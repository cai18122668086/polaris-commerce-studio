# 简洁白卡 / Whitecard production runtime

Host API: `compile_request(resolved, *, source_path, fonts, creative_options, ffmpeg="ffmpeg", size=(1080,1920))`, then `render_mp4(cfg, output_dir)` returns `final.mp4` and writes a light receipt.

This package has no fixed source, caption text, FA clocks or drive dependency. The host supplies the full resolved plan and real source. Runtime inspects native frame count/rate and samples to 25fps. Captions remain on supplied absolute FA clocks. `materials[].spoken_span` determines semantic visibility; a legacy extended `end` is not treated as spoken FA. Images contain the complete original image with blurred padding. Each matching slot is retained even when asset IDs repeat. The current native slot is an image slot; video/SVG inputs are rejected.

`creative_options.material_mode="none"` really clears images. `selected_asset_ids` restricts matching IDs. Meaningful chapters/features/points can still form text-only evidence cards; `information_enabled=false` removes these text roles. Missing content leaves the original room video available. The native template has no independent identity/title badge; empty, disabled, name-only, description-only identity requests are explicitly aliases. No identity is inferred. Full captions are always independent. Text-card capacity is explicit and never silently cropped.

Mechanisms: original-environment circle -> upper rounded room window with primary evidence; later slanted room and yellow backer with variable meaningful evidence cards; shared foreground compression/reopening selected in a real caption gap, then large room return and end fade. It does not require a head matte. All glyphs/materials/room windows are editable layers in renderer.render(..., roles=True).

Dependencies: Python 3.12+, Pillow, numpy, OpenCV, ffmpeg/ffprobe. `vendor` is a local frozen copy of the previously approved V02/media/typography helpers, not an installed engine. Bundled body.otf is the original Source Han Sans CN Bold used by the approved chain; caller fonts override it. Native author raw, exact native font/curve/UV remain unavailable; the source reference suffix uses disclosed same-source isolated finished room/card pixels. This clean runtime does not carry those source recovery assets.

This is a complete production application candidate. It does not declare formal 03/04/08 gate acceptance or new user visual approval. The older first2 approval and this full-suite implementation are distinct.
