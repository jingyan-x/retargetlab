"""Exercise installer failure boundaries and read-only verification."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "skills/retargetlab/scripts/install_full.py"


def invoke(*args):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True
    )
    return result, json.loads(result.stdout)


def snapshot(root):
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


class InstallerBoundaries(unittest.TestCase):
    def test_existing_prefix_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "user-file").write_text("preserve this")
            before = snapshot(root)
            result, payload = invoke("--prefix", root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAILED")
            self.assertEqual(snapshot(root), before)

    def test_bad_archive_cannot_install_components(self):
        with tempfile.TemporaryDirectory() as folder:
            kit = Path(folder) / "wrong-kit.zip"
            kit.write_bytes(b"not the release")
            root = Path(folder) / "installation"
            result, payload = invoke("--prefix", root, "--kit", kit)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAILED")
            self.assertEqual(
                json.loads((root / "installation.json").read_text())["status"], "INCOMPLETE"
            )
            self.assertFalse((root / "process").exists())
            self.assertFalse((root / "reader").exists())
            self.assertEqual(kit.read_bytes(), b"not the release")

    def test_check_of_partial_installation_does_not_repair_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "installation.json").write_text(json.dumps({"status": "INCOMPLETE"}))
            before = snapshot(root)
            result, payload = invoke("--prefix", root, "--check")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAILED")
            self.assertEqual(snapshot(root), before)

    @unittest.skipUnless(
        os.environ.get("RETARGETLAB_INSTALL_PREFIX"), "fresh full runtime required"
    )
    def test_full_check_preserves_installed_files(self):
        root = Path(os.environ["RETARGETLAB_INSTALL_PREFIX"])
        before = snapshot(root)
        result, payload = invoke("--prefix", root, "--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(payload["full_runtime"])
        self.assertEqual(set(payload["checks"]), {"process", "reader"})
        self.assertEqual(snapshot(root), before)


if __name__ == "__main__":
    unittest.main()
