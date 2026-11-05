"""Create a forward-only video long enough to avoid vendor auto-extension.

Overlapping dissolves connect the end of each forward copy to its beginning.
No source frames are reversed and no audio is modified or included.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.video_template_media import prepare_forward as prepare

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--seconds", type=float, required=True)
    args = parser.parse_args()
    print(prepare(args.source, args.target, args.seconds))
