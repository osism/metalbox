#!/usr/bin/env python3
"""Check that every image a mirror job is about to copy exists at its source.

The mirror job runs this after its image lists are final and before the
first copy. It resolves each reference with `skopeo inspect --raw`, which
fetches the manifest only, so a bad tag fails the job within a minute and
every missing reference is listed at once -- a failing `skopeo copy` stops
at the first one, after moving gigabytes.

Usage:
    python3 zuul/check-container-image-tags.py --source-registry HOST \\
        [--jobs N] VARS_FILE...

VARS_FILE are the image-list vars files the job loaded. Exits 0 when every
reference resolves, 1 otherwise, 2 on a configuration problem (a missing
file, an unmapped list key -- see REGISTRY_PREFIX -- or no references).
"""

import argparse
import concurrent.futures
import pathlib
import subprocess
import sys

import yaml

# Mirrors the per-list registry prefixes in zuul/mirror-container-images.yml.
# A key that is not listed here is a hard error rather than a skip: a new list
# added to the playbook must be added here too, otherwise it would silently go
# unchecked -- which is the failure this script exists to prevent.
REGISTRY_PREFIX = {
    "images_manager_external": "dockerhub",
    "images_manager_stable_external": "dockerhub",
    "images_manager": "osism",
    "images_manager_stable": "osism",
    "images_osism": "osism",
    "images_kolla_metalbox": "kolla",
    "images_kolla": "kolla",
}


def collect(paths, source):
    """Return ({reference: [origins]}, [unmapped keys]) for the vars files."""
    refs = {}
    unmapped = []
    for path in map(pathlib.Path, paths):
        data = yaml.safe_load(path.read_text()) or {}
        for key, items in data.items():
            prefix = REGISTRY_PREFIX.get(key)
            if prefix is None:
                unmapped.append(f"{path.name}: {key}")
                continue
            for item in items or []:
                ref = f"{source}/{prefix}/{item}"
                refs.setdefault(ref, []).append(f"{path.name}:{key}")
    return refs, unmapped


def resolves(ref):
    """Return (ok, stderr): ok when the registry serves a manifest for ref,
    and skopeo's stderr, which names the failure when it does not."""
    result = subprocess.run(
        ["skopeo", "inspect", "--raw", f"docker://{ref}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.returncode == 0, result.stderr.decode(errors="replace").strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vars_files", nargs="+", metavar="VARS_FILE")
    parser.add_argument(
        "--source-registry",
        required=True,
        help="the registry the copy tasks read from (docker_registry)",
    )
    parser.add_argument("--jobs", type=int, default=12, help="parallel probes")
    args = parser.parse_args(argv)

    try:
        refs, unmapped = collect(args.vars_files, args.source_registry)
    except (OSError, yaml.YAMLError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if unmapped:
        print(
            "ERROR: image list keys with no registry prefix mapping:", file=sys.stderr
        )
        for entry in unmapped:
            print(f"  {entry}", file=sys.stderr)
        print(
            "Add them to REGISTRY_PREFIX to match zuul/mirror-container-images.yml.",
            file=sys.stderr,
        )
        return 2

    if not refs:
        print("ERROR: no image references found", file=sys.stderr)
        return 2

    print(f"Checking {len(refs)} unique references with {args.jobs} parallel probes...")
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for ref, (ok, err) in zip(refs, pool.map(resolves, refs)):
            if not ok:
                failures.append((ref, err))

    for ref, err in sorted(failures):
        print(f"\nUNRESOLVED {ref}")
        print(f"  referenced by: {', '.join(refs[ref])}")
        if err:
            print(f"  {err.splitlines()[-1]}")

    print(f"\n{len(refs) - len(failures)}/{len(refs)} references resolved.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
