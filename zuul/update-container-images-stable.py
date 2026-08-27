#!/usr/bin/env python3
"""
Update zuul/vars/container-images-*-stable.yml from an OSISM release.

The two stable image lists pin every image of the stable registry tarball
(registry-stable-full.tar.bz2) to the versions of one OSISM release:

  container-images-manager-stable.yml
      Tags come from the docker_images section of <release>/base.yml in
      https://github.com/osism/release. base.yml does not pin
      openstackclient; when the key is missing there, the tag is taken from
      latest/openstack-<version>.yml, the way osism-ansible resolves it.

  container-images-openstack-stable.yml
      The kolla version in base.yml names the SBOM image
      registry.osism.tech/kolla/release/<openstack version>/sbom:<kolla>.
      Its /images.yml lists every Kolla image of that build; the tags in
      the file are replaced with the ones listed there.

Only the tags of the images already listed are updated; images are never
added or removed. The OpenStack release in the kolla entries
(release/<version>/...) is read from the file and only changed when -o asks
for another one. Entries without a counterpart in the release (for example
library/httpd or rsync:latest) are kept unchanged and reported, and so is
the number of images the release provides that the files do not list.

Usage: update-container-images-stable.py [-n] [-v] [-o VERSION] [RELEASE]

  RELEASE                  OSISM release, e.g. 10.2.0. Default: the highest
                           numbered X.Y.Z release directory in osism/release.
  -o, --openstack-version  Move the kolla entries to this OpenStack release.
                           Default: the release the entries currently use.
  -n, --dry-run            Report the changes without writing the files.
  -v, --verbose            Also report unchanged entries and name the images
                           of the release that are not listed.

Requirements: python3 with PyYAML, docker (or crane) to read the SBOM image,
network access to github.com and registry.osism.tech. GITHUB_TOKEN is sent
to the GitHub API when set (only needed to avoid the anonymous rate limit).

Exit status: 0 on success, 1 on a fatal error, 2 when some entries could not
be resolved (the other entries are still updated unless -n is given).

Both files are read, checked and resolved before either is written, so a
fatal error in that stage leaves them as they were. Each file is then
replaced atomically: the new content is staged next to it and renamed into
place, so a failed write leaves that file untouched. The two files are
written one after the other, not as one transaction; if the second write
fails, git diff zuul/vars shows what the first one changed.
"""

import argparse
import contextlib
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
from pathlib import Path, PurePosixPath
from typing import NamedTuple

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
# section of the release. Images not listed here have no counterpart in the
# release and are left untouched.
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
        # openstackclient is taken from latest/openstack-<version>.yml unless
        # base.yml pins it
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
# The vars files are rewritten line by line to keep comments and blank lines,
# so their entries are located with these two expressions. They only know
# plain "  - image:tag" items; scan_file() compares what they find with what
# the YAML parser sees, so anything else fails loudly instead of being skipped.
LIST_RE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*):\s*$")
ITEM_RE = re.compile(r"^(?P<prefix>\s*-\s+)(?P<image>\S+)\s*$")
KOLLA_ENTRY_RE = re.compile(
    r"^release/(?P<version>[^/]+)/(?P<name>[^/:]+):(?P<tag>[^/:]+)$"
)
SBOM_IMAGE_RE = re.compile(
    r"^(?:.*/)?kolla/release/(?P<version>[^/]+)/(?P<name>[^/:]+):(?P<tag>[^/:]+)$"
)


class Fatal(Exception):
    pass


class Entry(NamedTuple):
    """One list item of a vars file."""

    index: int  # line index in the file
    list_name: str
    image: str


class Resolution(NamedTuple):
    """What the release says about one list entry."""

    image: str | None = None  # the entry as pinned by the release
    reason: str | None = None  # why the entry is kept when image is None
    expected: bool = True  # False: the mapping or the release is inconsistent


def resolved(image):
    return Resolution(image=image)


def unmapped(reason):
    """The entry has no counterpart in the release; keeping it is normal."""
    return Resolution(reason=reason)


def unresolved(reason):
    """The entry should have a counterpart, but it could not be found."""
    return Resolution(reason=reason, expected=False)


class Update(NamedTuple):
    """The rewritten content of a vars file and the tally of its entries."""

    path: Path
    text: str
    updated: int
    unresolved: int


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


def release_versions(release, openstack_version):
    """Return the docker_images of the release plus openstackclient."""
    base = load_yaml(
        fetch(
            f"{RELEASE_RAW}/{release}/base.yml",
            not_found=f"release {release} not found in osism/release",
        )
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
    # A pin in base.yml is release-scoped and wins; latest/ only fills the gap.
    openstackclient = (openstack.get("docker_images") or {}).get("openstackclient")
    if openstackclient:
        versions.setdefault("openstackclient", openstackclient)
    elif "openstackclient" not in versions:
        warn(
            f"neither {release}/base.yml nor latest/openstack-{openstack_version}.yml "
            "pins an openstackclient tag"
        )
    return versions


def sbom_via_docker(image):
    run(["docker", "pull", "--quiet", "--platform", "linux/amd64", image])
    # The SBOM image is built from scratch and has no command. docker create
    # insists on one; the container is never started, so any string will do.
    result = run(
        ["docker", "create", "--platform", "linux/amd64", image, "/images.yml"]
    )
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
        # The member may be stored as images.yml, ./images.yml or /images.yml.
        for member in tar:
            if member.isfile() and PurePosixPath("/", member.name) == PurePosixPath(
                "/images.yml"
            ):
                return tar.extractfile(member).read().decode()
    raise Fatal(f"{image} contains no images.yml")


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
            return unresolved(f"unknown list {list_name}")
        name, _, _ = image.rpartition(":")
        if not name:
            return unresolved("entry has no tag")
        key = mapping.get(name)
        if key is None:
            return unmapped("no mapping in MANAGER_IMAGES")
        if key not in versions:
            return unresolved(f"docker_images.{key} missing in the release")
        return resolved(f"{name}:{versions[key]}")

    return resolve


def resolve_openstack(openstack_version, tags, sbom_image):
    def resolve(list_name, image):
        if list_name != "images_kolla":
            return unresolved(f"unknown list {list_name}")
        match = KOLLA_ENTRY_RE.match(image)
        if not match:
            return unresolved("not a release/<version>/<name>:<tag> entry")
        tag = tags.get(match["name"])
        if tag is None:
            return unresolved(f"not part of {sbom_image}")
        return resolved(f"release/{openstack_version}/{match['name']}:{tag}")

    return resolve


def scan_file(path):
    """Return (lines, entries) of a vars file.

    Every entry the YAML parser sees must be found by the line scanner as
    well; an entry written any other way (quoted, followed by a comment, in
    flow style) would otherwise be invisible to the update.
    """
    try:
        text = path.read_text()
    except OSError as e:
        raise Fatal(f"{path}: {e}") from e
    lines = text.splitlines(keepends=True)

    entries = []
    scanned = {}
    current = None
    for index, line in enumerate(lines):
        match = LIST_RE.match(line)
        if match:
            current = match["name"]
            scanned.setdefault(current, [])
            continue
        match = ITEM_RE.match(line)
        if match and current is not None:
            entries.append(Entry(index, current, match["image"]))
            scanned[current].append(match["image"])

    try:
        parsed = load_yaml(text)
    except yaml.YAMLError as e:
        raise Fatal(f"{path.name}: {e}") from e
    if not isinstance(parsed, dict):
        raise Fatal(f"{path.name}: expected a mapping of lists")
    lists = {name: value for name, value in parsed.items() if isinstance(value, list)}
    for name in sorted(set(scanned) | set(lists)):
        found, expected = scanned.get(name, []), lists.get(name, [])
        if found == expected:
            continue
        if len(found) != len(expected):
            detail = (
                f"the YAML parser sees {len(expected)} entries, "
                f"the line scanner {len(found)}"
            )
        else:
            item, value = next((f, e) for f, e in zip(found, expected) if f != e)
            detail = (
                f"the line scanner reads {item!r} where the YAML parser reads {value!r}"
            )
        raise Fatal(
            f"{path.name}: {name}: {detail}; every entry must be a plain "
            "'  - image:tag' line without quotes or a trailing comment"
        )
    return lines, entries


def kolla_versions(entries):
    """Return the OpenStack releases the release/<version>/ entries point to."""
    versions = set()
    for entry in entries:
        if entry.list_name == "images_kolla":
            match = KOLLA_ENTRY_RE.match(entry.image)
            if match:
                versions.add(match["version"])
    return versions


def update_entries(path, lines, entries, resolve, verbose):
    """Resolve every entry of a vars file; returns the new text and tally."""
    print(path.relative_to(REPO_ROOT))
    if not entries:
        warn(f"{path.name}: no list entries found")
        return Update(path, "".join(lines), 0, 0)

    lines = list(lines)
    width = max(len(entry.image.rpartition(":")[0] or entry.image) for entry in entries)
    updated = unchanged = 0
    unresolved = []
    for entry in entries:
        result = resolve(entry.list_name, entry.image)
        name, _, old_tag = entry.image.rpartition(":")
        if result.image is None:
            print(
                f"  {name or entry.image:<{width}}  {old_tag} (kept: {result.reason})"
            )
            if not result.expected:
                unresolved.append(f"{path.name}: {entry.image}: {result.reason}")
            continue
        if result.image == entry.image:
            unchanged += 1
            if verbose:
                print(f"  {name:<{width}}  {old_tag}")
            continue
        updated += 1
        new_name, _, new_tag = result.image.rpartition(":")
        print(
            f"  {name:<{width}}  {old_tag} -> "
            f"{new_tag if new_name == name else result.image}"
        )
        prefix = ITEM_RE.match(lines[entry.index])["prefix"]
        lines[entry.index] = f"{prefix}{result.image}\n"

    kept = len(entries) - updated - unchanged
    print(f"  {updated} updated, {unchanged} unchanged, {kept} kept")
    for message in unresolved:
        warn(message)
    return Update(path, "".join(lines), updated, len(unresolved))


def report_unlisted(versions, tags, manager_entries, openstack_entries, verbose):
    """Report the images of the release that the files do not list.

    The files decide what the stable tarball contains, and that choice was
    made by hand once. This is the reminder to look at it again when a
    release adds images; the script itself never adds entries.
    """
    listed = set()
    for entry in manager_entries:
        mapping = MANAGER_IMAGES.get(entry.list_name, {})
        listed.add(mapping.get(entry.image.rpartition(":")[0]))
    # kolla names the SBOM image itself, not an image of the tarball
    manager_unlisted = sorted(set(versions) - listed - {"kolla"})

    listed = set()
    for entry in openstack_entries:
        match = KOLLA_ENTRY_RE.match(entry.image)
        if entry.list_name == "images_kolla" and match:
            listed.add(match["name"])
    kolla_unlisted = sorted(set(tags) - listed)

    for names, what, path in (
        (manager_unlisted, "docker_images of the release", MANAGER_FILE),
        (kolla_unlisted, "images of the SBOM", OPENSTACK_FILE),
    ):
        print(f"{len(names)} {what} are not listed in {path.name}")
        if verbose:
            for name in names:
                print(f"  {name}")


def write_file(path, text):
    """Replace path atomically: stage the content next to it, then rename."""
    try:
        fd, staged = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
    except OSError as e:
        raise Fatal(f"{path}: {e}") from e
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
        shutil.copymode(path, staged)
        os.replace(staged, path)
    except OSError as e:
        with contextlib.suppress(OSError):
            os.unlink(staged)
        raise Fatal(f"{path}: {e}") from e


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Update zuul/vars/container-images-*-stable.yml from an OSISM release.",
        epilog="Without RELEASE the highest numbered X.Y.Z release of osism/release is used.",
    )
    parser.add_argument(
        "release", nargs="?", metavar="RELEASE", help="OSISM release, e.g. 10.2.0"
    )
    parser.add_argument(
        "-o",
        "--openstack-version",
        metavar="VERSION",
        help=(
            "move the kolla entries to this OpenStack release "
            "(default: keep the release they currently use)"
        ),
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="report the changes without writing the files",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="also report unchanged entries and name the unlisted images of the release",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    manager_lines, manager_entries = scan_file(MANAGER_FILE)
    openstack_lines, openstack_entries = scan_file(OPENSTACK_FILE)

    # The OpenStack release of the kolla entries is a property of the file;
    # moving the entries to another release needs an explicit -o.
    file_versions = kolla_versions(openstack_entries)
    if args.openstack_version:
        openstack_version = args.openstack_version
    elif len(file_versions) == 1:
        (openstack_version,) = file_versions
    elif file_versions:
        raise Fatal(
            f"{OPENSTACK_FILE.name}: the entries belong to different OpenStack "
            f"releases ({', '.join(sorted(file_versions))}); pass -o to move "
            "them all to one release"
        )
    else:
        raise Fatal(
            f"{OPENSTACK_FILE.name}: no release/<version>/<name>:<tag> entries "
            "found; pass -o to select the OpenStack release"
        )

    release = args.release or latest_release()
    versions = release_versions(release, openstack_version)
    kolla_version = versions["kolla"]
    sbom_image = f"{REGISTRY}/kolla/release/{openstack_version}/sbom:{kolla_version}"

    print(
        f"OSISM release {release}: kolla {kolla_version}, OpenStack {openstack_version}"
    )
    if file_versions - {openstack_version}:
        print(
            f"Moving the kolla entries from release/{'|'.join(sorted(file_versions))}/ "
            f"to release/{openstack_version}/"
        )
    print(f"SBOM image: {sbom_image}")
    tags = sbom_tags(sbom_image, openstack_version)
    print()

    updates = []
    for path, lines, entries, resolve in (
        (MANAGER_FILE, manager_lines, manager_entries, resolve_manager(versions)),
        (
            OPENSTACK_FILE,
            openstack_lines,
            openstack_entries,
            resolve_openstack(openstack_version, tags, sbom_image),
        ),
    ):
        updates.append(update_entries(path, lines, entries, resolve, args.verbose))
        print()
    report_unlisted(versions, tags, manager_entries, openstack_entries, args.verbose)
    print()

    updated = sum(update.updated for update in updates)
    unresolved = sum(update.unresolved for update in updates)
    if args.dry_run:
        if updated:
            print(f"Dry run: {updated} changes pending, nothing written.")
        else:
            print("Dry run: the files already match the release, nothing to write.")
    elif updated:
        for update in updates:
            if update.updated:
                write_file(update.path, update.text)
        print("Files updated. Review the result with: git diff zuul/vars")
    else:
        print("Nothing to do, the files already match the release.")

    if unresolved:
        print(
            f"{unresolved} entries could not be resolved, see the warnings above.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fatal as e:
        sys.exit(f"ERROR: {e}")
    except KeyboardInterrupt:
        sys.exit(130)
