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

import argparse
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple

import yaml

import image_refs as images

HERE = Path(__file__).resolve().parent

# Kept at their manager-stable tag: no release key pins these repositories.
# They win over generics, whose render may still include an entry for the
# same repository; none of RUNNER_ROLES resolves to a STATIC repository, so
# the runner never contends for one.
STATIC = frozenset(
    {"library/httpd", "library/nginx", "library/registry", "osism/rsync"}
)
CEPH_DAEMON = "osism/ceph-daemon"
CEPHCLIENT = "osism/cephclient"

MANAGER_STABLE = HERE / "vars" / "container-images-manager-stable.yml"
RELEASE_GIT = "https://github.com/osism/release"
RAW = "https://raw.githubusercontent.com/osism/{repo}/{ref}/{path}"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RUNNERS = {
    "osism-ansible": ("versions.yml",),
    "ceph-ansible": ("versions.yml",),
    "kolla-ansible": ("versions.yml",),
}

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


def fetch(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "metalbox/resolve-container-images-latest"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode()
    except urllib.error.HTTPError as e:
        raise Fatal(f"{url}: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise Fatal(f"{url}: {e.reason}") from e


def release_commit(run=subprocess.run):
    """The commit of osism/release main, so every fetch reads one snapshot."""
    cmd = ["git", "ls-remote", RELEASE_GIT, "refs/heads/main"]
    try:
        stdout = run(cmd, check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise Fatal(f"{' '.join(cmd)}: {e}") from e
    fields = stdout.split()
    if not fields or not SHA_RE.match(fields[0]):
        raise Fatal(f"{' '.join(cmd)}: no commit in {stdout!r}")
    return fields[0]


def render_generics(commit, workdir, fetch=fetch, run=subprocess.run):
    """Run generics' render-images.py for latest; return (rendered, generics_version).

    generics is fetched at the generics_version a latest pod pins, and the
    script reads osism/release at commit, not at main.
    """
    base_url = RAW.format(repo="release", ref=commit, path="latest/base.yml")
    version = images.load_yaml(fetch(base_url)).get("generics_version")
    if not version:
        raise Fatal(f"{base_url}: no generics_version")
    for path, name in (
        ("environments/manager/images.yml", "images.yml.j2"),
        ("src/render-images.py", "render-images.py"),
    ):
        (workdir / name).write_text(
            fetch(RAW.format(repo="generics", ref=version, path=path))
        )
    env = dict(
        os.environ,
        MANAGER_VERSION="latest",
        VERSIONS_URL=base_url,
        IMAGES_URL=RAW.format(repo="release", ref=commit, path="etc/images.yml"),
        IMAGES_TEMPLATE_PATH="images.yml.j2",
        IMAGES_PATH="images.yml",
    )
    try:
        run(
            [sys.executable, "render-images.py"],
            cwd=workdir,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise Fatal(f"generics {version} render-images.py failed:\n{e.stderr}") from e
    return images.load_yaml((workdir / "images.yml").read_text()), version


def read_role_defaults(directory):
    """Return {(collection, role): data} for the RUNNER_ROLES extracted from
    the osism-ansible runner (<directory>/osism-ansible/<collection>/roles/)."""
    out = {}
    for collection, roles in RUNNER_ROLES.items():
        for role in roles:
            path = (
                directory
                / "osism-ansible"
                / collection
                / "roles"
                / role
                / "defaults"
                / "main.yml"
            )
            try:
                out[(collection, role)] = images.load_yaml(path.read_text())
            except OSError as e:
                raise Fatal(
                    f"runner osism-ansible: osism.{collection}.{role}: {e}"
                ) from e
    return out


def read_runner(directory, name):
    """Return (digest, {filename: data}) for one runner extracted by the playbook."""
    base = directory / name
    try:
        digest = (base / "digest").read_text().strip()
        files = {f: images.load_yaml((base / f).read_text()) for f in RUNNERS[name]}
    except OSError as e:
        raise Fatal(f"runner {name}: {e}") from e
    if not digest.startswith("sha256:"):
        raise Fatal(f"runner {name}: digest file does not hold a sha256 digest")
    return digest, files


def write_atomic(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Resolve the manager image set of a latest registry tarball."
    )
    parser.add_argument("--openstack-version", required=True)
    parser.add_argument("--ceph-version", required=True)
    parser.add_argument(
        "--runner-images",
        type=Path,
        required=True,
        help="files extracted from the copied runners",
    )
    parser.add_argument("--output", type=Path, required=True, help="vars file to write")
    parser.add_argument(
        "--manifest", type=Path, required=True, help="manifest to write"
    )
    parser.add_argument("--manager-stable", type=Path, default=MANAGER_STABLE)
    return parser.parse_args(argv)


def main(argv=None, commit_of=release_commit, render=render_generics):
    args = parse_args(argv)
    site = {
        "manager_version": "latest",
        "openstack_version": args.openstack_version,
        "ceph_version": args.ceph_version,
    }
    warnings = []
    try:
        commit = commit_of()
        with tempfile.TemporaryDirectory() as tmp:
            generics, generics_version = render(commit, Path(tmp))
        runners = {name: read_runner(args.runner_images, name) for name in RUNNERS}
        resolved = resolve(
            generics,
            read_role_defaults(args.runner_images),
            runners["osism-ansible"][1]["versions.yml"],
            runners["kolla-ansible"][1]["versions.yml"],
            runners["ceph-ansible"][1]["versions.yml"],
            images.load_yaml(args.manager_stable.read_text()),
            site,
            warnings,
        )
    except (Fatal, images.RenderError, OSError, yaml.YAMLError) as e:
        for key, message in warnings:
            print(f"WARNING skipped runner entry {key}: {message}", file=sys.stderr)
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    for key, message in warnings:
        print(f"WARNING skipped runner entry {key}: {message}")
    for entry in resolved:
        print(f"{entry.source:14} {entry.ref}")

    manifest = {
        "release_commit": commit,
        "generics_version": generics_version,
        "openstack_version": args.openstack_version,
        "ceph_version": args.ceph_version,
        "runners": {name: runners[name][0] for name in RUNNERS},
        "images": [
            {"image": str(entry.ref), "source": entry.source} for entry in resolved
        ],
    }
    write_atomic(
        args.output,
        "---\n" + yaml.safe_dump(vars_lists(resolved), default_flow_style=False),
    )
    write_atomic(
        args.manifest,
        "---\n" + yaml.safe_dump(manifest, default_flow_style=False, sort_keys=False),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
