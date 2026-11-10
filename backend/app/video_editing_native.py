"""Run the unmodified adapter with a task-local copy permission compatibility fix.

The native exporter copies a font twice (layout evidence, then final captions).
shutil.copy2 carries the read-only package file mode onto its task copy; Windows
then refuses the second copy. Only instance copies become writable. Original
bytes, native draw functions and checks remain unchanged.
"""

import argparse
import os
import runpy
import sys
from pathlib import Path

from .motion_browser_originals import (
    BROWSER_ORIGINALS_KEY,
    RENDER_GROUPS,
    browser_original_evidence,
    require_browser_originals,
)
from .motion_library import atomic_json, read_json
from .video_editing_native_compat import install
from .video_editing_native_frame_clock import install_native_frame_clocks
from .video_editing_native_layout import install_native_role_review
from .video_editing_native_shot_recovery import install_shot_recovery
from .video_editing_subtitle_sound_clock import install_subtitle_sound_clock
from .video_editing_unified_alpha import (
    install_unified_sequence_audit,
    stage_unified_sequences,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument(
        "--command", choices=["check", "export", "render-group", "plan"], required=True
    )
    parser.add_argument("--kind", choices=["episode", "group"], default="episode")
    args = parser.parse_args()
    package, root = args.package.resolve(), args.instance.resolve()
    if root.is_relative_to(package):
        raise ValueError("Task outputs must be outside the original library")
    input_file = root / ("episode.json" if args.kind == "episode" else "job.json")
    if args.command != "plan":
        native_input = read_json(input_file)
        shots = native_input["shots"] if args.kind == "episode" else [native_input]
        original_shots = [
            (index, shot)
            for index, shot in enumerate(shots)
            if shot["group_id"] in RENDER_GROUPS
        ]
        if original_shots:
            binding_path = root / "bindings.json"
            frozen = (
                read_json(binding_path).get(BROWSER_ORIGINALS_KEY)
                if binding_path.is_file()
                else None
            )
            groups = {
                group["id"]: group
                for group in read_json(package / "catalog/groups.json")["groups"]
            }
            for index, shot in original_shots:
                selected = require_browser_originals(
                    package,
                    groups[shot["group_id"]],
                    shot["config"],
                    frozen,
                    root / "browser-originals",
                )
                if selected and args.command in {"export", "render-group"}:
                    output = (
                        root / "renders" / f"{index:03}-{shot['group_id']}.mp4"
                        if args.kind == "episode"
                        else root
                        / shot.get("output", f"outputs/{shot['group_id']}.mp4")
                    ).resolve()
                    if not output.is_relative_to(root):
                        raise ValueError("Native browser output leaves its task")
                    if output.is_file():
                        receipt = read_json(output.with_suffix(".receipt.json"))
                        if receipt.get("native", {}).get(
                            BROWSER_ORIGINALS_KEY
                        ) != browser_original_evidence(selected):
                            raise ValueError(
                                "Cached browser output has different originals"
                            )
    install(package, root)
    install_native_frame_clocks(package, root)
    # Original adapter launches original Python workers. Apply the same narrow
    # copy-mode rule at Python startup there, without editing their source.
    compatibility = root / "python-startup"
    compatibility.mkdir(exist_ok=True)
    (compatibility / "sitecustomize.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "from app.video_editing_native_compat import install\n"
        "from app.video_editing_native_compat import isolate_native_matte_cache\n"
        "from app.video_editing_native_compat import install_native_opening_validator\n"
        "from app.video_editing_native_font_maps import install_native_font_maps\n"
        "from app.video_editing_native_frame_clock import "
        "install_native_frame_clocks\n"
        "from app.video_editing_hypit_strips import install_native_strips\n"
        "from app.video_editing_browser_live import install_live_card_export\n"
        "from app.video_editing_browser_live import install_fruit_list_export\n"
        "from app.video_editing_browser_rotation import install_rotation_export\n"
        "from app.video_editing_browser_original_transport import ("
        "install_browser_originals)\n"
        "from app.video_editing_line_branch import install_native_line_branch\n"
        "from app.video_editing_question_branch import install_native_question_branch\n"
        "package = Path(os.environ['TENGLI_NATIVE_PACKAGE'])\n"
        "root = Path(os.environ['TENGLI_NATIVE_INSTANCE'])\n"
        "install(package, root)\n"
        "try:\n"
        "    install_native_frame_clocks(package, root)\n"
        "    isolate_native_matte_cache(package, root)\n"
        "    install_native_opening_validator(package, root)\n"
        "    install_native_font_maps(package, root)\n"
        "    install_native_strips(package, root)\n"
        "    install_native_question_branch(package, root)\n"
        "    install_live_card_export(package, root)\n"
        "    install_fruit_list_export(package, root)\n"
        "    install_rotation_export(package, root)\n"
        "    install_browser_originals(package, root)\n"
        "    install_native_line_branch(package, root)\n"
        "except Exception as error:\n"
        "    raise SystemExit('Unable to prepare native shot adapter') from error\n",
        encoding="utf-8",
    )
    os.environ["TENGLI_NATIVE_PACKAGE"] = str(package)
    os.environ["TENGLI_NATIVE_INSTANCE"] = str(root)
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [
            str(compatibility),
            str(Path(__file__).resolve().parents[1]),
            os.environ.get("PYTHONPATH", ""),
        ]
    )
    sys.argv = [
        str(package / "adapter.py"),
        args.command,
        "--input",
        str(input_file),
        "--instance",
        str(root),
        "--bindings",
        str(root / "bindings.json"),
        "--report",
        str(root / ("native-" + args.command + ".json")),
    ]
    try:
        sequences = stage_unified_sequences(package, root, args.kind)
        if args.kind == "episode":
            install_unified_sequence_audit(package, sequences)
        if args.command == "export":
            install_native_role_review(package, root)
            install_shot_recovery(package, root)
            install_subtitle_sound_clock(package, root)
        runpy.run_path(str(package / "adapter.py"), run_name="__main__")
    finally:
        atomic_json(
            root / "runtime-compatibility.json",
            {
                "adapter_version": "task-copy-permissions/2",
                "native_sources_changed": False,
                "copy_events": "compatibility/copies-*.json",
            },
        )


if __name__ == "__main__":
    main()
