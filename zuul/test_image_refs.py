"""Tests for zuul/image_refs.py.

Run with: python3 -m unittest discover -s zuul
"""

import tempfile
import unittest
from pathlib import Path

import image_refs as images

IMAGES = """\
---
ara_server_tag: "1.8.0-r1"
ara_server_image: "{{ docker_registry_ansible|default('registry.osism.tech') }}/osism/ara-server:{{ ara_server_tag }}"
ceph_ansible_tag: "{{ ceph_version|default('quincy') }}"
ceph_ansible_image: "{{ docker_registry_ansible|default('registry.osism.tech') }}/osism/ceph-ansible:{{ ceph_ansible_tag }}"
patchman_memcached_tag: "1.6.45-alpine"
patchman_memcached_image: "{{ docker_registry_memcached }}/memcached:{{ patchman_memcached_tag }}"
"""

ROOT = Path(__file__).resolve().parent.parent


class PlaceholderModeTest(unittest.TestCase):
    def test_renders_through_registry_variables(self):
        refs = images.image_refs(images.load_yaml(IMAGES), {"ceph_version": "reef"})
        self.assertEqual(
            {k: str(v) for k, v in refs.items()},
            {
                "ara_server_image": "osism/ara-server:1.8.0-r1",
                "ceph_ansible_image": "osism/ceph-ansible:reef",
                "patchman_memcached_image": "library/memcached:1.6.45-alpine",
            },
        )

    def test_default_applies_without_site_value(self):
        refs = images.image_refs(images.load_yaml(IMAGES), {})
        self.assertEqual(str(refs["ceph_ansible_image"]), "osism/ceph-ansible:quincy")

    def test_site_registry_values_do_not_leak_into_refs(self):
        context = {"docker_registry_ansible": "192.168.16.20:5001"}
        refs = images.image_refs(images.load_yaml(IMAGES), context)
        self.assertEqual(str(refs["ara_server_image"]), "osism/ara-server:1.8.0-r1")

    def test_load_yaml_keeps_versions_as_strings(self):
        data = images.load_yaml("openstack_version: 2025.1\nregistry_tag: 3.0\n")
        self.assertEqual(data, {"openstack_version": "2025.1", "registry_tag": "3.0"})

    def test_registry_named_values_that_are_not_registries_render(self):
        data = {
            "registry_tag": "3.0",
            "registry_image": "{{ docker_registry }}/library/registry:{{ registry_tag }}",
            "x_image": "{{ dnsmasq_docker_registry }}/osism/x:{{ registry_tag }}",
        }
        refs = images.image_refs(data, {})
        self.assertEqual(str(refs["registry_image"]), "library/registry:3.0")
        self.assertEqual(str(refs["x_image"]), "osism/x:3.0")

    def test_hardcoded_host_is_an_error(self):
        data = {"homer_image": "ghcr.io/bastienwirtz/homer:v25.10.1"}
        with self.assertRaisesRegex(images.RenderError, "homer_image"):
            images.image_refs(data, {})

    def test_undefined_variable_is_an_error(self):
        data = {"x_image": "{{ docker_registry }}/osism/x:{{ x_version }}"}
        with self.assertRaisesRegex(images.RenderError, "x_image"):
            images.image_refs(data, {})

    def test_errors_list_skips_instead_of_raising(self):
        data = images.load_yaml(IMAGES)
        data["homer_image"] = "ghcr.io/bastienwirtz/homer:v25.10.1"
        errors = []
        refs = images.image_refs(data, {"ceph_version": "reef"}, errors)
        self.assertNotIn("homer_image", refs)
        self.assertEqual([key for key, _ in errors], ["homer_image"])
        self.assertIn("ara_server_image", refs)

    def test_circular_reference_is_an_error(self):
        data = {
            "a_image": "{{ docker_registry }}/osism/a:{{ a_tag }}",
            "a_tag": "{{ a_image }}",
        }
        with self.assertRaisesRegex(images.RenderError, "circular"):
            images.image_refs(data, {})


class RegistryModeTest(unittest.TestCase):
    BOX = "localhost:5001"

    def test_configured_registry_is_stripped(self):
        data = images.load_yaml(IMAGES)
        data["docker_registry_ansible"] = self.BOX
        data["docker_registry_memcached"] = self.BOX + "/library"
        refs = images.image_refs(data, data, registry=self.BOX)
        self.assertEqual(str(refs["ara_server_image"]), "osism/ara-server:1.8.0-r1")
        self.assertEqual(
            str(refs["patchman_memcached_image"]), "library/memcached:1.6.45-alpine"
        )

    def test_path_in_registry_variable_is_kept(self):
        data = images.load_yaml(IMAGES)
        data["docker_registry_ansible"] = self.BOX + "/custom"
        data["docker_registry_memcached"] = self.BOX
        refs = images.image_refs(data, data, registry=self.BOX)
        self.assertEqual(
            str(refs["ara_server_image"]), "custom/osism/ara-server:1.8.0-r1"
        )

    def test_no_library_prefix_is_invented(self):
        data = images.load_yaml(IMAGES)
        data["docker_registry_ansible"] = self.BOX
        data["docker_registry_memcached"] = self.BOX
        refs = images.image_refs(data, data, registry=self.BOX)
        self.assertEqual(
            str(refs["patchman_memcached_image"]), "memcached:1.6.45-alpine"
        )

    def test_reference_outside_the_registry_is_an_error(self):
        data = images.load_yaml(IMAGES)
        data["docker_registry_memcached"] = self.BOX
        # docker_registry_ansible unset: its default() points at registry.osism.tech
        with self.assertRaisesRegex(images.RenderError, "ara_server_image"):
            images.image_refs(data, data, registry=self.BOX)

    def test_host_prefix_must_end_at_a_slash(self):
        data = {"x_tag": "1", "x_image": "localhost:50011/osism/x:{{ x_tag }}"}
        with self.assertRaisesRegex(images.RenderError, "x_image"):
            images.image_refs(data, data, registry=self.BOX)


class LoadManagerConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.manager = self.root / "environments" / "manager"
        (self.manager / "group_vars" / "all").mkdir(parents=True)
        (self.manager / "host_vars" / "box").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative, text):
        path = self.root / "environments" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_precedence_matches_the_manager_deploy(self):
        self.write("manager/group_vars/all/registries.yml", "a: group\nb: group\n")
        self.write("manager/host_vars/box/vars.yml", "b: host\nc: host\n")
        self.write("images.yml", "c: env-images\nd: env-images\n")
        self.write("configuration.yml", "d: env-config\ne: env-config\n")
        self.write("manager/images.yml", "e: images\nf: images\n")
        self.write("manager/configuration.yml", "f: config\n")
        data = images.load_manager_configuration(self.root, "box")
        self.assertEqual(
            data,
            {
                "a": "group",
                "b": "host",
                "c": "env-images",
                "d": "env-config",
                "e": "images",
                "f": "config",
            },
        )

    def test_manager_group_vars_sit_between_all_and_host_vars(self):
        self.write("manager/images.yml", "x: images\n")
        self.write("manager/group_vars/all/vars.yml", "a: all\nb: all\n")
        self.write("manager/group_vars/manager/vars.yml", "b: manager\nc: manager\n")
        self.write("manager/host_vars/box/vars.yml", "c: host\n")
        data = images.load_manager_configuration(self.root, "box")
        self.assertEqual((data["a"], data["b"], data["c"]), ("all", "manager", "host"))

    def test_single_file_forms_are_read(self):
        (self.manager / "group_vars" / "all").rmdir()
        (self.manager / "host_vars" / "box").rmdir()
        self.write("manager/images.yml", "x: images\n")
        self.write("manager/group_vars/all.yml", "a: all\nb: all\n")
        self.write("manager/group_vars/manager.yaml", "b: manager\nc: manager\n")
        self.write("manager/host_vars/box.yml", "c: host\n")
        data = images.load_manager_configuration(self.root, "box")
        self.assertEqual((data["a"], data["b"], data["c"]), ("all", "manager", "host"))

    def test_yaml_extension_is_read_in_sorted_order(self):
        self.write("manager/images.yml", "x: images\n")
        self.write("manager/group_vars/all/a.yaml", "a: a-yaml\nb: a-yaml\n")
        self.write("manager/group_vars/all/b.yml", "b: b-yml\n")
        self.write("manager/group_vars/all/notes.txt", "a: ignored\n")
        data = images.load_manager_configuration(self.root, "box")
        self.assertEqual((data["a"], data["b"]), ("a-yaml", "b-yml"))

    def test_directory_form_shadows_single_file(self):
        # Ansible reads only the first of name/, name.yml, name.yaml.
        self.write("manager/images.yml", "x: images\n")
        self.write("manager/group_vars/all/vars.yml", "a: directory\n")
        self.write("manager/group_vars/all.yml", "a: file\nb: file\n")
        data = images.load_manager_configuration(self.root, "box")
        self.assertEqual(data["a"], "directory")
        self.assertNotIn("b", data)

    def test_missing_manager_images_is_an_error(self):
        with self.assertRaises(OSError):
            images.load_manager_configuration(self.root, "box")

    def test_other_hosts_are_not_read(self):
        self.write("manager/images.yml", "x: images\n")
        self.write("manager/host_vars/other/vars.yml", "y: other\n")
        data = images.load_manager_configuration(self.root, "box")
        self.assertNotIn("y", data)


class ShippedBoxConfigurationTest(unittest.TestCase):
    def test_every_box_image_renders_through_the_box_registry(self):
        data = images.load_manager_configuration(ROOT, "metalbox")
        errors = []
        refs = images.image_refs(data, data, errors, registry="localhost:5001")
        self.assertEqual(errors, [])
        self.assertGreater(len(refs), 5)


if __name__ == "__main__":
    unittest.main()
