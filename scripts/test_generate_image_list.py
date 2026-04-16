"""Tests for generate_image_list.py"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_image_list import (
    _collect_latest_images,
    collect_all_versions,
    detect_latest_major,
    discover_versions,
    fetch_base_versions,
    fetch_image_mapping,
    generate_image_entries,
    load_filter_config,
    parse_version,
    run,
    update_zuul_file,
    validate_filter,
)


class TestParseVersion(unittest.TestCase):
    def test_valid_version(self):
        self.assertEqual(parse_version("9.3.1"), (9, 3, 1))

    def test_valid_version_large(self):
        self.assertEqual(parse_version("10.0.0"), (10, 0, 0))

    def test_valid_version_zeros(self):
        self.assertEqual(parse_version("1.0.0"), (1, 0, 0))

    def test_rc_version_returns_none(self):
        self.assertIsNone(parse_version("9.3.1rc1"))

    def test_rc_version_dash_returns_none(self):
        self.assertIsNone(parse_version("9.3.1-rc1"))

    def test_non_version_string_returns_none(self):
        self.assertIsNone(parse_version("etc"))

    def test_partial_version_returns_none(self):
        self.assertIsNone(parse_version("9.3"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(parse_version(""))

    def test_alpha_version_returns_none(self):
        self.assertIsNone(parse_version("latest"))


class TestDiscoverVersionsLocal(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmpdir.name)
        # Create version dirs
        for v in ["9.0.0", "9.1.0", "10.0.0", "10.1.0"]:
            (self.repo / v).mkdir()
        # Create non-version dirs
        (self.repo / "etc").mkdir()
        (self.repo / "main").mkdir()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_all_versions(self):
        versions = discover_versions(self.repo)
        self.assertCountEqual(versions, ["9.0.0", "9.1.0", "10.0.0", "10.1.0"])

    def test_filter_by_major(self):
        versions = discover_versions(self.repo, major=9)
        self.assertCountEqual(versions, ["9.0.0", "9.1.0"])

    def test_filter_by_major_10(self):
        versions = discover_versions(self.repo, major=10)
        self.assertCountEqual(versions, ["10.0.0", "10.1.0"])

    def test_filter_by_major_no_match(self):
        versions = discover_versions(self.repo, major=11)
        self.assertEqual(versions, [])

    def test_excludes_non_version_dirs(self):
        versions = discover_versions(self.repo)
        self.assertNotIn("etc", versions)
        self.assertNotIn("main", versions)


class TestFetchLocal(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmpdir.name)
        etc_dir = self.repo / "etc"
        etc_dir.mkdir()
        images_data = {
            "ara_server": "osism/ara-server",
            "netbox": "osism/netbox",
            "traefik": "traefik",
        }
        with open(etc_dir / "images.yml", "w") as f:
            yaml.dump(images_data, f)

        ver_dir = self.repo / "9.3.1"
        ver_dir.mkdir()
        base_data = {
            "docker_images": {
                "ara_server": "2024.1.3",
                "netbox": "v4.1.11",
                "traefik": "v3.3.4",
            }
        }
        with open(ver_dir / "base.yml", "w") as f:
            yaml.dump(base_data, f)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_fetch_image_mapping(self):
        mapping = fetch_image_mapping(self.repo)
        self.assertEqual(mapping["ara_server"], "osism/ara-server")
        self.assertEqual(mapping["netbox"], "osism/netbox")
        self.assertEqual(mapping["traefik"], "traefik")

    def test_fetch_base_versions(self):
        images = fetch_base_versions(self.repo, "9.3.1")
        self.assertEqual(images["ara_server"], "2024.1.3")
        self.assertEqual(images["netbox"], "v4.1.11")
        self.assertEqual(images["traefik"], "v3.3.4")

    def test_fetch_base_versions_missing_docker_images(self):
        ver_dir = self.repo / "9.3.2"
        ver_dir.mkdir()
        with open(ver_dir / "base.yml", "w") as f:
            yaml.dump({"other_key": "value"}, f)
        images = fetch_base_versions(self.repo, "9.3.2")
        self.assertEqual(images, {})


class TestCollectAllVersions(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmpdir.name)
        for version, images in [
            ("9.0.0", {"ara_server": "1.0", "netbox": "v3.0"}),
            ("9.1.0", {"ara_server": "1.1", "netbox": "v3.1", "traefik": "v2.0"}),
        ]:
            ver_dir = self.repo / version
            ver_dir.mkdir()
            with open(ver_dir / "base.yml", "w") as f:
                yaml.dump({"docker_images": images}, f)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_union_of_versions(self):
        all_versions = collect_all_versions(self.repo, ["9.0.0", "9.1.0"])
        self.assertEqual(all_versions["ara_server"], {"1.0", "1.1"})
        self.assertEqual(all_versions["netbox"], {"v3.0", "v3.1"})
        self.assertEqual(all_versions["traefik"], {"v2.0"})

    def test_single_version(self):
        all_versions = collect_all_versions(self.repo, ["9.0.0"])
        self.assertEqual(all_versions["ara_server"], {"1.0"})
        self.assertNotIn("traefik", all_versions)

    def test_empty_versions(self):
        all_versions = collect_all_versions(self.repo, [])
        self.assertEqual(all_versions, {})


class TestLoadFilterConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_load_with_both_keys(self):
        path = Path(self.tmpdir.name) / "filter.yml"
        with open(path, "w") as f:
            yaml.dump(
                {
                    "images": ["ara_server", "netbox"],
                    "unmanaged": ["library/httpd:alpine"],
                },
                f,
            )
        config = load_filter_config(path)
        self.assertEqual(config["images"], ["ara_server", "netbox"])
        self.assertEqual(config["unmanaged"], ["library/httpd:alpine"])

    def test_missing_unmanaged_defaults_to_empty(self):
        path = Path(self.tmpdir.name) / "filter.yml"
        with open(path, "w") as f:
            yaml.dump({"images": ["ara_server"]}, f)
        config = load_filter_config(path)
        self.assertEqual(config["images"], ["ara_server"])
        self.assertEqual(config["unmanaged"], [])

    def test_missing_images_defaults_to_empty(self):
        path = Path(self.tmpdir.name) / "filter.yml"
        with open(path, "w") as f:
            yaml.dump({"unmanaged": ["library/httpd:alpine"]}, f)
        config = load_filter_config(path)
        self.assertEqual(config["images"], [])
        self.assertEqual(config["unmanaged"], ["library/httpd:alpine"])

    def test_exclude_key(self):
        path = Path(self.tmpdir.name) / "filter.yml"
        with open(path, "w") as f:
            yaml.dump({"images": ["ara_server"], "exclude": ["homer"]}, f)
        config = load_filter_config(path)
        self.assertEqual(config["exclude"], ["homer"])

    def test_missing_exclude_defaults_to_empty(self):
        path = Path(self.tmpdir.name) / "filter.yml"
        with open(path, "w") as f:
            yaml.dump({"images": ["ara_server"]}, f)
        config = load_filter_config(path)
        self.assertEqual(config["exclude"], [])

    def test_unmanaged_manager_key(self):
        path = Path(self.tmpdir.name) / "filter.yml"
        with open(path, "w") as f:
            yaml.dump(
                {
                    "images": ["ara_server"],
                    "unmanaged_manager": ["rsync:latest"],
                },
                f,
            )
        config = load_filter_config(path)
        self.assertEqual(config["unmanaged_manager"], ["rsync:latest"])

    def test_missing_unmanaged_manager_defaults_to_empty(self):
        path = Path(self.tmpdir.name) / "filter.yml"
        with open(path, "w") as f:
            yaml.dump({"images": ["ara_server"]}, f)
        config = load_filter_config(path)
        self.assertEqual(config["unmanaged_manager"], [])


class TestValidateFilter(unittest.TestCase):
    def setUp(self):
        self.image_mapping = {
            "ara_server": "osism/ara-server",
            "netbox": "osism/netbox",
            "traefik": "traefik",
        }
        self.all_versions = {
            "ara_server": {"1.0", "1.1"},
            "netbox": {"v3.0"},
            "traefik": {"v2.0"},
        }

    def test_valid_filter(self):
        errors = validate_filter(
            ["ara_server", "netbox", "traefik"],
            self.image_mapping,
            self.all_versions,
        )
        self.assertEqual(errors, [])

    def test_unknown_upstream_image(self):
        errors = validate_filter(
            ["ara_server", "netbox"],
            self.image_mapping,
            self.all_versions,
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("traefik", errors[0])
        self.assertIn("not in the filter config", errors[0])

    def test_stale_filter_entry(self):
        errors = validate_filter(
            ["ara_server", "netbox", "traefik", "old_image"],
            self.image_mapping,
            self.all_versions,
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("old_image", errors[0])
        self.assertIn("does not exist in", errors[0])

    def test_image_in_mapping_but_no_versions_not_flagged(self):
        # mariadb is in mapping but has no entry in all_versions
        mapping = dict(self.image_mapping)
        mapping["mariadb"] = "osism/mariadb"
        errors = validate_filter(
            ["ara_server", "netbox", "traefik"],
            mapping,
            self.all_versions,
        )
        # mariadb has no versions so it's not in upstream_with_versions, no error
        self.assertEqual(errors, [])

    def test_multiple_errors(self):
        errors = validate_filter(
            ["ara_server", "stale_one", "stale_two"],
            self.image_mapping,
            self.all_versions,
        )
        # netbox and traefik are unknown upstream
        unknown_errors = [e for e in errors if "not in the filter config" in e]
        stale_errors = [e for e in errors if "does not exist in" in e]
        self.assertEqual(len(unknown_errors), 2)
        self.assertEqual(len(stale_errors), 2)

    def test_filter_entry_with_no_versions_is_error(self):
        """Image in filter and in mapping but with no versions in any release."""
        image_mapping = {"ara_server": "osism/ara-server",
                         "netbox": "osism/netbox"}
        all_versions = {"ara_server": {"1.0"}}  # netbox has no versions
        errors = validate_filter(
            ["ara_server", "netbox"],
            image_mapping,
            all_versions,
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("netbox", errors[0])
        self.assertIn("no versions", errors[0])

    def test_excluded_images_not_flagged(self):
        errors = validate_filter(
            ["ara_server", "netbox"],
            self.image_mapping,
            self.all_versions,
            exclude_names=["traefik"],
        )
        self.assertEqual(errors, [])

    def test_excluded_but_not_in_mapping_still_ok(self):
        """Excluding a name that doesn't exist in mapping is harmless."""
        errors = validate_filter(
            ["ara_server", "netbox", "traefik"],
            self.image_mapping,
            self.all_versions,
            exclude_names=["nonexistent"],
        )
        self.assertEqual(errors, [])


class TestGenerateImageEntries(unittest.TestCase):
    def setUp(self):
        self.image_mapping = {
            "ara_server": "osism/ara-server",
            "netbox": "osism/netbox",
            "traefik": "traefik",
            "redis": "osism/redis",
        }
        self.all_versions = {
            "ara_server": {"1.0", "1.1"},
            "netbox": {"v3.0"},
            "traefik": {"v2.0", "v2.1"},
            "redis": {"7.0"},
        }

    def test_prefix_split(self):
        images, images_manager = generate_image_entries(
            ["ara_server", "traefik"], self.image_mapping, self.all_versions, [], []
        )
        self.assertIn("traefik:v2.0", images)
        self.assertIn("ara-server:1.0", images_manager)

    def test_osism_prefix_stripped(self):
        images, images_manager = generate_image_entries(
            ["netbox"], self.image_mapping, self.all_versions, [], []
        )
        self.assertIn("netbox:v3.0", images_manager)
        self.assertNotIn("osism/netbox:v3.0", images_manager)

    def test_sorted_output(self):
        images, images_manager = generate_image_entries(
            ["ara_server", "netbox", "traefik", "redis"],
            self.image_mapping,
            self.all_versions,
            [],
            [],
        )
        self.assertEqual(images, sorted(images))
        self.assertEqual(images_manager, sorted(images_manager))

    def test_multiple_versions(self):
        images, images_manager = generate_image_entries(
            ["traefik"], self.image_mapping, self.all_versions, [], []
        )
        self.assertIn("traefik:v2.0", images)
        self.assertIn("traefik:v2.1", images)

    def test_unmanaged_passthrough(self):
        unmanaged = ["library/httpd:alpine", "library/nginx:latest"]
        images, images_manager = generate_image_entries(
            [], self.image_mapping, self.all_versions, unmanaged, []
        )
        self.assertIn("library/httpd:alpine", images)
        self.assertIn("library/nginx:latest", images)

    def test_unmanaged_included_in_sorted_images(self):
        unmanaged = ["zzz/image:latest"]
        images, images_manager = generate_image_entries(
            ["traefik"], self.image_mapping, self.all_versions, unmanaged, []
        )
        self.assertIn("zzz/image:latest", images)
        self.assertEqual(images, sorted(images))

    def test_name_not_in_all_versions_produces_no_entries(self):
        all_versions = {}
        images, images_manager = generate_image_entries(
            ["ara_server"], self.image_mapping, all_versions, [], []
        )
        self.assertEqual(images, [])
        self.assertEqual(images_manager, [])

    def test_unmanaged_manager_goes_to_images_manager(self):
        unmanaged_manager = ["rsync:latest", "osism-frontend:latest"]
        images, images_manager = generate_image_entries(
            [], self.image_mapping, self.all_versions, [], unmanaged_manager
        )
        self.assertIn("rsync:latest", images_manager)
        self.assertIn("osism-frontend:latest", images_manager)
        self.assertEqual(images, [])

    def test_unmanaged_manager_sorted_with_generated(self):
        unmanaged_manager = ["zzz:latest"]
        images, images_manager = generate_image_entries(
            ["ara_server"], self.image_mapping, self.all_versions, [], unmanaged_manager
        )
        self.assertIn("zzz:latest", images_manager)
        self.assertEqual(images_manager, sorted(images_manager))

    def test_keep_latest_for_collapses_to_latest(self):
        all_versions = {
            "ara_server": {"1.7.2", "1.7.3"},
            "traefik": {"v2.0", "v2.1"},
        }
        # traefik is in keep_latest_for -> only :latest emitted
        images, images_manager = generate_image_entries(
            ["ara_server", "traefik"],
            self.image_mapping,
            all_versions,
            [],
            [],
            keep_latest_for={"traefik"},
        )
        traefik_entries = [e for e in images if e.startswith("traefik:")]
        self.assertEqual(traefik_entries, ["traefik:latest"])
        # ara_server is NOT in keep_latest_for -> all versions preserved
        ara_entries = [e for e in images_manager if e.startswith("ara-server:")]
        self.assertEqual(sorted(ara_entries), ["ara-server:1.7.2", "ara-server:1.7.3"])

    def test_keep_latest_for_osism_prefix(self):
        """keep_latest_for uses short names (prefix stripped)."""
        all_versions = {
            "ara_server": {"1.7.2", "1.7.3"},
        }
        images, images_manager = generate_image_entries(
            ["ara_server"],
            self.image_mapping,
            all_versions,
            [],
            [],
            keep_latest_for={"ara-server"},
        )
        self.assertEqual(images_manager, ["ara-server:latest"])

    def test_keep_latest_for_empty_expands_all(self):
        all_versions = {
            "traefik": {"v2.0", "v2.1"},
        }
        images, _ = generate_image_entries(
            ["traefik"], self.image_mapping, all_versions, [], [], keep_latest_for=set()
        )
        self.assertIn("traefik:v2.0", images)
        self.assertIn("traefik:v2.1", images)
        self.assertNotIn("traefik:latest", images)


class TestCollectLatestImages(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_zuul(self, data):
        path = Path(self.tmpdir.name) / "container-images.yml"
        with open(path, "w") as f:
            f.write("---\n")
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        return str(path)

    def test_finds_latest_in_both_lists(self):
        path = self._write_zuul(
            {
                "images": ["library/httpd:alpine", "osism:latest"],
                "images_manager": ["ara-server:1.7.3", "tempest:latest"],
            }
        )
        result = _collect_latest_images(path)
        self.assertEqual(result, {"osism", "tempest"})

    def test_no_latest_returns_empty(self):
        path = self._write_zuul(
            {
                "images": ["library/httpd:alpine"],
                "images_manager": ["ara-server:1.7.3"],
            }
        )
        result = _collect_latest_images(path)
        self.assertEqual(result, set())

    def test_handles_missing_lists(self):
        path = self._write_zuul({})
        result = _collect_latest_images(path)
        self.assertEqual(result, set())


class TestUpdateZuulFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_zuul_file(self, data):
        path = Path(self.tmpdir.name) / "container-images.yml"
        with open(path, "w") as f:
            f.write("---\n")
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        return path

    def test_preserves_other_keys(self):
        path = self._write_zuul_file(
            {
                "images": ["old:1.0"],
                "images_manager": ["old-mgr:1.0"],
                "extra_key": "keep_me",
            }
        )
        update_zuul_file(path, ["new:2.0"], ["new-mgr:2.0"])
        with open(path) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data["extra_key"], "keep_me")
        self.assertEqual(data["images"], ["new:2.0"])
        self.assertEqual(data["images_manager"], ["new-mgr:2.0"])

    def test_output_starts_with_yaml_document_marker(self):
        path = self._write_zuul_file({"images": [], "images_manager": []})
        update_zuul_file(path, [], [])
        with open(path) as f:
            content = f.read()
        self.assertTrue(content.startswith("---\n"))

    def test_updates_images_list(self):
        path = self._write_zuul_file({"images": ["old:1.0"], "images_manager": []})
        update_zuul_file(path, ["a:1.0", "b:2.0"], [])
        with open(path) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data["images"], ["a:1.0", "b:2.0"])

    def test_updates_images_manager_list(self):
        path = self._write_zuul_file({"images": [], "images_manager": ["old-mgr:1.0"]})
        update_zuul_file(path, [], ["mgr-a:1.0", "mgr-b:2.0"])
        with open(path) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data["images_manager"], ["mgr-a:1.0", "mgr-b:2.0"])

    def test_empty_list_written_as_empty_yaml_list(self):
        path = self._write_zuul_file({
            "images": ["old:1.0"],
            "images_manager": ["old-mgr:1.0"],
            "images_kolla_metalbox": [],
        })
        update_zuul_file(path, [], [])
        with open(path) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data["images"], [])
        self.assertEqual(data["images_manager"], [])
        self.assertEqual(data["images_kolla_metalbox"], [])


class TestDetectLatestMajor(unittest.TestCase):
    def test_picks_highest(self):
        versions = ["7.0.0", "7.1.0", "9.0.0", "9.1.0", "10.0.0"]
        self.assertEqual(detect_latest_major(versions), 10)

    def test_single_version(self):
        self.assertEqual(detect_latest_major(["5.0.0"]), 5)


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.release_dir = os.path.join(self.tmpdir, "release")
        self.metalbox_dir = os.path.join(self.tmpdir, "metalbox")

        # Build a minimal release repo
        os.makedirs(os.path.join(self.release_dir, "etc"))
        with open(os.path.join(self.release_dir, "etc", "images.yml"), "w") as f:
            yaml.dump(
                {
                    "ara_server": "osism/ara-server",
                    "vault": "hashicorp/vault",
                    "redis": "library/redis",
                    "homer": "osism/homer",
                },
                f,
            )

        for version, images in [
            (
                "9.0.0",
                {
                    "ara_server": "1.7.2",
                    "vault": "1.19.1",
                    "redis": "7.4.2-alpine",
                    "homer": "v25.04.1",
                },
            ),
            (
                "9.1.0",
                {
                    "ara_server": "1.7.2",
                    "vault": "1.19.5",
                    "redis": "7.4.4-alpine",
                    "homer": "v25.05.2",
                },
            ),
            (
                "9.3.0",
                {
                    "ara_server": "1.7.3",
                    "vault": "1.19.5",
                    "redis": "7.4.4-alpine",
                    "homer": "v25.08.1",
                },
            ),
        ]:
            v_dir = os.path.join(self.release_dir, version)
            os.makedirs(v_dir)
            with open(os.path.join(v_dir, "base.yml"), "w") as f:
                yaml.dump({"docker_images": images}, f)

        # Build minimal metalbox structure
        scripts_dir = os.path.join(self.metalbox_dir, "scripts")
        zuul_dir = os.path.join(self.metalbox_dir, "zuul", "vars")
        os.makedirs(scripts_dir)
        os.makedirs(zuul_dir)

        # Filter config -- deliberately omit homer to test error
        with open(os.path.join(scripts_dir, "metalbox-images.yml"), "w") as f:
            yaml.dump(
                {
                    "images": ["ara_server", "vault", "redis"],
                    "unmanaged": ["library/httpd:alpine"],
                },
                f,
            )

        # Existing zuul file
        with open(os.path.join(zuul_dir, "container-images.yml"), "w") as f:
            yaml.dump(
                {
                    "images": ["old:1.0"],
                    "images_manager": ["old-mgr:1.0"],
                    "images_kolla_metalbox": ["cron:2024.2", "ironic-api:2024.2"],
                },
                f,
            )

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_error_on_unknown_upstream_image(self):
        """homer is in release but not in filter -> error."""
        ret = run(
            release_repo=self.release_dir,
            major=9,
            filter_path=os.path.join(
                self.metalbox_dir, "scripts", "metalbox-images.yml"
            ),
            zuul_path=os.path.join(
                self.metalbox_dir, "zuul", "vars", "container-images.yml"
            ),
        )
        self.assertEqual(ret, 1)

    def test_success_when_filter_is_complete(self):
        """Add homer to filter -> success."""
        filter_path = os.path.join(self.metalbox_dir, "scripts", "metalbox-images.yml")
        with open(filter_path, "w") as f:
            yaml.dump(
                {
                    "images": ["ara_server", "homer", "vault", "redis"],
                    "unmanaged": ["library/httpd:alpine"],
                },
                f,
            )

        zuul_path = os.path.join(
            self.metalbox_dir, "zuul", "vars", "container-images.yml"
        )
        ret = run(
            release_repo=self.release_dir,
            major=9,
            filter_path=filter_path,
            zuul_path=zuul_path,
        )
        self.assertEqual(ret, 0)

        with open(zuul_path) as f:
            result = yaml.safe_load(f)

        # Check images (non-osism)
        self.assertIn("hashicorp/vault:1.19.1", result["images"])
        self.assertIn("hashicorp/vault:1.19.5", result["images"])
        self.assertIn("library/redis:7.4.2-alpine", result["images"])
        self.assertIn("library/redis:7.4.4-alpine", result["images"])
        self.assertIn("library/httpd:alpine", result["images"])

        # Check images_manager (osism, prefix stripped)
        self.assertIn("ara-server:1.7.2", result["images_manager"])
        self.assertIn("ara-server:1.7.3", result["images_manager"])
        self.assertIn("homer:v25.04.1", result["images_manager"])

        # Kolla preserved
        self.assertEqual(
            result["images_kolla_metalbox"],
            ["cron:2024.2", "ironic-api:2024.2"],
        )

    def test_keep_latest_preserves_existing_tags(self):
        """--keep-latest reads existing zuul file and preserves :latest."""
        filter_path = os.path.join(self.metalbox_dir, "scripts", "metalbox-images.yml")
        with open(filter_path, "w") as f:
            yaml.dump(
                {
                    "images": ["ara_server", "homer", "vault", "redis"],
                    "unmanaged": ["library/httpd:alpine"],
                },
                f,
            )

        zuul_path = os.path.join(
            self.metalbox_dir, "zuul", "vars", "container-images.yml"
        )
        # Write existing zuul file with vault:latest
        with open(zuul_path, "w") as f:
            f.write("---\n")
            yaml.dump(
                {
                    "images": ["hashicorp/vault:latest", "library/httpd:alpine"],
                    "images_manager": ["ara-server:1.7.2"],
                    "images_kolla_metalbox": [],
                },
                f,
                default_flow_style=False,
                sort_keys=False,
            )

        ret = run(
            release_repo=self.release_dir,
            major=9,
            filter_path=filter_path,
            zuul_path=zuul_path,
            keep_latest=True,
        )
        self.assertEqual(ret, 0)

        with open(zuul_path) as f:
            result = yaml.safe_load(f)

        # vault had :latest in existing file -> preserved
        vault_entries = [
            e for e in result["images"] if e.startswith("hashicorp/vault:")
        ]
        self.assertEqual(vault_entries, ["hashicorp/vault:latest"])
        # ara-server did NOT have :latest -> expanded
        ara_entries = [
            e for e in result["images_manager"] if e.startswith("ara-server:")
        ]
        self.assertIn("ara-server:1.7.2", ara_entries)
        self.assertIn("ara-server:1.7.3", ara_entries)

    def test_unmanaged_manager_in_end_to_end(self):
        """unmanaged_manager entries go to images_manager."""
        filter_path = os.path.join(self.metalbox_dir, "scripts", "metalbox-images.yml")
        with open(filter_path, "w") as f:
            yaml.dump(
                {
                    "images": ["ara_server", "homer", "vault", "redis"],
                    "unmanaged": ["library/httpd:alpine"],
                    "unmanaged_manager": ["rsync:latest"],
                },
                f,
            )

        zuul_path = os.path.join(
            self.metalbox_dir, "zuul", "vars", "container-images.yml"
        )
        ret = run(
            release_repo=self.release_dir,
            major=9,
            filter_path=filter_path,
            zuul_path=zuul_path,
        )
        self.assertEqual(ret, 0)

        with open(zuul_path) as f:
            result = yaml.safe_load(f)

        self.assertIn("rsync:latest", result["images_manager"])
        self.assertNotIn("rsync:latest", result["images"])


if __name__ == "__main__":
    unittest.main()
