#!/usr/bin/env python3
"""
Resolve the manager image set of a latest registry tarball.

A latest CloudPod (manager_version: latest) pulls its manager images at tags
from the place that deploys each service, and this resolves each from there:

  generics   environments/manager/images.yml as generics' render-images.py
             renders it for latest, at the generics version and osism/release
             commit a latest pod would use. It is the source only for the
             manager environment (ara, netbox, traefik, vault, the runners, ...),
             whose plays load that file.
  runner     every other service osism-ansible deploys (step-ca, squid,
             adminer, the otel collector, ...): each role's <x>_image from its
             defaults/main.yml in the collections of the copied osism-ansible
             runner, rendered with the runners' versions.yml in the inventory
             reconciler's order -- role defaults < ceph-ansible < kolla-ansible
             < osism-ansible < site. These are the pins of the image build, not
             today's osism/release main.
  ceph       ceph_image_version from that same context, and cephclient_image
             from the cephclient role.

Which manager images belong in the tarball is container-images-manager-stable.yml:
the same images a stable pod's manager runs, at other tags. Entries are
matched by repository. generics' output is included whole, except for the
repositories a runner role owns.

Exit status: 0 resolved, 1 anything unresolved or any input unavailable.
"""

from typing import NamedTuple

import image_refs as images

# Kept at their manager-stable tag: no release key pins these repositories.
# They win over generics, whose render may still include an entry for the
# same repository; none of RUNNER_ROLES resolves to a STATIC repository, so
# the runner never contends for one.
STATIC = frozenset(
    {"library/httpd", "library/nginx", "library/registry", "osism/rsync"}
)
CEPH_DAEMON = "osism/ceph-daemon"
CEPHCLIENT = "osism/cephclient"

# The services osism-ansible deploys outside the manager environment whose
# images a latest tarball carries, by collection. Their tags come from the
# runner, never from generics, even where generics also renders them.
RUNNER_ROLES = {
    "services": (
        "adminer",
        "cephclient",
        "dnsdist",
        "dnsmasq",
        "gnmic",
        "openstackclient",
        "opentelemetry_collector",
        "phpmyadmin",
        "squid",
        "stepca",
    ),
    "validations": ("tempest",),
}


class Fatal(Exception):
    pass


class Resolved(NamedTuple):
    ref: images.ImageRef
    source: str


def split_entry(item):
    name, sep, tag = item.rpartition(":")
    if not sep or not name or not tag:
        raise Fatal(f"{item}: entry has no tag")
    return images.ImageRef(name, tag)


def manager_stable_refs(data):
    refs = [
        split_entry(item) for item in data.get("images_manager_stable_external") or []
    ]
    refs += [
        split_entry("osism/" + item) for item in data.get("images_manager_stable") or []
    ]
    return refs


def tags_by_repository(refs):
    tags = {}
    for ref in refs:
        tags.setdefault(ref.repository, set()).add(ref.tag)
    return {repository: sorted(found) for repository, found in tags.items()}


def runner_context(role_defaults, ceph_versions, kolla_versions, osism_versions, site):
    """One role's variables as the inventory reconciler layers them for a run.

    role defaults < 100-versions-ceph-ansible < -kolla-ansible < -osism-ansible
    < site: the reconciler copies each runner's versions.yml to
    group_vars/all/100-versions-<runner>.yml, which sort in that order and all
    beat role defaults; the site values stand for the configuration.
    """
    return {
        **role_defaults,
        **ceph_versions,
        **kolla_versions,
        **osism_versions,
        **site,
    }


def runner_refs(
    role_defaults, ceph_versions, kolla_versions, osism_versions, site, warnings
):
    """Return the ImageRefs of the RUNNER_ROLES, rendered in runner_context.

    role_defaults maps (collection, role) to that role's defaults/main.yml;
    roles outside RUNNER_ROLES are ignored. A missing role raises Fatal. An
    <x>_image of a listed role that does not render is appended to warnings.
    """
    refs = []
    for collection, roles in RUNNER_ROLES.items():
        for role in roles:
            defaults = role_defaults.get((collection, role))
            if defaults is None:
                raise Fatal(
                    f"runner osism-ansible: no defaults for osism.{collection}.{role}"
                )
            data = runner_context(
                defaults, ceph_versions, kolla_versions, osism_versions, site
            )
            refs += images.image_refs(data, {}, warnings).values()
    return refs


def resolve(
    generics,
    role_defaults,
    osism_versions,
    kolla_versions,
    ceph_versions,
    manager_stable,
    site,
    warnings,
):
    """Return the manager set of a latest pod as Resolved entries, sorted by image.

    Runner entries that do not render are appended to warnings and skipped.
    Anything the pod needs that cannot be resolved raises Fatal.
    """
    generics_tags = tags_by_repository(images.image_refs(generics, site).values())
    # The pins below are read from the runners copied at these tags; a pod
    # pulling another runner tag would deploy with other pins.
    for repository, expected in (
        ("osism/osism-ansible", "latest"),
        ("osism/kolla-ansible", site["openstack_version"]),
        ("osism/ceph-ansible", site["ceph_version"]),
    ):
        found = generics_tags.get(repository, [])
        if found != [expected]:
            raise Fatal(
                f"{repository}: generics renders {', '.join(found) or 'nothing'},"
                f" the runner copied is {expected}"
            )
    runner_tags = tags_by_repository(
        runner_refs(
            role_defaults, ceph_versions, kolla_versions, osism_versions, site, warnings
        )
    )

    resolved = set()
    unresolved = []
    listed = manager_stable_refs(manager_stable)
    for entry in listed:
        repository = entry.repository
        if repository in STATIC:
            source, tags = "static", [entry.tag]
        elif repository in runner_tags:
            source, tags = "runner", runner_tags[repository]
        elif repository in generics_tags:
            source, tags = "generics", generics_tags[repository]
        else:
            unresolved.append(str(entry))
            continue
        resolved.update(
            Resolved(images.ImageRef(repository, tag), source) for tag in tags
        )

    names = {entry.repository for entry in listed}
    for repository, tags in generics_tags.items():
        if repository not in names and repository not in runner_tags:
            resolved.update(
                Resolved(images.ImageRef(repository, tag), "generics-only")
                for tag in tags
            )

    ceph_context = runner_context(
        {}, ceph_versions, kolla_versions, osism_versions, site
    )
    daemon_tag = ceph_context.get("ceph_image_version") or ""
    if not daemon_tag or "{{" in daemon_tag:
        unresolved.append(f"{CEPH_DAEMON} (no ceph_image_version in any runner)")
    else:
        resolved.add(Resolved(images.ImageRef(CEPH_DAEMON, daemon_tag), "ceph"))
    if CEPHCLIENT in runner_tags:
        resolved.update(
            Resolved(images.ImageRef(CEPHCLIENT, tag), "ceph")
            for tag in runner_tags[CEPHCLIENT]
        )
    else:
        unresolved.append(f"{CEPHCLIENT} (no cephclient_image in the cephclient role)")

    if unresolved:
        raise Fatal("unresolved: " + ", ".join(unresolved))
    return sorted(resolved, key=lambda r: str(r.ref))


def vars_lists(resolved):
    """Split Resolved entries into the vars the mirror playbook loops over."""
    lists = {
        "images_manager_latest_external": [],
        "images_manager_latest": [],
        "images_ceph_latest": [],
    }
    for entry in resolved:
        ref = str(entry.ref)
        if entry.source == "ceph":
            lists["images_ceph_latest"].append(ref.removeprefix("osism/"))
        elif entry.ref.repository.startswith("osism/"):
            lists["images_manager_latest"].append(ref.removeprefix("osism/"))
        else:
            lists["images_manager_latest_external"].append(ref)
    return lists
