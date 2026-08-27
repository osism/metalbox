#!/usr/bin/env python3
"""
Update zuul/vars/container-images-*-stable.yml from an OSISM release.

The two stable image lists pin every image of the stable registry tarball
(registry-stable-full.tar.bz2) to the versions of one OSISM release:

  container-images-manager-stable.yml
      Tags come from the docker_images section of <release>/base.yml in
      https://github.com/osism/release. openstackclient is not pinned in
      base.yml; like osism-ansible, the script takes it from
      latest/openstack-<version>.yml.

  container-images-openstack-stable.yml
      The kolla version in base.yml names the SBOM image
      registry.osism.tech/kolla/release/<openstack version>/sbom:<kolla>.
      Its /images.yml lists every Kolla image of that build; the tags in
      the file are replaced with the ones listed there.

Only the tags of the images already listed are updated; images are never
added or removed. Entries without a counterpart in the release (for example
library/httpd or rsync:latest) are kept unchanged and reported.

Usage: update-container-images-stable.py [-n] [-v] [-o VERSION] [RELEASE]

  RELEASE                  OSISM release, e.g. 10.2.0. Default: the newest
                           X.Y.Z release directory in osism/release.
  -o, --openstack-version  OpenStack release of the SBOM image. Default: the
                           default of the release repository
                           (latest/openstack.yml).
  -n, --dry-run            Report the changes without writing the files.
  -v, --verbose            Also report unchanged entries.

Requirements: python3 with PyYAML, docker (or crane) to read the SBOM image,
network access to github.com and registry.osism.tech. GITHUB_TOKEN is sent
to the GitHub API when set (only needed to avoid the anonymous rate limit).

Exit status: 0 on success, 1 on a fatal error (nothing is written), 2 when
the files were updated but some entries could not be resolved.
"""

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("ERROR: PyYAML is required (pip install pyyaml, or make deps)")

RELEASE_RAW = "https://raw.githubusercontent.com/osism/release/main"
RELEASE_API = "https://api.github.com/repos/osism/release/contents/"
REGISTRY = "registry.osism.tech"

REPO_ROOT = Path(__file__).resolve().parents[1]
VARS_DIR = REPO_ROOT / "zuul" / "vars"
MANAGER_FILE = VARS_DIR / "container-images-manager-stable.yml"
OPENSTACK_FILE = VARS_DIR / "container-images-openstack-stable.yml"

# Image name in container-images-manager-stable.yml -> key in the docker_images
# section of the release. Images not listed here are not pinned by the release
# and are left untouched.
MANAGER_IMAGES = {
    "images_manager_stable_external": {
        "hashicorp/vault": "vault",
        "library/adminer": "adminer",
        "library/mariadb": "mariadb",
        "library/memcached": "memcached",
        "library/phpmyadmin": "phpmyadmin",
        "library/postgres": "postgres",
        "library/redis": "redis",
        "library/traefik": "traefik",
        "otel/opentelemetry-collector": "opentelemetry_collector",
        "pgautoupgrade/pgautoupgrade": "pgautoupgrade",
        "smallstep/step-ca": "stepca",
        "ubuntu/squid": "squid",
    },
    "images_manager_stable": {
        "ara-server": "ara_server",
        "ceph-ansible": "ceph_ansible",
        "dnsdist": "dnsdist",
        "dnsmasq-osism": "dnsmasq",
        "gnmic": "gnmic",
        "inventory-reconciler": "inventory_reconciler",
        "kolla-ansible": "kolla_ansible",
        "netbox": "netbox",
        # openstackclient is taken from latest/openstack-<version>.yml
        "openstackclient": "openstackclient",
        "osism": "osism",
        "osism-ansible": "osism_ansible",
        # osism-frontend is built from the osism repository and shares its tag
        # (see osism_frontend_tag in environments/manager/images.yml)
        "osism-frontend": "osism",
        "osism-kubernetes": "osism_kubernetes",
        "tempest": "tempest",
    },
}

RELEASE_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
LIST_RE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*):\s*$")
ITEM_RE = re.compile(r"^(?P<prefix>\s*-\s+)(?P<image>\S+)\s*$")
KOLLA_ENTRY_RE = re.compile(r"^release/(?P<version>[^/]+)/(?P<name>[^/:]+):(?P<tag>[^/:]+)$")
SBOM_IMAGE_RE = re.compile(r"^(?:.*/)?kolla/release/(?P<version>[^/]+)/(?P<name>[^/:]+):(?P<tag>[^/:]+)$")


class Fatal(Exception):
    pass


def warn(message):
    print(f"WARNING: {message}", file=sys.stderr)


def fetch(url, not_found=None):
    """Return the body of url; not_found replaces the error message on 404."""
    headers = {"User-Agent": "metalbox/update-container-images-stable"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404 and not_found:
            raise Fatal(not_found) from e
        raise Fatal(f"{url}: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise Fatal(f"{url}: {e.reason}") from e


def load_yaml(text):
    # BaseLoader keeps every scalar a string, so tags such as 3.0 or 1.10 are
    # not turned into floats.
    return yaml.load(text, Loader=yaml.BaseLoader) or {}


def run(cmd):
    try:
        return subprocess.run(cmd, check=True, capture_output=True)
    except FileNotFoundError as e:
        raise Fatal(f"{cmd[0]}: command not found") from e
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace").strip()
        raise Fatal(f"{' '.join(cmd)} failed:\n{stderr}") from e


def latest_release():
    entries = json.loads(fetch(RELEASE_API))
    versions = [
        entry["name"]
        for entry in entries
        if entry.get("type") == "dir" and RELEASE_VERSION_RE.match(entry["name"])
    ]
    if not versions:
        raise Fatal("no release directories found in osism/release")
    return max(versions, key=lambda v: tuple(int(part) for part in v.split(".")))


def default_openstack_version():
    # latest/openstack.yml is a symlink; raw.githubusercontent.com serves the
    # link target as content. Fall back to the file content in case that
    # changes.
    text = fetch(f"{RELEASE_RAW}/latest/openstack.yml").strip()
    match = re.fullmatch(r"openstack-(.+)\.yml", text)
    if match:
        return match.group(1)
    version = load_yaml(text).get("openstack_version")
    if not version:
        raise Fatal(f"cannot determine the default OpenStack version from latest/openstack.yml: {text!r}")
    return version


def release_versions(release, openstack_version):
    """Return the docker_images of the release plus openstackclient."""
    base = load_yaml(
        fetch(f"{RELEASE_RAW}/{release}/base.yml", not_found=f"release {release} not found in osism/release")
    )
    versions = dict(base.get("docker_images") or {})
    if "kolla" not in versions:
        raise Fatal(f"{release}/base.yml has no docker_images.kolla entry")

    openstack = load_yaml(
        fetch(
            f"{RELEASE_RAW}/latest/openstack-{openstack_version}.yml",
            not_found=(
                f"OpenStack {openstack_version} is unknown to osism/release "
                f"(no latest/openstack-{openstack_version}.yml)"
            ),
        )
    )
    openstackclient = (openstack.get("docker_images") or {}).get("openstackclient")
    if openstackclient:
        versions["openstackclient"] = openstackclient
    else:
        warn(f"latest/openstack-{openstack_version}.yml pins no openstackclient tag")
    return versions


def sbom_via_docker(image):
    run(["docker", "pull", "--quiet", "--platform", "linux/amd64", image])
    # The SBOM image is built from scratch and has no command. docker create
    # insists on one; the container is never started, so any string will do.
    result = run(["docker", "create", "--platform", "linux/amd64", image, "/images.yml"])
    container = result.stdout.decode().strip()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            run(["docker", "cp", f"{container}:/images.yml", tmpdir])
            return Path(tmpdir, "images.yml").read_text()
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)


def sbom_via_crane(image):
    result = run(["crane", "--platform", "linux/amd64", "export", image, "-"])
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as tar:
        member = tar.extractfile("images.yml")
        if member is None:
            raise Fatal(f"{image} contains no images.yml")
        return member.read().decode()


def sbom_tags(image, openstack_version):
    """Return {image name: tag} from the images.yml inside the SBOM image."""
    if shutil.which("docker"):
        read_sbom = sbom_via_docker
    elif shutil.which("crane"):
        read_sbom = sbom_via_crane
    else:
        raise Fatal("docker or crane is required to read the SBOM image")
    try:
        text = read_sbom(image)
    except Fatal as e:
        message = str(e)
        # docker reports "repository ... not found", crane "NAME_UNKNOWN" or
        # "MANIFEST_UNKNOWN" when the release has no such SBOM image.
        if "not found" in message.lower() or "unknown" in message.lower():
            message += (
                f"\nThe release provides no kolla images for OpenStack {openstack_version}; "
                "use --openstack-version to select the matching release."
            )
        raise Fatal(message) from e

    sbom = load_yaml(text)
    sbom_version = sbom.get("openstack_version")
    if sbom_version and sbom_version != openstack_version:
        warn(f"{image} was built for OpenStack {sbom_version}, not {openstack_version}")

    tags = {}
    for entry in sbom.get("images") or []:
        match = SBOM_IMAGE_RE.match(entry.get("image", ""))
        if not match:
            warn(f"unexpected image reference in SBOM: {entry.get('image')!r}")
            continue
        tags[match["name"]] = match["tag"]
    if not tags:
        raise Fatal(f"{image} lists no images")
    return tags


def resolve_manager(versions):
    def resolve(list_name, image):
        mapping = MANAGER_IMAGES.get(list_name)
        if mapping is None:
            return None, f"unknown list {list_name}"
        name, _, tag = image.rpartition(":")
        if not name:
            return None, "entry has no tag"
        key = mapping.get(name)
        if key is None:
            return None, "not pinned by the release"
        if key not in versions:
            return None, f"docker_images.{key} missing in the release"
        return f"{name}:{versions[key]}", None

    return resolve


def resolve_openstack(openstack_version, tags, sbom_image):
    def resolve(list_name, image):
        if list_name != "images_kolla":
            return None, f"unknown list {list_name}"
        match = KOLLA_ENTRY_RE.match(image)
        if not match:
            return None, "not a release/<version>/<name>:<tag> entry"
        tag = tags.get(match["name"])
        if tag is None:
            return None, f"not part of {sbom_image}"
        return f"release/{openstack_version}/{match['name']}:{tag}", None

    return resolve


def update_file(path, resolve, dry_run, verbose):
    """Rewrite the list entries of a vars file. Returns (changed, unresolved)."""
    lines = path.read_text().splitlines(keepends=True)
    entries = []  # (index, list name, image)
    current = None
    for index, line in enumerate(lines):
        match = LIST_RE.match(line)
        if match:
            current = match["name"]
            continue
        match = ITEM_RE.match(line)
        if match and current:
            entries.append((index, current, match["image"]))

    print(path.relative_to(REPO_ROOT))
    if not entries:
        warn(f"{path.name}: no list entries found")
        return False, 0

    width = max(len(image.rpartition(":")[0] or image) for _, _, image in entries)
    updated = unchanged = 0
    unresolved = []
    for index, list_name, image in entries:
        new_image, reason = resolve(list_name, image)
        name, _, old_tag = image.rpartition(":")
        if new_image is None:
            # Expected for images the release does not know about; anything
            # else means the mapping or the release is inconsistent.
            if reason == "not pinned by the release":
                print(f"  {name or image:<{width}}  {old_tag} (kept: {reason})")
            else:
                unresolved.append(f"{path.name}: {image}: {reason}")
                print(f"  {name or image:<{width}}  {old_tag} (kept: {reason})")
            continue
        if new_image == image:
            unchanged += 1
            if verbose:
                print(f"  {name:<{width}}  {old_tag}")
            continue
        updated += 1
        new_name, _, new_tag = new_image.rpartition(":")
        print(f"  {name:<{width}}  {old_tag} -> {new_tag if new_name == name else new_image}")
        prefix = ITEM_RE.match(lines[index])["prefix"]
        lines[index] = f"{prefix}{new_image}\n"

    print(f"  {updated} updated, {unchanged} unchanged, {len(entries) - updated - unchanged} kept")
    for message in unresolved:
        warn(message)

    if updated and not dry_run:
        path.write_text("".join(lines))
    return updated > 0, len(unresolved)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Update zuul/vars/container-images-*-stable.yml from an OSISM release.",
        epilog="Without RELEASE the newest X.Y.Z release of osism/release is used.",
    )
    parser.add_argument("release", nargs="?", metavar="RELEASE", help="OSISM release, e.g. 10.2.0")
    parser.add_argument(
        "-o",
        "--openstack-version",
        metavar="VERSION",
        help="OpenStack release of the SBOM image (default: latest/openstack.yml of osism/release)",
    )
    parser.add_argument("-n", "--dry-run", action="store_true", help="report the changes without writing the files")
    parser.add_argument("-v", "--verbose", action="store_true", help="also report unchanged entries")
    return parser.parse_args()


def main():
    args = parse_args()

    for path in (MANAGER_FILE, OPENSTACK_FILE):
        if not path.is_file():
            raise Fatal(f"{path} not found")

    release = args.release or latest_release()
    openstack_version = args.openstack_version or default_openstack_version()
    versions = release_versions(release, openstack_version)
    kolla_version = versions["kolla"]
    sbom_image = f"{REGISTRY}/kolla/release/{openstack_version}/sbom:{kolla_version}"

    print(f"OSISM release {release}: kolla {kolla_version}, OpenStack {openstack_version}")
    print(f"SBOM image: {sbom_image}")
    tags = sbom_tags(sbom_image, openstack_version)
    print()

    changed = False
    unresolved = 0
    for path, resolve in (
        (MANAGER_FILE, resolve_manager(versions)),
        (OPENSTACK_FILE, resolve_openstack(openstack_version, tags, sbom_image)),
    ):
        file_changed, file_unresolved = update_file(path, resolve, args.dry_run, args.verbose)
        changed = changed or file_changed
        unresolved += file_unresolved
        print()

    if args.dry_run:
        print("Dry run, nothing written.")
    elif changed:
        print("Files updated. Review the result with: git diff zuul/vars")
    else:
        print("Nothing to do, the files already match the release.")

    if unresolved:
        print(f"{unresolved} entries could not be resolved, see the warnings above.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fatal as e:
        sys.exit(f"ERROR: {e}")
    except KeyboardInterrupt:
        sys.exit(130)
