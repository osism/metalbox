"""Tests for update-container-images-stable.py.

Run with: python3 -m unittest discover -s zuul
"""

import contextlib
import importlib.util
import io
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("update-container-images-stable.py")
spec = importlib.util.spec_from_file_location("update_container_images_stable", SCRIPT)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)

MANAGER = """\
---
images_manager_stable_external:
  - library/httpd:alpine
  - library/mariadb:11.8.7
  - library/redis:7.4.10-alpine

images_manager_stable:
  - netbox:v4.3.4
  - openstackclient:2025.1
  - osism-frontend:0.20260701.0
  - osism:0.20260701.0
  - rsync:latest
"""

OPENSTACK = """\
---
images_kolla:
  - release/2025.1/cron:3.0.20260328
  - release/2025.1/keystone:27.0.3.20260814
  - release/2025.1/nova-api:31.1.2.20260328
"""

# docker_images of the release: mariadb, netbox and osism moved on, redis and
# openstackclient are unchanged, alerta has no entry in the manager file.
VERSIONS = {
    "alerta": "9.1.0",
    "kolla": "0.20260814.0",
    "mariadb": "11.8.8",
    "netbox": "v4.3.5",
    "openstackclient": "2025.1",
    "osism": "0.20260808.0",
    "redis": "7.4.10-alpine",
}

# images of the SBOM: cron and nova-api moved on, aodh-api is not listed.
TAGS = {
    "aodh-api": "20.0.0.20260814",
    "cron": "3.0.20260814",
    "keystone": "27.0.3.20260814",
    "nova-api": "31.1.2.20260814",
}


def tar_with(names):
    """Return the bytes of a tar archive holding the given regular files."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name in names:
            data = b"images: []\n"
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class MainTest(unittest.TestCase):
    """main() against fixture files; the network and the SBOM are stubbed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.manager = self.tmp / "container-images-manager-stable.yml"
        self.openstack = self.tmp / "container-images-openstack-stable.yml"
        self.manager.write_text(MANAGER)
        self.openstack.write_text(OPENSTACK)
        self.release_versions = mock.Mock(return_value=dict(VERSIONS))
        self.sbom_tags = mock.Mock(return_value=dict(TAGS))
        patcher = mock.patch.multiple(
            script,
            REPO_ROOT=self.tmp,
            MANAGER_FILE=self.manager,
            OPENSTACK_FILE=self.openstack,
            latest_release=mock.Mock(return_value="10.2.0"),
            release_versions=self.release_versions,
            sbom_tags=self.sbom_tags,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = script.main(list(argv))
        return status, out.getvalue(), err.getvalue()

    def test_updates_tags_and_keeps_unmapped_entries_with_exit_0(self):
        status, out, err = self.run_main()

        self.assertEqual(status, 0, err)
        self.assertEqual(err, "")
        self.assertEqual(
            self.manager.read_text(),
            MANAGER.replace("mariadb:11.8.7", "mariadb:11.8.8")
            .replace("netbox:v4.3.4", "netbox:v4.3.5")
            .replace("osism-frontend:0.20260701.0", "osism-frontend:0.20260808.0")
            .replace("osism:0.20260701.0", "osism:0.20260808.0"),
        )
        self.assertEqual(
            self.openstack.read_text(),
            OPENSTACK.replace("cron:3.0.20260328", "cron:3.0.20260814").replace(
                "nova-api:31.1.2.20260328", "nova-api:31.1.2.20260814"
            ),
        )
        # httpd and rsync are kept without making the run fail
        self.assertRegex(out, r"\n  library/httpd +alpine \(kept: ")
        self.assertRegex(out, r"\n  rsync +latest \(kept: ")
        self.assertIn("  4 updated, 2 unchanged, 2 kept\n", out)
        self.assertIn("  2 updated, 1 unchanged, 0 kept\n", out)
        self.assertIn("Files updated.", out)

    def test_tally_sums_to_the_number_of_entries(self):
        self.release_versions.return_value = {
            key: value for key, value in VERSIONS.items() if key != "netbox"
        }

        status, out, err = self.run_main()

        self.assertEqual(status, 2)
        self.assertIn("netbox:v4.3.4: docker_images.netbox missing", err)
        self.assertIn("1 entries could not be resolved", err)
        tally = [line for line in out.splitlines() if line.endswith(" kept")]
        self.assertEqual(len(tally), 2)
        for line, entries in zip(tally, (8, 3)):
            numbers = [int(word) for word in line.split() if word.isdigit()]
            self.assertEqual(sum(numbers), entries, line)
        # the unresolved entry is kept, the others are still written
        self.assertIn("netbox:v4.3.4", self.manager.read_text())
        self.assertIn("mariadb:11.8.8", self.manager.read_text())

    def test_dry_run_writes_nothing_and_reports_the_pending_changes(self):
        status, out, err = self.run_main("-n")

        self.assertEqual(status, 0, err)
        self.assertEqual(self.manager.read_text(), MANAGER)
        self.assertEqual(self.openstack.read_text(), OPENSTACK)
        self.assertIn("Dry run: 6 changes pending, nothing written.", out)
        self.assertEqual(
            sorted(p.name for p in self.tmp.iterdir()),
            sorted([self.manager.name, self.openstack.name]),
        )

    def test_dry_run_reports_when_nothing_is_pending(self):
        self.run_main()

        status, out, err = self.run_main("-n")

        self.assertEqual(status, 0, err)
        self.assertIn("Dry run: the files already match the release", out)

    def test_up_to_date_files_are_left_alone(self):
        self.run_main()
        before = (self.manager.stat().st_mtime_ns, self.openstack.stat().st_mtime_ns)

        status, out, err = self.run_main()

        self.assertEqual(status, 0, err)
        self.assertIn("Nothing to do", out)
        after = (self.manager.stat().st_mtime_ns, self.openstack.stat().st_mtime_ns)
        self.assertEqual(before, after)

    def test_openstack_release_is_taken_from_the_file(self):
        self.run_main()

        self.release_versions.assert_called_once_with("10.2.0", "2025.1")
        self.sbom_tags.assert_called_once_with(
            "registry.osism.tech/kolla/release/2025.1/sbom:0.20260814.0", "2025.1"
        )
        self.assertNotIn("release/2025.2/", self.openstack.read_text())

    def test_mixed_openstack_releases_are_fatal_without_o(self):
        self.openstack.write_text(
            OPENSTACK.replace("release/2025.1/cron", "release/2025.2/cron")
        )

        with self.assertRaisesRegex(script.Fatal, "2025.1, 2025.2.*pass -o"):
            self.run_main()

        self.release_versions.assert_not_called()

    def test_o_moves_the_entries_to_the_requested_release(self):
        status, out, err = self.run_main("-o", "2025.2")

        self.assertEqual(status, 0, err)
        self.release_versions.assert_called_once_with("10.2.0", "2025.2")
        self.assertIn(
            "Moving the kolla entries from release/2025.1/ to release/2025.2/", out
        )
        text = self.openstack.read_text()
        self.assertNotIn("release/2025.1/", text)
        self.assertIn("  - release/2025.2/keystone:27.0.3.20260814\n", text)
        self.assertIn("  3 updated, 0 unchanged, 0 kept\n", out)

    def test_unlisted_images_of_the_release_are_counted(self):
        status, out, err = self.run_main("-n")

        self.assertIn(
            "1 docker_images of the release are not listed in container-images-manager-stable.yml",
            out,
        )
        self.assertIn(
            "1 images of the SBOM are not listed in container-images-openstack-stable.yml",
            out,
        )
        self.assertNotIn("  alerta\n", out)

        status, out, err = self.run_main("-n", "-v")

        self.assertIn("  alerta\n", out)
        self.assertIn("  aodh-api\n", out)

    def test_commented_entry_is_fatal_instead_of_invisible(self):
        self.manager.write_text(
            MANAGER.replace(
                "library/redis:7.4.10-alpine", "library/redis:7.4.10-alpine  # keep"
            )
        )

        with self.assertRaisesRegex(
            script.Fatal,
            "images_manager_stable_external: the YAML parser sees 3 entries, "
            "the line scanner 2",
        ):
            self.run_main("-n")

    def test_write_failure_is_fatal_and_leaves_the_file_untouched(self):
        with mock.patch.object(
            script.os, "replace", side_effect=OSError(28, "No space left on device")
        ):
            with self.assertRaisesRegex(
                script.Fatal, "container-images-manager-stable.yml: .*No space left"
            ):
                self.run_main()

        self.assertEqual(self.manager.read_text(), MANAGER)
        self.assertEqual(self.openstack.read_text(), OPENSTACK)
        self.assertEqual(
            sorted(p.name for p in self.tmp.iterdir()),
            sorted([self.manager.name, self.openstack.name]),
        )


class ScanFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.path = self.tmp / "container-images-manager-stable.yml"

    def scan(self, text):
        self.path.write_text(text)
        return script.scan_file(self.path)

    def test_plain_entries_are_found_with_their_list_and_line(self):
        lines, entries = self.scan(MANAGER)

        self.assertEqual(len(lines), MANAGER.count("\n"))
        self.assertEqual(len(entries), 8)
        self.assertEqual(
            entries[0],
            script.Entry(2, "images_manager_stable_external", "library/httpd:alpine"),
        )
        self.assertEqual(
            entries[3], script.Entry(7, "images_manager_stable", "netbox:v4.3.4")
        )
        self.assertEqual(
            {entry.list_name for entry in entries},
            {"images_manager_stable_external", "images_manager_stable"},
        )

    def test_trailing_comment_is_fatal(self):
        with self.assertRaisesRegex(
            script.Fatal, "the YAML parser sees 3 entries, the line scanner 2"
        ):
            self.scan(
                MANAGER.replace("library/nginx", "library/nginx").replace(
                    "library/redis:7.4.10-alpine", "library/redis:7.4.10-alpine  # keep"
                )
            )

    def test_quoted_entry_is_fatal(self):
        with self.assertRaisesRegex(
            script.Fatal,
            """reads '"netbox:v4.3.4"' where the YAML parser reads 'netbox:v4.3.4'""",
        ):
            self.scan(MANAGER.replace("netbox:v4.3.4", '"netbox:v4.3.4"'))

    def test_flow_sequence_is_fatal(self):
        with self.assertRaisesRegex(
            script.Fatal, "the YAML parser sees 1 entries, the line scanner 0"
        ):
            self.scan("---\nimages_kolla: [release/2025.1/cron:3.0.20260814]\n")

    def test_invalid_yaml_is_fatal(self):
        with self.assertRaises(script.Fatal):
            self.scan("---\nimages_kolla:\n  - a\n - b\n")


class ReleaseVersionsTest(unittest.TestCase):
    BASE = "---\ndocker_images:\n  kolla: 0.20260814.0\n  netbox: v4.3.5\n"
    OPENSTACK = "---\ndocker_images:\n  openstackclient: '2025.1'\n"

    def release_versions(self, base, openstack):
        def fetch(url, not_found=None):
            return base if url.endswith("/base.yml") else openstack

        err = io.StringIO()
        with mock.patch.object(script, "fetch", fetch), contextlib.redirect_stderr(err):
            versions = script.release_versions("10.2.0", "2025.1")
        return versions, err.getvalue()

    def test_openstackclient_falls_back_to_the_openstack_release_file(self):
        versions, err = self.release_versions(self.BASE, self.OPENSTACK)

        self.assertEqual(versions["openstackclient"], "2025.1")
        self.assertEqual(versions["netbox"], "v4.3.5")
        self.assertEqual(err, "")

    def test_openstackclient_pinned_in_base_yml_wins(self):
        versions, err = self.release_versions(
            self.BASE + "  openstackclient: 9.9.9\n", self.OPENSTACK
        )

        self.assertEqual(versions["openstackclient"], "9.9.9")
        self.assertEqual(err, "")

    def test_openstackclient_missing_everywhere_is_a_warning(self):
        versions, err = self.release_versions(self.BASE, "---\ndocker_images: {}\n")

        self.assertNotIn("openstackclient", versions)
        self.assertIn(
            "WARNING: neither 10.2.0/base.yml nor latest/openstack-2025.1.yml pins", err
        )

    def test_missing_kolla_is_fatal(self):
        with self.assertRaisesRegex(script.Fatal, "no docker_images.kolla entry"):
            self.release_versions(
                "---\ndocker_images:\n  netbox: v4.3.5\n", self.OPENSTACK
            )


class SbomViaCraneTest(unittest.TestCase):
    def crane(self, names):
        with mock.patch.object(
            script, "run", return_value=mock.Mock(stdout=tar_with(names))
        ):
            return script.sbom_via_crane(
                "registry.osism.tech/kolla/release/2025.1/sbom:x"
            )

    def test_images_yml_is_found_under_any_root_spelling(self):
        for name in ("images.yml", "./images.yml", "/images.yml"):
            with self.subTest(name=name):
                self.assertEqual(self.crane([name]), "images: []\n")

    def test_missing_images_yml_is_fatal(self):
        with self.assertRaisesRegex(script.Fatal, "contains no images.yml"):
            self.crane(["./other.yml", "./etc/images.yml"])


class WriteFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.path = self.tmp / "vars.yml"
        self.path.write_text("old\n")
        os.chmod(self.path, 0o644)

    def test_replaces_the_content_and_keeps_the_mode(self):
        script.write_file(self.path, "new\n")

        self.assertEqual(self.path.read_text(), "new\n")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o644)
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["vars.yml"])

    def test_failed_rename_is_fatal_and_leaves_no_trace(self):
        with mock.patch.object(
            script.os, "replace", side_effect=OSError(13, "Permission denied")
        ):
            with self.assertRaisesRegex(script.Fatal, "vars.yml: .*Permission denied"):
                script.write_file(self.path, "new\n")

        self.assertEqual(self.path.read_text(), "old\n")
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["vars.yml"])


if __name__ == "__main__":
    unittest.main()
