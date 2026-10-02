"""Tests for zuul/check-container-image-tags.py.

Run with: python3 -m unittest discover -s zuul
"""

import contextlib
import importlib.util
import io
import re
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "check_container_image_tags", HERE / "check-container-image-tags.py"
)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

PLAYBOOK = HERE / "mirror-container-images.yml"
SOURCE_RE = re.compile(r"docker://\{\{ docker_registry \}\}/([a-z]+)/\{\{ item \}\}")
LOOP_LIST_RE = re.compile(r"\{\{\s*(images_[a-z0-9_]+)")


def copy_tasks():
    """Yield (task name, list variable, source prefix) for each image-list copy."""
    play = yaml.safe_load(PLAYBOOK.read_text())[0]
    for task in play["tasks"]:
        command = task.get("ansible.builtin.command") or {}
        cmd = command.get("cmd", "") if isinstance(command, dict) else ""
        if "skopeo copy" not in cmd or "loop" not in task:
            continue
        lst = LOOP_LIST_RE.search(task["loop"])
        if lst is None:
            continue  # not an image list, e.g. the latest runners
        source = SOURCE_RE.search(cmd)
        yield task["name"], lst.group(1), source.group(1) if source else None


class PrefixMapTest(unittest.TestCase):
    def test_every_copied_list_maps_to_its_source_prefix(self):
        found = list(copy_tasks())
        self.assertGreater(len(found), 5, "no copy tasks parsed out of the playbook")
        wrong = [
            f"  {name}: {lst} copies from {source!r}, "
            f"REGISTRY_PREFIX says {check.REGISTRY_PREFIX.get(lst)!r}"
            for name, lst, source in found
            if check.REGISTRY_PREFIX.get(lst) != source
        ]
        self.assertEqual([], wrong, "\n" + "\n".join(wrong))


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text)
        return path

    def test_references_use_source_and_prefix(self):
        path = self.write(
            "a.yml",
            "images_manager_external:\n  - library/redis:7\n"
            "images_manager:\n  - osism:latest\n",
        )
        refs, unmapped = check.collect([path], "registry.example")
        self.assertEqual(unmapped, [])
        self.assertEqual(
            sorted(refs),
            [
                "registry.example/dockerhub/library/redis:7",
                "registry.example/osism/osism:latest",
            ],
        )

    def test_same_reference_from_two_files_is_probed_once(self):
        a = self.write("a.yml", "images_manager:\n  - osism:latest\n")
        b = self.write("b.yml", "images_manager_stable:\n  - osism:latest\n")
        refs, _ = check.collect([a, b], "r")
        self.assertEqual(
            refs["r/osism/osism:latest"],
            ["a.yml:images_manager", "b.yml:images_manager_stable"],
        )

    def test_unmapped_key_is_reported(self):
        path = self.write("a.yml", "images_new:\n  - x:1\n")
        _, unmapped = check.collect([path], "r")
        self.assertEqual(unmapped, ["a.yml: images_new"])

    def test_unmapped_key_exits_2(self):
        path = self.write("a.yml", "images_new:\n  - x:1\n")
        with contextlib.redirect_stderr(io.StringIO()):
            rc = check.main(["--source-registry", "r", str(path)])
        self.assertEqual(rc, 2)

    def test_missing_file_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            rc = check.main(["--source-registry", "r", str(self.dir / "nope.yml")])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
