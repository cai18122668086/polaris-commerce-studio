# 青瓷古宅完整网站运行包

`compile_request(resolved, *, source_path, fonts, creative_options, ffmpeg="ffmpeg", size=(1080,1920))`; `render_mp4(cfg, output_dir)` returns final.mp4 and writes render-receipt.json including final_sha256. Optional render_frame returns RGB/9RGBA/meta. Host: Python3.12+, Pillow/numpy/OpenCV/FFmpeg. All package renderer/fonts/small geometry resources are relative.

Resolved MUST contain real `tokens[{id,text,start_ms,end_ms}]`, complete captions with first/last token IDs and semantic lines. Each character uses its actual containing FA token start; punctuation shares that token, no invented divided milliseconds. Full-token once/order validation. FA/voice stays unchanged; only final glyph settle is clipped to cue last visible frame.

Full native family: mint expansion/opening topic, street poster/lower park window, upward night takeover/topright window, return to large park window, book top-left strip reveal, second image right strip reveal/joint exit, city blur-clear, independent caption and final RGB fade. Existing first2 algorithms plus measured later landmark interpolation; exact author curves/fonts/alpha remain unknown. No person segmentation.

Actual material IDs and semantic start/end control media. No images leaves the large portrait and meaningful topic/captions; later unmatched book/city stages are omitted. Meaningful title/support may appear without images. Identity enabled+one supplied field works; two empty or disabled omits. Native titles/caption width constraints fail explicitly; planned lines fit as a unit, no silent truncation. More than two planned caption lines requires upstream semantic planning.

Actual full encoding: limited-source526 and clean57b526 x none/partial/provided. Source book/city use bounded native crops; window asset only observable strip, not recovered full author asset. Source-only inpaint masks/diffs are outside package, no repair pixels used on clean input. Current full101FA14cue case verified; arbitrary planner/effect approval and formal03/04/08 are not claimed. Website host does one final decode/clock validation; runtime avoids repeated full decode/per-frame hashes.
