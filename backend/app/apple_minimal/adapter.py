"""Portable local entry for the Motion-style package; no application account needed."""

import argparse
import json
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from apple_minimal.render import render
else:
    from .render import render


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "export"])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = json.loads(args.input.read_text(encoding="utf8"))
    if config.get("schema_version") != "apple-minimal-render/1":
        raise ValueError("Unsupported composition contract")
    width, height = config["size"]
    if abs(width / height - 9 / 16) > 0.001:
        raise ValueError("This release supports portrait9:16")
    if config["fps"] != 25 or not 0 < config["duration"] <= 600:
        raise ValueError("Invalid voice timeline")
    for path in [config["source"], *config["fonts"].values()]:
        if not Path(path).is_file():
            raise ValueError("A declared input file is unavailable")
    if args.command == "check":
        print("Composition inputs available; no render or visual approval implied.")
        return
    if args.output is None:
        parser.error("export requires --output")
    if args.output.resolve().is_relative_to(Path(__file__).resolve().parent):
        raise ValueError("Render output must stay outside the template package")
    render(config, args.output)


if __name__ == "__main__":
    main()
