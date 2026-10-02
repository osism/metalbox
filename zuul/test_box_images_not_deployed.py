"""Tests that zuul/box-images-not-deployed.yml matches the shipped box.

Run with: python3 -m unittest discover -s zuul
"""

import importlib.util
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
spec = importlib.util.spec_from_file_location(
    "check_box_images", HERE / "check-box-images.py"
)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

BASE_LIST = HERE / "vars" / "container-images-metalbox.yml"


def mirrored_paths():
    """The localhost:5000 references the base list's manager lists produce."""
    data = yaml.safe_load(BASE_LIST.read_text()) or {}
    return set(data.get("images_manager_external") or []) | {
        f"osism/{item}" for item in data.get("images_manager") or []
    }


class NotDeployedTableTest(unittest.TestCase):
    def setUp(self):
        self.table = check.load_not_deployed(check.NOT_DEPLOYED)
        self.data, self.refs = check.box_refs(ROOT)

    def test_box_renders_enough_images(self):
        self.assertGreater(len(self.refs), 5)

    def test_every_row_is_still_rendered(self):
        stale = sorted(set(self.table) - set(self.refs))
        self.assertEqual(
            [], stale, f"rows the box no longer renders, delete them: {stale}"
        )

    def test_every_unless_flag_exists(self):
        # Raises ValueError, failing the test, when a flag is not configured.
        check.excluded(self.table, self.data)

    def test_no_excluded_image_is_mirrored_at_its_rendered_tag(self):
        """Exact-ref only: vault and traefik are mirrored at older tags, which
        is dead weight, not a contradiction."""
        mirrored = mirrored_paths()
        both = sorted(
            f"{key}: {self.refs[key]}"
            for key in check.excluded(self.table, self.data)
            if str(self.refs[key]) in mirrored
        )
        self.assertEqual(
            [], both, "excluded but mirrored at exactly the rendered tag: " f"{both}"
        )


if __name__ == "__main__":
    unittest.main()
