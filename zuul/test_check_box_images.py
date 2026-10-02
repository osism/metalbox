"""Tests for zuul/check-box-images.py against fixture configurations.

Run with: python3 -m unittest discover -s zuul
"""

import contextlib
import importlib.util
import io
import tempfile
import unittest
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "check_box_images", HERE / "check-box-images.py"
)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

IMAGES = """\
---
ara_server_tag: "1.7.5"
ara_server_image: "{{ docker_registry_ansible|default('registry.osism.tech') }}/osism/ara-server:{{ ara_server_tag }}"
redis_tag: "7.4.7-alpine"
redis_image: "{{ docker_registry|default('registry.osism.tech/dockerhub') }}/library/redis:{{ redis_tag }}"
vault_tag: "1.21.0"
vault_image: "{{ docker_registry|default('registry.osism.tech/dockerhub') }}/hashicorp/vault:{{ vault_tag }}"
"""

HOMER = "homer_image: ghcr.io/bastienwirtz/homer:v25.10.1\n"

REGISTRIES = (
    "docker_registry: localhost:5001\ndocker_registry_ansible: localhost:5001\n"
)

TABLE = """\
vault_image:
  reason: disabled
  unless: enable_vault
"""


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_urlopen(present, error=None):
    """urlopen stand-in: 200 for URLs of present refs, 404 otherwise."""

    def urlopen(request, timeout):
        if error is not None:
            raise error
        if request.get_method() != "HEAD":
            raise AssertionError("expected a HEAD request")
        if not request.full_url.startswith("http://localhost:5000/v2/"):
            raise AssertionError(f"unexpected registry: {request.full_url}")
        for ref in present:
            repository, tag = ref.rsplit(":", 1)
            if request.full_url.endswith(f"/v2/{repository}/manifests/{tag}"):
                return FakeResponse()
        raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)

    return urlopen


ALL = ["osism/ara-server:1.7.5", "library/redis:7.4.7-alpine"]


class MainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.write("manager/images.yml", IMAGES)
        self.write("manager/configuration.yml", "enable_vault: false\n")
        self.write("manager/group_vars/all/registries.yml", REGISTRIES)
        self.table = self.root / "table.yml"
        self.table.write_text(TABLE)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative, text):
        path = self.root / "environments" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def run_main(self, present, error=None):
        out, err = io.StringIO(), io.StringIO()
        argv = ["--registry", "localhost:5000", "--configuration", str(self.root)]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = check.main(argv, fake_urlopen(present, error), self.table)
        return rc, out.getvalue(), err.getvalue()

    def test_all_present_exits_0(self):
        rc, out, _ = self.run_main(ALL)
        self.assertEqual(rc, 0)
        self.assertIn("2 of 2 images present", out)

    def test_missing_image_exits_1_and_names_it(self):
        rc, out, _ = self.run_main(ALL[:1])
        self.assertEqual(rc, 1)
        self.assertIn("MISSING library/redis:7.4.7-alpine", out)

    def test_path_in_registry_variable_is_queried(self):
        self.write(
            "manager/group_vars/all/registries.yml",
            "docker_registry: localhost:5001\n"
            "docker_registry_ansible: localhost:5001/custom\n",
        )
        rc, out, _ = self.run_main(ALL)
        self.assertEqual(rc, 1)
        self.assertIn("MISSING custom/osism/ara-server:1.7.5", out)

    def test_registry_outside_the_box_exits_2(self):
        self.write(
            "manager/group_vars/all/registries.yml",
            "docker_registry: localhost:5001\n",
        )
        rc, _, err = self.run_main(ALL)
        self.assertEqual(rc, 2)
        self.assertIn("ara_server_image", err)

    def test_configuration_overrides_inventory(self):
        self.write(
            "manager/configuration.yml",
            "enable_vault: false\ndocker_registry_ansible: registry.osism.tech\n",
        )
        rc, _, _ = self.run_main(ALL)
        self.assertEqual(rc, 2)

    def test_disabled_service_is_not_required(self):
        rc, _, _ = self.run_main(ALL)
        self.assertEqual(rc, 0)

    def test_enabled_service_is_required(self):
        self.write("manager/configuration.yml", "enable_vault: true\n")
        rc, out, _ = self.run_main(ALL)
        self.assertEqual(rc, 1)
        self.assertIn("MISSING hashicorp/vault:1.21.0", out)

    def test_unless_flag_absent_from_configuration_exits_2(self):
        self.write("manager/configuration.yml", "")
        rc, _, err = self.run_main(ALL)
        self.assertEqual(rc, 2)
        self.assertIn("enable_vault", err)

    def test_templated_unless_flag_exits_2(self):
        self.write("manager/configuration.yml", 'enable_vault: "{{ x }}"\n')
        rc, _, err = self.run_main(ALL)
        self.assertEqual(rc, 2)
        self.assertIn("enable_vault", err)

    def test_junk_unless_flag_exits_2(self):
        self.write("manager/configuration.yml", "enable_vault: maybe\n")
        rc, _, err = self.run_main(ALL)
        self.assertEqual(rc, 2)
        self.assertIn("enable_vault", err)

    def test_excluded_key_may_render_outside_the_box(self):
        self.write("manager/images.yml", IMAGES + HOMER)
        self.table.write_text(TABLE + "homer_image:\n  reason: not pulled\n")
        rc, out, _ = self.run_main(ALL)
        self.assertEqual(rc, 0)
        self.assertIn("2 of 2 images present", out)

    def test_unlisted_key_outside_the_box_exits_2(self):
        self.write("manager/images.yml", IMAGES + HOMER)
        rc, _, err = self.run_main(ALL)
        self.assertEqual(rc, 2)
        self.assertIn("homer_image", err)

    def test_registry_error_exits_2(self):
        error = urllib.error.HTTPError("u", 500, "boom", {}, None)
        rc, _, _ = self.run_main(ALL, error)
        self.assertEqual(rc, 2)

    def test_unreachable_registry_exits_2(self):
        rc, _, _ = self.run_main(ALL, urllib.error.URLError("refused"))
        self.assertEqual(rc, 2)

    def test_no_images_exits_2(self):
        self.write("manager/images.yml", "x_tag: 1\n")
        rc, _, _ = self.run_main(ALL)
        self.assertEqual(rc, 2)

    def test_malformed_table_exits_2(self):
        self.table.write_text("vault_image: just a string\n")
        rc, _, _ = self.run_main(ALL)
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
