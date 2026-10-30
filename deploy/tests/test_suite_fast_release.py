"""A corrupt candidate must fail before stopping production workers."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


RELEASE_PATH = Path(__file__).resolve().parents[1] / "sister-fast-20261030/release.py"
SPEC = importlib.util.spec_from_file_location("suite_fast_release_test_target", RELEASE_PATH)
assert SPEC and SPEC.loader
RELEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RELEASE)


class CandidatePreflightTests(unittest.TestCase):
    def test_corrupt_candidate_does_not_stop_any_service(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(json.dumps({
                "bases": dict.fromkeys(RELEASE.ROLES, "original-image"),
            }))
            (root / "baseline.private.json").write_text(json.dumps({"protected": {}}))
            (root / "postgres.dump").write_bytes(b"backup")
            with (
                patch.object(RELEASE, "protected", return_value={}),
                patch.object(RELEASE, "inspect", return_value={"Image": "original-image"}),
                patch.object(RELEASE, "verify_candidate_files", side_effect=AssertionError("missing file")),
                patch.object(RELEASE, "compose") as compose,
            ):
                with self.assertRaisesRegex(AssertionError, "missing file"):
                    RELEASE.activate(root)
                compose.assert_not_called()


if __name__ == "__main__":
    unittest.main()
