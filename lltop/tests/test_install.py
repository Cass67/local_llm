import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"


class InstallTests(unittest.TestCase):
    def test_dry_run_prints_target_without_installing(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp)
            result = subprocess.run(
                [str(INSTALL), "--dry-run", "--prefix", str(prefix)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(prefix / "bin" / "lltop"), result.stdout)
            self.assertFalse((prefix / "bin" / "lltop").exists())

    def test_installs_executable_to_prefix_bin(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp)
            result = subprocess.run(
                [str(INSTALL), "--prefix", str(prefix)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            target = prefix / "bin" / "lltop"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(target.exists())
            self.assertTrue(target.stat().st_mode & 0o111)
            self.assertIn("installed", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
