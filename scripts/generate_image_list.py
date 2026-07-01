#!/usr/bin/env python3
"""Generate zuul/vars/container-images.yml from osism/release data."""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

import yaml

GITHUB_API_URL = "https://api.github.com/repos/osism/release/contents/"
GITHUB_RAW_URL = "https://raw.githubusercontent.com/osism/release/main/"

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_version(name):
    """Parse a version string like '9.3.1' into (major, minor, patch).
    Returns None for non-version strings and release candidates."""
    m = VERSION_RE.match(name)
    if m is None:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def discover_versions(release_repo, major=None):
    """Return list of version strings for non-RC releases.
    release_repo: local path (str/Path) or None for GitHub.
    major: if set, filter to this major version only."""
    if release_repo is not None:
        names = [p.name for p in Path(release_repo).iterdir() if p.is_dir()]
    else:
        names = _github_list_dirs()
    result = []
    for name in names:
        v = parse_version(name)
        if v is None:
            continue
        if major is not None and v[0] != major:
            continue
        result.append(name)
    return result


def _github_list_dirs():
    """List directory names from the release repo root via GitHub API."""
    req = urllib.request.Request(
        GITHUB_API_URL,
        headers={"Accept": "application/vnd.github.v3+json"},
    )
    with urllib.request.urlopen(req) as resp:
        entries = json.loads(resp.read())
    return [e["name"] for e in entries if e["type"] == "dir"]


def fetch_file(release_repo, path):
    """Fetch and YAML-parse a file from the release repo."""
    if release_repo is not None:
        file_path = Path(release_repo) / path
        with open(file_path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    else:
        url = GITHUB_RAW_URL + path
        with urllib.request.urlopen(url) as resp:
            return yaml.safe_load(resp.read())


def fetch_image_mapping(release_repo):
    """Fetch etc/images.yml: logical name -> image path."""
    return fetch_file(release_repo, "etc/images.yml")


def fetch_base_versions(release_repo, version):
    """Fetch <version>/base.yml and return docker_images dict."""
    data = fetch_file(release_repo, f"{version}/base.yml")
    return data.get("docker_images", {})


def collect_all_versions(release_repo, versions):
    """Collect the union of docker_images across multiple releases.
    Returns dict mapping logical name -> set of version tags."""
    all_versions = {}
    for version in versions:
        images = fetch_base_versions(release_repo, version)
        for name, tag in images.items():
            all_versions.setdefault(name, set()).add(str(tag))
    return all_versions


def load_filter_config(path):
    """Load the metalbox filter config."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {
        "images": data.get("images", []),
        "exclude": data.get("exclude", []),
        "unmanaged": data.get("unmanaged", []),
        "unmanaged_manager": data.get("unmanaged_manager", []),
    }


def validate_filter(filter_names, image_mapping, all_versions, exclude_names=None):
    """Validate filter against upstream data. Returns list of error messages.
    Errors:
    - Images in image_mapping with versions in all_versions but not in filter
      or exclude list.
    - Images in filter but not in image_mapping."""
    errors = []
    filter_set = set(filter_names)
    exclude_set = set(exclude_names or [])
    known = filter_set | exclude_set
    upstream_with_versions = set(image_mapping.keys()) & set(all_versions.keys())

    unknown = sorted(upstream_with_versions - known)
    for name in unknown:
        errors.append(
            f"Image '{name}' exists in release repo with versions "
            f"{sorted(all_versions[name])} but is not in the filter config. "
            f"Add it to scripts/metalbox-images.yml or confirm it's not needed."
        )

    stale = sorted(filter_set - set(image_mapping.keys()))
    for name in stale:
        errors.append(
            f"Image '{name}' is in the filter config but does not exist in "
            f"release/etc/images.yml. Remove it from scripts/metalbox-images.yml."
        )

    no_versions = sorted(filter_set & set(image_mapping.keys()) - set(all_versions.keys()))
    for name in no_versions:
        errors.append(
            f"Image '{name}' is in the filter config and in release/etc/images.yml "
            f"but has no versions in any target release. Move it to unmanaged or "
            f"exclude in scripts/metalbox-images.yml."
        )

    return errors


def _collect_latest_images(zuul_path):
    """Read the existing zuul file and return image names that use :latest."""
    with open(zuul_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    latest = set()
    for entry in data.get("images", []) + data.get("images_manager", []):
        if entry.endswith(":latest"):
            latest.add(entry.rsplit(":latest", 1)[0])
    return latest


def generate_image_entries(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    filter_names,
    image_mapping,
    all_versions,
    unmanaged,
    unmanaged_manager,
    keep_latest_for=None,
):
    """Generate sorted image:tag lists for the zuul file.
    Returns (images, images_manager) where:
    - images: entries with non-osism/ prefix (full path preserved)
    - images_manager: entries with osism/ prefix (prefix stripped)
    keep_latest_for: set of short image names (e.g. 'osism', 'ara-server')
    that should emit only ':latest' instead of expanded versions."""
    images = []
    images_manager = []
    keep = keep_latest_for or set()

    for name in filter_names:
        path = image_mapping[name]
        if path.startswith("osism/"):
            short = path[len("osism/") :]
        else:
            short = path
        if short in keep:
            tags = ["latest"]
        else:
            tags = sorted(all_versions.get(name, set()))
        if path.startswith("osism/"):
            for tag in tags:
                images_manager.append(f"{short}:{tag}")
        else:
            for tag in tags:
                images.append(f"{path}:{tag}")

    images.extend(unmanaged)
    images_manager.extend(unmanaged_manager)
    images.sort()
    images_manager.sort()
    return images, images_manager


def _write_yaml_list(f, key, items):
    """Write a YAML key with a list of items using 2-space indented dashes."""
    if not items:
        f.write(f"{key}: []\n")
        return
    f.write(f"{key}:\n")
    for item in items:
        f.write(f"  - {item}\n")


def update_zuul_file(path, images, images_manager):
    """Update zuul/vars/container-images.yml in place.
    Replaces images and images_manager, preserves all other keys."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    data["images"] = images
    data["images_manager"] = images_manager

    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n")
        for key, value in data.items():
            if isinstance(value, list):
                _write_yaml_list(f, key, value)
            else:
                yaml.dump({key: value}, f, default_flow_style=False)
            f.write("\n")


def detect_latest_major(versions):
    """Return the highest major version number from a list of version strings."""
    return max(parse_version(v)[0] for v in versions)


def run(release_repo, major, filter_path, zuul_path, keep_latest=False):
    """Core logic, callable from tests without argparse."""
    all_version_strings = discover_versions(release_repo)
    if not all_version_strings:
        print("ERROR: No release versions found.", file=sys.stderr)
        return 1

    if major is None:
        major = detect_latest_major(all_version_strings)
    print(f"Targeting major release series: {major}", file=sys.stderr)

    target_versions = discover_versions(release_repo, major=major)
    if not target_versions:
        print(f"ERROR: No releases found for major version {major}.", file=sys.stderr)
        return 1
    print(f"Found releases: {sorted(target_versions)}", file=sys.stderr)

    image_mapping = fetch_image_mapping(release_repo)
    all_versions = collect_all_versions(release_repo, target_versions)

    filter_config = load_filter_config(filter_path)
    errors = validate_filter(
        filter_config["images"],
        image_mapping,
        all_versions,
        exclude_names=filter_config["exclude"],
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    keep_latest_for = set()
    if keep_latest:
        keep_latest_for = _collect_latest_images(zuul_path)
        if keep_latest_for:
            print(f"Keeping :latest for: {sorted(keep_latest_for)}", file=sys.stderr)

    images, images_manager = generate_image_entries(
        filter_config["images"],
        image_mapping,
        all_versions,
        unmanaged=filter_config["unmanaged"],
        unmanaged_manager=filter_config["unmanaged_manager"],
        keep_latest_for=keep_latest_for,
    )

    update_zuul_file(zuul_path, images, images_manager)
    print(f"Updated {zuul_path}", file=sys.stderr)
    print(f"  images: {len(images)} entries", file=sys.stderr)
    print(f"  images_manager: {len(images_manager)} entries", file=sys.stderr)
    return 0


def main(argv=None):
    """CLI entry point: parse arguments and run."""
    parser = argparse.ArgumentParser(
        description="Generate images and images_manager in "
        "zuul/vars/container-images.yml from osism/release data."
    )
    parser.add_argument(
        "--major",
        type=int,
        default=None,
        help="Major release series to target (default: latest non-RC).",
    )
    parser.add_argument(
        "--release-repo",
        type=str,
        default=None,
        help="Local path to osism/release checkout " "(default: fetch from GitHub).",
    )
    parser.add_argument(
        "--keep-latest",
        action="store_true",
        help="Preserve existing :latest tags from the zuul file instead "
        "of expanding to all pinned versions from the release repo.",
    )
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent

    return run(
        release_repo=args.release_repo,
        major=args.major,
        keep_latest=args.keep_latest,
        filter_path=str(script_dir / "metalbox-images.yml"),
        zuul_path=str(repo_root / "zuul" / "vars" / "container-images.yml"),
    )


if __name__ == "__main__":
    sys.exit(main())
