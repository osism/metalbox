"""Tests for resolve-container-images-latest.py.

Run with: python3 -m unittest discover -s zuul
"""

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("resolve-container-images-latest.py")
spec = importlib.util.spec_from_file_location("resolve_container_images_latest", SCRIPT)
resolver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolver)
load_yaml = resolver.images.load_yaml

# generics' images.yml as render-images.py leaves it: first-level values
# filled in, second-level {{ }} still to resolve.
GENERICS = """\
---
ara_server_tag: "1.8.0-r1"
ara_server_image: "{{ docker_registry_ansible|default('registry.osism.tech') }}/osism/ara-server:{{ ara_server_tag }}"
ara_server_mariadb_tag: "11.8.8"
ara_server_mariadb_image: "{{ docker_registry|default('registry.osism.tech/dockerhub') }}/library/mariadb:{{ ara_server_mariadb_tag }}"
manager_redis_tag: "7.4.10-alpine"
manager_redis_image: "{{ docker_registry|default('registry.osism.tech/dockerhub') }}/library/redis:{{ manager_redis_tag }}"
netbox_redis_tag: "7.4.9-alpine"
netbox_redis_image: "{{ docker_registry|default('registry.osism.tech/dockerhub') }}/library/redis:{{ netbox_redis_tag }}"
osism_ansible_tag: "latest"
osism_ansible_image: "{{ docker_registry_ansible|default('registry.osism.tech') }}/osism/osism-ansible:{{ osism_ansible_tag }}"
ceph_ansible_tag: "{{ ceph_version|default('quincy') }}"
ceph_ansible_image: "{{ docker_registry_ansible|default('registry.osism.tech') }}/osism/ceph-ansible:{{ ceph_ansible_tag }}"
kolla_ansible_tag: "{{ openstack_version|default('2024.2') }}"
kolla_ansible_image: "{{ docker_registry_ansible|default('registry.osism.tech') }}/osism/kolla-ansible:{{ kolla_ansible_tag }}"
new_thing_tag: "1.0"
new_thing_image: "{{ docker_registry_ansible|default('registry.osism.tech') }}/osism/new-thing:{{ new_thing_tag }}"
adminer_tag: "5.4.0"
adminer_image: "{{ docker_registry|default('registry.osism.tech/dockerhub') }}/library/adminer:{{ adminer_tag }}"
"""

# defaults/main.yml of the RUNNER_ROLES, as extracted from the osism-ansible
# runner's collections: the role defaults the reconciler's layers override.
ROLE_DEFAULTS = {
    ("services", "adminer"): """\
---
docker_registry: index.docker.io
docker_registry_adminer: "{{ docker_registry }}"
adminer_tag: '4.7'
adminer_image: "{{ docker_registry_adminer }}/library/adminer:{{ adminer_tag }}"
""",
    ("services", "cephclient"): """\
---
docker_registry_cephclient: registry.osism.tech
cephclient_version: "{{ ceph_version }}"
cephclient_tag: "{{ cephclient_version }}"
cephclient_image: "{{ docker_registry_cephclient }}/osism/cephclient:{{ cephclient_tag }}"
""",
    ("services", "dnsdist"): """\
---
docker_registry_dnsdist: registry.osism.tech
dnsdist_tag: '1.9.8'
dnsdist_image: "{{ docker_registry_dnsdist }}/osism/dnsdist:{{ dnsdist_tag }}"
""",
    ("services", "dnsmasq"): """\
---
dnsmasq_docker_registry: registry.osism.tech
dnsmasq_tag: '2.90'
dnsmasq_image: "{{ dnsmasq_docker_registry }}/osism/dnsmasq-osism:{{ dnsmasq_tag }}"
""",
    ("services", "gnmic"): """\
---
docker_registry: registry.osism.tech
gnmic_docker_registry: "{{ docker_registry }}"
gnmic_tag: '0.41.0'
gnmic_image: "{{ gnmic_docker_registry }}/osism/gnmic:{{ gnmic_tag }}"
""",
    ("services", "openstackclient"): """\
---
docker_registry_openstackclient: registry.osism.tech
openstackclient_version: "{{ openstack_version }}"
openstackclient_tag: "{{ openstackclient_version }}"
openstackclient_image: "{{ docker_registry_openstackclient }}/osism/openstackclient:{{ openstackclient_tag }}"
""",
    ("services", "opentelemetry_collector"): """\
---
docker_registry_opentelemetry_collector: docker.io
opentelemetry_collector_version: '0.136.0'
opentelemetry_collector_tag: "{{ opentelemetry_collector_version }}"
opentelemetry_collector_image: "{{ docker_registry_opentelemetry_collector }}/otel/opentelemetry-collector-contrib:{{ opentelemetry_collector_tag }}"
""",
    ("services", "phpmyadmin"): """\
---
docker_registry: index.docker.io
docker_registry_phpmyadmin: "{{ docker_registry }}"
phpmyadmin_tag: '5.2'
phpmyadmin_image: "{{ docker_registry_phpmyadmin }}/phpmyadmin/phpmyadmin:{{ phpmyadmin_tag }}"
""",
    ("services", "squid"): """\
---
docker_registry_squid: index.docker.io
squid_tag: 6.1-23.10_beta
squid_image: "{{ docker_registry_squid }}/ubuntu/squid:{{ squid_tag }}"
""",
    ("services", "stepca"): """\
---
docker_registry_stepca: index.docker.io
stepca_tag: '0.28.4'
stepca_image: "{{ docker_registry_stepca }}/smallstep/step-ca:{{ stepca_tag }}"
""",
    ("validations", "tempest"): """\
---
docker_registry_tempest: registry.osism.tech
tempest_osism_tag: latest
tempest_osism_image: "{{ docker_registry_tempest }}/osism/tempest:{{ tempest_osism_tag }}"
tempest_image_ref: Cirros 0.6.3
""",
}

# group_vars/all/versions.yml of the osism-ansible runner (latest build).
RUNNER_VERSIONS = """\
---
osism_ansible_version: "latest"
manager_version: "latest"
adminer_tag: "5.5.1"
dnsdist_tag: "1.9.8"
dnsmasq_tag: "2.91"
gnmic_tag: "0.41.0"
opentelemetry_collector_version: "0.161.0"
phpmyadmin_tag: "5.2.3"
squid_tag: "6.1-23.10_beta"
stepca_tag: "0.30.2"
tempest_osism_tag: "latest"
"""

# group_vars/all/versions.yml of the kolla-ansible runner.
KOLLA_VERSIONS = """\
---
openstack_version: "2025.1"
kolla_image_version: "{{ openstack_version }}"
openstackclient_version: "2025.1"
"""

CEPH_VERSIONS = """\
---
ceph_version: ""
ceph_image_version: "reef"
ceph_ansible_version: "reef"
cephclient_version: "reef"
"""

MANAGER_STABLE = """\
---
images_manager_stable_external:
  - library/adminer:5.5.1
  - library/httpd:alpine
  - library/mariadb:11.8.4
  - library/nginx:1.29.3-alpine
  - library/redis:7.4.7-alpine
  - otel/opentelemetry-collector-contrib:0.158.0
  - phpmyadmin/phpmyadmin:5.2.3
  - smallstep/step-ca:0.30.2
  - ubuntu/squid:6.0

images_manager_stable:
  - ara-server:1.7.5
  - ceph-ansible:0.20260811.0
  - dnsdist:1.9.8
  - dnsmasq-osism:2.91
  - gnmic:0.41.0
  - kolla-ansible:0.20260814.0
  - openstackclient:2025.1
  - osism-ansible:0.20260811.0
  - rsync:latest
  - tempest:latest
"""

SITE = {
    "manager_version": "latest",
    "openstack_version": "2025.1",
    "ceph_version": "reef",
}


def role_defaults():
    return {key: load_yaml(text) for key, text in ROLE_DEFAULTS.items()}


def run_resolve(**overrides):
    args = {
        "generics": load_yaml(GENERICS),
        "role_defaults": role_defaults(),
        "osism_versions": load_yaml(RUNNER_VERSIONS),
        "kolla_versions": load_yaml(KOLLA_VERSIONS),
        "ceph_versions": load_yaml(CEPH_VERSIONS),
        "manager_stable": load_yaml(MANAGER_STABLE),
        "site": SITE,
        "warnings": [],
    }
    args.update(overrides)
    return resolver.resolve(**args), args["warnings"]


class ResolveTest(unittest.TestCase):
    def test_sources(self):
        resolved, _ = run_resolve()
        self.assertEqual(
            {str(r.ref): r.source for r in resolved},
            {
                "library/adminer:5.5.1": "runner",
                "library/httpd:alpine": "static",
                "library/mariadb:11.8.8": "generics",
                "library/nginx:1.29.3-alpine": "static",
                "library/redis:7.4.10-alpine": "generics",
                "library/redis:7.4.9-alpine": "generics",
                "osism/ara-server:1.8.0-r1": "generics",
                "osism/ceph-ansible:reef": "generics",
                "osism/ceph-daemon:reef": "ceph",
                "osism/cephclient:reef": "ceph",
                "osism/dnsdist:1.9.8": "runner",
                "osism/dnsmasq-osism:2.91": "runner",
                "osism/gnmic:0.41.0": "runner",
                "osism/kolla-ansible:2025.1": "generics",
                "osism/new-thing:1.0": "generics-only",
                "osism/openstackclient:2025.1": "runner",
                "osism/osism-ansible:latest": "generics",
                "osism/rsync:latest": "static",
                "osism/tempest:latest": "runner",
                "otel/opentelemetry-collector-contrib:0.161.0": "runner",
                "phpmyadmin/phpmyadmin:5.2.3": "runner",
                "smallstep/step-ca:0.30.2": "runner",
                "ubuntu/squid:6.1-23.10_beta": "runner",
            },
        )

    def test_sorted_by_image(self):
        resolved, _ = run_resolve()
        self.assertEqual(
            [str(r.ref) for r in resolved], sorted(str(r.ref) for r in resolved)
        )

    def test_manager_environment_service_resolves_from_generics(self):
        resolved, _ = run_resolve()
        tags = [r.ref.tag for r in resolved if r.ref.repository == "osism/ara-server"]
        self.assertEqual(tags, ["1.8.0-r1"])

    def test_runner_service_resolves_from_runner_not_generics(self):
        # generics at a pinned generics_version still renders adminer (5.4.0);
        # `osism apply adminer` runs in infrastructure and never reads it.
        resolved, _ = run_resolve()
        adminer = [
            (str(r.ref), r.source)
            for r in resolved
            if r.ref.repository == "library/adminer"
        ]
        self.assertEqual(adminer, [("library/adminer:5.5.1", "runner")])

    def test_versions_override_role_defaults(self):
        refs = {str(r.ref) for r in run_resolve()[0]}
        self.assertIn("smallstep/step-ca:0.30.2", refs)
        self.assertNotIn("smallstep/step-ca:0.28.4", refs)

    def test_version_input_overrides_role_default(self):
        # The otel role's input is opentelemetry_collector_version; its _tag
        # derives from it.
        refs = {str(r.ref) for r in run_resolve()[0]}
        self.assertIn("otel/opentelemetry-collector-contrib:0.161.0", refs)

    def test_role_default_applies_when_no_runner_pins_it(self):
        versions = load_yaml(RUNNER_VERSIONS)
        del versions["stepca_tag"]
        refs = {str(r.ref) for r in run_resolve(osism_versions=versions)[0]}
        self.assertIn("smallstep/step-ca:0.28.4", refs)

    def test_openstackclient_from_kolla_versions(self):
        kolla = dict(load_yaml(KOLLA_VERSIONS), openstackclient_version="2025.1-p1")
        refs = {str(r.ref) for r in run_resolve(kolla_versions=kolla)[0]}
        self.assertIn("osism/openstackclient:2025.1-p1", refs)

    def test_osism_ansible_versions_beat_ceph_ansible(self):
        # A release build of osism-ansible carries cephclient_version; it sorts
        # after ceph-ansible's and wins, as in the reconciler.
        versions = dict(load_yaml(RUNNER_VERSIONS), cephclient_version="18.2.8")
        refs = {str(r.ref) for r in run_resolve(osism_versions=versions)[0]}
        self.assertIn("osism/cephclient:18.2.8", refs)
        self.assertNotIn("osism/cephclient:reef", refs)

    def test_role_outside_runner_roles_is_ignored(self):
        # wazuh_proxy deploys library/nginx at another tag; it is no manager
        # service and must not touch the manager's nginx.
        defaults = role_defaults()
        defaults[("services", "wazuh_proxy")] = load_yaml(
            "---\ndocker_registry: index.docker.io\n"
            'wazuh_proxy_tag: "1.31.5"\n'
            'wazuh_proxy_image: "{{ docker_registry }}/nginx:{{ wazuh_proxy_tag }}"\n'
        )
        resolved, _ = run_resolve(role_defaults=defaults)
        nginx = [str(r.ref) for r in resolved if r.ref.repository == "library/nginx"]
        self.assertEqual(nginx, ["library/nginx:1.29.3-alpine"])
        # library/nginx is STATIC, so the check above holds whatever the
        # runner renders; the role must also stay out of the runner's refs.
        warnings = []
        refs = resolver.runner_refs(
            defaults,
            load_yaml(CEPH_VERSIONS),
            load_yaml(KOLLA_VERSIONS),
            load_yaml(RUNNER_VERSIONS),
            SITE,
            warnings,
        )
        self.assertNotIn("library/nginx", {r.repository for r in refs})
        self.assertEqual(warnings, [])

    def test_missing_runner_role_fails_and_names_it(self):
        defaults = role_defaults()
        del defaults[("services", "stepca")]
        with self.assertRaisesRegex(resolver.Fatal, r"osism\.services\.stepca"):
            run_resolve(role_defaults=defaults)

    def test_broken_extra_image_in_runner_role_is_skipped(self):
        defaults = role_defaults()
        defaults[("services", "stepca")]["stepca_debug_image"] = "ghcr.io/x/debug:1"
        resolved, warnings = run_resolve(role_defaults=defaults)
        self.assertEqual([key for key, _ in warnings], ["stepca_debug_image"])
        self.assertIn("smallstep/step-ca:0.30.2", {str(r.ref) for r in resolved})

    def test_broken_generics_entry_fails(self):
        generics = load_yaml(GENERICS)
        generics["broken_image"] = "quay.io/x/y:1"
        with self.assertRaises(resolver.images.RenderError):
            run_resolve(generics=generics)

    def test_unmatched_entry_fails_and_names_it(self):
        manager_stable = load_yaml(MANAGER_STABLE)
        manager_stable["images_manager_stable_external"].append(
            "otel/opentelemetry-collector:0.158.0"
        )
        with self.assertRaisesRegex(
            resolver.Fatal, "otel/opentelemetry-collector:0.158.0"
        ):
            run_resolve(manager_stable=manager_stable)

    def test_pinned_runner_tag_in_generics_fails(self):
        # The pins are read from osism-ansible:latest; a generics pin would
        # make the pod pull another runner than the one copied.
        generics = dict(load_yaml(GENERICS), osism_ansible_tag="0.20260811.0")
        with self.assertRaisesRegex(
            resolver.Fatal, r"osism/osism-ansible.*0\.20260811\.0.*latest"
        ):
            run_resolve(generics=generics)

    def test_missing_ceph_image_version_fails(self):
        with self.assertRaisesRegex(resolver.Fatal, "ceph-daemon"):
            run_resolve(ceph_versions={})

    def test_missing_cephclient_fails(self):
        defaults = role_defaults()
        del defaults[("services", "cephclient")]["cephclient_image"]
        with self.assertRaisesRegex(resolver.Fatal, "cephclient"):
            run_resolve(role_defaults=defaults)

    def test_ceph_stream_follows_site(self):
        # The ceph-ansible:squid runner carries squid for both values.
        ceph = dict(
            load_yaml(CEPH_VERSIONS),
            ceph_image_version="squid",
            cephclient_version="squid",
        )
        resolved, _ = run_resolve(
            ceph_versions=ceph, site=dict(SITE, ceph_version="squid")
        )
        refs = {str(r.ref) for r in resolved}
        self.assertIn("osism/ceph-daemon:squid", refs)
        self.assertIn("osism/cephclient:squid", refs)
        self.assertIn("osism/ceph-ansible:squid", refs)


class VarsListsTest(unittest.TestCase):
    def test_split_by_namespace_and_source(self):
        resolved, _ = run_resolve()
        lists = resolver.vars_lists(resolved)
        self.assertEqual(
            lists["images_ceph_latest"], ["ceph-daemon:reef", "cephclient:reef"]
        )
        self.assertIn("ara-server:1.8.0-r1", lists["images_manager_latest"])
        self.assertIn("rsync:latest", lists["images_manager_latest"])
        self.assertIn(
            "library/redis:7.4.9-alpine", lists["images_manager_latest_external"]
        )
        self.assertNotIn(
            "osism/ara-server:1.8.0-r1", lists["images_manager_latest_external"]
        )


if __name__ == "__main__":
    unittest.main()
