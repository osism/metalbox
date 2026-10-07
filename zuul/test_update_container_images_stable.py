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

# docker_images of the release: mariadb, netbox and osism moved on, redis is
# unchanged, alerta has no entry in the manager file. openstackclient is not
# pinned here; it comes from the runners.
VERSIONS = {
    "alerta": "9.1.0",
    "ceph_ansible": "0.20260811.0",
    "kolla": "0.20260814.0",
    "kolla_ansible": "0.20260814.0",
    "mariadb": "11.8.8",
    "netbox": "v4.3.5",
    "osism": "0.20260808.0",
    "osism_ansible": "0.20260811.0",
    "redis": "7.4.10-alpine",
}

# The runners' versions.yml merged, as runner_pins() returns it:
# openstackclient is unchanged.
RUNNER_CONTEXT = {
    "openstackclient_version": "2025.1",
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
        self.runner_pins = mock.Mock(return_value=dict(RUNNER_CONTEXT))
        patcher = mock.patch.multiple(
            script,
            REPO_ROOT=self.tmp,
            MANAGER_FILE=self.manager,
            OPENSTACK_FILE=self.openstack,
            latest_release=mock.Mock(return_value="10.2.0"),
            release_versions=self.release_versions,
            sbom_tags=self.sbom_tags,
            runner_pins=self.runner_pins,
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

        self.release_versions.assert_called_once_with("10.2.0")
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
        self.release_versions.assert_called_once_with("10.2.0")
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
            "4 docker_images of the release are not listed in container-images-manager-stable.yml",
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

    def test_openstackclient_comes_from_the_runners(self):
        self.runner_pins.return_value["openstackclient_version"] = "10.3.0"

        status, out, err = self.run_main()

        self.assertEqual(status, 0, err)
        self.assertIn("  - openstackclient:10.3.0\n", self.manager.read_text())

    def test_runner_openstackclient_wins_over_a_base_yml_pin(self):
        self.release_versions.return_value["openstackclient"] = "9.9.9"

        status, out, err = self.run_main()

        self.assertEqual(status, 0, err)
        self.assertIn("  - openstackclient:2025.1\n", self.manager.read_text())
        self.assertIn("WARNING: base.yml pins openstackclient 9.9.9", err)

    def test_missing_openstackclient_is_unresolved(self):
        del self.runner_pins.return_value["openstackclient_version"]

        status, out, err = self.run_main()

        self.assertEqual(status, 2)
        self.assertIn("openstackclient:2025.1: no openstackclient_version", err)

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

    def release_versions(self, base):
        fetched = []

        def fetch(url, not_found=None):
            fetched.append(url)
            return base

        with mock.patch.object(script, "fetch", fetch):
            versions = script.release_versions("10.2.0")
        return versions, fetched

    def test_returns_the_docker_images_of_base_yml_only(self):
        versions, fetched = self.release_versions(self.BASE)

        self.assertEqual(versions, {"kolla": "0.20260814.0", "netbox": "v4.3.5"})
        # latest/ moves on after a release; nothing is read from it
        self.assertEqual(
            [url.rpartition("/main/")[2] for url in fetched], ["10.2.0/base.yml"]
        )

    def test_missing_kolla_is_fatal(self):
        with self.assertRaisesRegex(script.Fatal, "no docker_images.kolla entry"):
            self.release_versions("---\ndocker_images:\n  netbox: v4.3.5\n")


class RunnerPinsTest(unittest.TestCase):
    VERSIONS = {
        "ceph_ansible": "0.20260811.0",
        "kolla_ansible": "0.20260814.0",
        "osism_ansible": "0.20260811.0",
    }
    FILES = {
        "ceph-ansible": "---\nceph_version: reef\ncephclient_version: '18.2.7'\n",
        "kolla-ansible": "---\nopenstack_version: '2025.1'\nopenstackclient_version: '2025.1'\n",
        "osism-ansible": "---\ncephclient_version: '18.2.8'\nopenstackclient_version: '10.3.0'\n",
    }

    def runner_pins(self, versions, files):
        read = []

        def image_file(image, path):
            read.append((image, path))
            name = image.rpartition("/")[2].partition(":")[0]
            return files[name]

        out = io.StringIO()
        with mock.patch.object(
            script, "image_file", image_file
        ), contextlib.redirect_stdout(out):
            context = script.runner_pins(versions)
        return context, read

    def test_later_runners_win_in_the_order_of_the_inventory(self):
        context, read = self.runner_pins(self.VERSIONS, self.FILES)

        self.assertEqual(
            read,
            [
                (
                    "registry.osism.tech/osism/ceph-ansible:0.20260811.0",
                    script.RUNNER_VERSIONS,
                ),
                (
                    "registry.osism.tech/osism/kolla-ansible:0.20260814.0",
                    script.RUNNER_VERSIONS,
                ),
                (
                    "registry.osism.tech/osism/osism-ansible:0.20260811.0",
                    script.RUNNER_VERSIONS,
                ),
            ],
        )
        self.assertEqual(context["ceph_version"], "reef")
        self.assertEqual(context["cephclient_version"], "18.2.8")
        self.assertEqual(context["openstackclient_version"], "10.3.0")

    def test_runner_the_release_does_not_pin_adds_no_layer(self):
        # A release without ceph-ansible (Ceph deployed with cephadm) gives
        # the pod no 100-versions-ceph-ansible.yml either.
        versions = {k: v for k, v in self.VERSIONS.items() if k != "ceph_ansible"}

        context, read = self.runner_pins(versions, self.FILES)

        self.assertEqual(
            [image.rpartition("/")[2] for image, _ in read],
            ["kolla-ansible:0.20260814.0", "osism-ansible:0.20260811.0"],
        )
        self.assertNotIn("ceph_version", context)

    def test_release_without_osism_ansible_is_fatal(self):
        versions = {k: v for k, v in self.VERSIONS.items() if k != "osism_ansible"}

        with self.assertRaisesRegex(
            script.Fatal, "docker_images.osism_ansible missing"
        ):
            self.runner_pins(versions, self.FILES)

    def test_versions_yml_that_is_no_mapping_is_fatal(self):
        files = dict(self.FILES, **{"osism-ansible": "---\n- a\n"})

        with self.assertRaisesRegex(
            script.Fatal, "osism-ansible:0.20260811.0: .*not a mapping"
        ):
            self.runner_pins(self.VERSIONS, files)


class RunnerPinTest(unittest.TestCase):
    def test_plain_value(self):
        self.assertEqual(
            script.runner_pin({"ceph_image_version": "18.2.8"}, "ceph_image"),
            ("18.2.8", None),
        )

    def test_template_without_a_map(self):
        context = {"ceph_image_version": "{{ ceph_image_versions[ceph_version] }}"}
        tag, reason = script.runner_pin(context, "ceph_image")
        self.assertIsNone(tag)
        self.assertIn("ceph_image_version is a template", reason)

    def test_missing(self):
        self.assertEqual(
            script.runner_pin({}, "openstackclient"),
            (None, "no openstackclient_version in the runners"),
        )


class FakeProcess:
    """A crane export as file_via_crane sees it: a tar stream and an exit code."""

    def __init__(self, stdout, returncode=0, stderr=b""):
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = None
        self._returncode = returncode

    def wait(self):
        self.returncode = self._returncode
        return self.returncode


class FileViaCraneTest(unittest.TestCase):
    def crane(self, process, path="/images.yml"):
        with mock.patch.object(script.subprocess, "Popen", return_value=process):
            return script.file_via_crane("registry.osism.tech/osism/x:1", path)

    def test_file_is_found_under_any_root_spelling(self):
        for name in ("images.yml", "./images.yml", "/images.yml"):
            with self.subTest(name=name):
                self.assertEqual(
                    self.crane(FakeProcess(tar_with([name]))), "images: []\n"
                )

    def test_file_in_a_directory(self):
        process = FakeProcess(tar_with(["./ansible/group_vars/all/versions.yml"]))
        self.assertEqual(
            self.crane(process, "/ansible/group_vars/all/versions.yml"), "images: []\n"
        )

    def test_missing_file_is_fatal(self):
        with self.assertRaisesRegex(script.Fatal, "contains no /images.yml"):
            self.crane(FakeProcess(tar_with(["./other.yml", "./etc/images.yml"])))

    def test_failed_export_is_fatal_with_its_error(self):
        with self.assertRaisesRegex(
            script.Fatal, "export .* failed:\nMANIFEST_UNKNOWN"
        ):
            self.crane(FakeProcess(b"", returncode=1, stderr=b"MANIFEST_UNKNOWN\n"))


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


class ManagerImagesMappingTest(unittest.TestCase):
    def test_otel_collector_is_the_contrib_image(self):
        # osism/release etc/images.yml maps opentelemetry_collector to the
        # -contrib repository; that is the image OSISM deploys.
        external = script.MANAGER_IMAGES["images_manager_stable_external"]
        self.assertEqual(
            external.get("otel/opentelemetry-collector-contrib"),
            "opentelemetry_collector",
        )
        self.assertNotIn("otel/opentelemetry-collector", external)

    def test_phpmyadmin_is_the_release_repository(self):
        # osism/release etc/images.yml maps phpmyadmin to phpmyadmin/phpmyadmin,
        # not the Docker Hub library image.
        external = script.MANAGER_IMAGES["images_manager_stable_external"]
        self.assertEqual(external.get("phpmyadmin/phpmyadmin"), "phpmyadmin")
        self.assertNotIn("library/phpmyadmin", external)


if __name__ == "__main__":
    unittest.main()
