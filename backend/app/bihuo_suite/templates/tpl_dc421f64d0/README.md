# 银灰蜜影网站运行包

`runtime.py` exports `compile_request(resolved, *, source_path, fonts, creative_options, ffmpeg="ffmpeg", size=(1080,1920))` and `render_mp4(cfg, output_dir)`. The latter returns `final.mp4` and writes `render-receipt.json` including `final_sha256`. Optional `render_frame` returns RGB, 3 independent RGBA roles, and metadata.

Host requirements: Python >=3.12, Pillow, numpy, OpenCV and FFmpeg. All renderer code/fonts/small stage resources are relative package dependencies. Input source and output directory are supplied by host. No provider/model/FA invocation. Website supplies verified full semantic captions with native `time`, token IDs, and planned lines/emphasis. Width/line-capacity errors fail explicitly.

The complete style has whole portrait opening, independent title/optional vertical identity, phrase captions with semantic outgoing split, common blurred handoff, close portrait window on fixed gray stage, common window/caption motion, and final RGB fade. Caption/FA time is never remapped. Chapter and conclusion events choose visual transitions for variable-duration scripts. No native image slots: matched and unmatched uploads are all reported unused rather than inserted into unrelated frames. Identity `name_card`/`identity`: disabled or both empty omits the block; each field can stand alone.

Current real regression: clean57b source, 101 tokens/14 cues/21.043 seconds, 526 frames, full encode/decode. Original 351-frame reference context is separately assembled from frozen lossless layers; it remains a limited source recovery with unknown pixels beneath old text and unknown author font/FX/curves. Source patches are not packaged or used by the clean runtime. Bundle code does not call the archived whole engine.

The delivery entry is a callable style implementation, not a declaration of arbitrary planner/effect approval or formal03/04/08 acceptance. Root owns website task integration/deployment. Host validates final decode/clock once; production renderer avoids per-frame hashing and duplicate decoding.
