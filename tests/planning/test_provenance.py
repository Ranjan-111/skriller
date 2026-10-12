import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "provenance", Path(__file__).resolve().parents[2] / "scripts/provenance.py"
)
provenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provenance)


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = self.root / "reference/Scrapling-main"
        (source / "scrapling").mkdir(parents=True)
        (source / "scrapling/__init__.py").write_text("VALUE = 1\n")
        (source / "LICENSE").write_text("BSD 3-Clause License\n")
        self.target = provenance.import_project("scrapling", self.root)

    def test_copy_and_registered_patch(self):
        provenance.verify_project(self.target, self.root)
        (self.target / "scrapling/__init__.py").write_text("VALUE = 2\n")
        provenance.record_patch(
            self.target, ["scrapling/__init__.py"], "Regression-backed adaptation"
        )
        provenance.verify_project(self.target, self.root)

    def test_unregistered_change_fails(self):
        (self.target / "scrapling/__init__.py").write_text("VALUE = 3\n")
        with self.assertRaisesRegex(ValueError, "Unregistered patch"):
            provenance.verify_project(self.target, self.root)

    def test_missing_notice_and_unregistered_source_fail(self):
        (self.target / "scrapling/extra.py").write_text("VALUE = 3\n")
        with self.assertRaisesRegex(ValueError, "Unregistered Python"):
            provenance.verify_project(self.target, self.root)
        (self.target / "LICENSE").unlink()
        with self.assertRaisesRegex(ValueError, "LICENSE"):
            provenance.verify_project(self.target, self.root)


if __name__ == "__main__":
    unittest.main()
