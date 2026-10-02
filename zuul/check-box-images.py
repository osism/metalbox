#!/usr/bin/env python3
"""Check that a mirrored registry holds every image the box's manager
configuration renders.

The mirror job runs this after its copies, against its own registry. It
renders every *_image key of the box's shipped manager configuration the way
the manager deploy sees it -- inventory group_vars/host_vars beneath the
run.sh -e files -- with the registry variables' real values. Kolla images and
images that only role defaults name are not covered.

Images in box-images-not-deployed.yml are dropped first, a row with
`unless: <flag>` only while that flag is false. Every remaining image must
come from the box registry (BOX_REGISTRY); a path a registry variable adds is
kept.

Usage:
    python3 zuul/check-box-images.py --registry localhost:5000 --configuration DIR

Exit status: 0 all present, 1 some missing, 2 the check could not be made.
"""

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

import image_refs as images

BOX_HOST = "metalbox"
BOX_REGISTRY = "localhost:5001"
NOT_DEPLOYED = Path(__file__).resolve().parent / "box-images-not-deployed.yml"
MANIFEST_TYPES = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


def load_not_deployed(path):
    """Return {key: {"reason": str, "unless": str|None}}; ValueError if malformed."""
    table = yaml.safe_load(Path(path).read_text()) or {}
    rows = {}
    for key, row in table.items():
        if not isinstance(row, dict) or not isinstance(row.get("reason"), str):
            raise ValueError(f"{path}: {key}: needs a reason")
        unless = row.get("unless")
        if unless is not None and not isinstance(unless, str):
            raise ValueError(f"{path}: {key}: unless must name a flag")
        rows[key] = {"reason": row["reason"], "unless": unless}
    return rows


TRUE = ("true", "yes", "on", "1")
FALSE = ("false", "no", "off", "0")


def is_true(flag, value):
    """The boolean value of an unless flag; ValueError unless it is literal.

    A templated or unrecognised value is an error, not false: false would
    silently drop the image from the check.
    """
    text = str(value).strip().lower()
    if text in TRUE:
        return True
    if text in FALSE:
        return False
    raise ValueError(f"unless flag {flag}: {value!r} is not a literal boolean")


def excluded(table, data):
    """The keys whose exclusion applies under this configuration."""
    keys = set()
    for key, row in table.items():
        flag = row["unless"]
        if flag is None:
            keys.add(key)
            continue
        if flag not in data:
            raise ValueError(f"{key}: unless flag {flag} is not configured")
        if not is_true(flag, data[flag]):
            keys.add(key)
    return keys


def box_refs(root, errors=None):
    """Return (merged configuration, {key: ImageRef}) for the box at root.

    errors is passed to image_refs: None raises RenderError for the first key
    that does not render through BOX_REGISTRY, a list collects them.
    """
    data = images.load_manager_configuration(root, BOX_HOST)
    return data, images.image_refs(data, data, errors, registry=BOX_REGISTRY)


def required_refs(root, table):
    """The ImageRefs the box needs; RenderError names the keys that fail.

    The not-deployed keys are dropped before the box registry is required of
    the rest, so an excluded key may render anywhere, or not at all.
    """
    errors = []
    data, refs = box_refs(root, errors)
    skip = excluded(table, data)
    failed = [message for key, message in errors if key not in skip]
    if failed:
        raise images.RenderError("; ".join(failed))
    return sorted({ref for key, ref in refs.items() if key not in skip}, key=str)


def manifest_exists(registry, ref, urlopen):
    request = urllib.request.Request(
        f"http://{registry}/v2/{ref.repository}/manifests/{ref.tag}",
        method="HEAD",
        headers={"Accept": MANIFEST_TYPES},
    )
    try:
        with urlopen(request, timeout=30):
            return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Check that a registry holds every image the box's manager"
            " configuration renders."
        )
    )
    parser.add_argument(
        "--registry", required=True, help="the registry to check, HOST:PORT"
    )
    parser.add_argument(
        "--configuration",
        type=Path,
        required=True,
        help="the metalbox repository root (holds environments/)",
    )
    return parser.parse_args(argv)


def main(argv=None, urlopen=urllib.request.urlopen, not_deployed=NOT_DEPLOYED):
    args = parse_args(argv)
    try:
        wanted = required_refs(args.configuration, load_not_deployed(not_deployed))
        if not wanted:
            raise ValueError("the box configuration renders no images to check")
        missing = [
            ref for ref in wanted if not manifest_exists(args.registry, ref, urlopen)
        ]
    except (
        OSError,
        ValueError,
        images.RenderError,
        urllib.error.URLError,
        yaml.YAMLError,
    ) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    for ref in missing:
        print(f"MISSING {ref}")
    print(
        f"{len(wanted) - len(missing)} of {len(wanted)} images present in {args.registry}"
    )
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
