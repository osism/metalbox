"""Render the image references of OSISM vars files.

Shared by the mirror's generator and its checks, so there is one answer to
"which image does this variable pull".

Two modes:

  placeholder (registry=None)  every registry variable (docker_registry,
      docker_registry_<service>, <service>_docker_registry) renders as one
      placeholder, and the reference is what follows it. For inputs with no
      site registry, such as a runner's role defaults.
  registry (registry="HOST:PORT")  registry variables render with their
      configured values, and every reference must start with HOST:PORT/. Only
      the host is stripped: a path a registry variable adds stays part of the
      repository. For a configuration whose registries are known, such as the
      MetalBox's own.
"""

from pathlib import Path
from typing import NamedTuple

import jinja2
import jinja2.meta
import yaml

PLACEHOLDER = "REGISTRY"
MAX_PASSES = 10

# The vars files the manager's run.sh passes with -e for the manager deploy,
# in its order, relative to environments/. Later files win. Secrets are left
# out: they are vaulted and carry no image references.
EXTRA_VARS = (
    "images.yml",
    "configuration.yml",
    "manager/images.yml",
    "manager/configuration.yml",
)

# The inventory groups whose group_vars the manager play sees, lowest
# precedence first: environments/manager/hosts puts the box's manager host in
# [manager], and group_vars/all applies beneath every other group.
MANAGER_GROUPS = ("all", "manager")
VARS_EXTENSIONS = (".yml", ".yaml")


class RenderError(Exception):
    pass


class ImageRef(NamedTuple):
    repository: str
    tag: str

    def __str__(self):
        return f"{self.repository}:{self.tag}"


def load_yaml(text):
    # BaseLoader keeps every scalar a string: 2025.1 and 3.0 are versions.
    return yaml.load(text, Loader=yaml.BaseLoader) or {}


def is_registry_variable(name):
    """docker_registry, docker_registry_<service> or <service>_docker_registry."""
    return (
        name == "docker_registry"
        or name.startswith("docker_registry_")
        or name.endswith("_docker_registry")
    )


def render_values(data, context, keys, registries=False):
    """Render the values of keys, resolving references to other keys of data.

    Unless registries is true, a registry variable (see is_registry_variable)
    renders as PLACEHOLDER, so a tag such as registry_tag is not mistaken for
    one. Other names come from data, then from context; anything else stays
    undefined, which only a default() filter survives.
    """
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    done = {}

    def resolve(key, stack):
        if key in done:
            return done[key]
        if key in stack:
            chain = " -> ".join(stack + (key,))
            raise RenderError(f"{key}: circular reference ({chain})")
        value = data[key]
        for _ in range(MAX_PASSES):
            if not isinstance(value, str) or "{{" not in value:
                break
            try:
                names = jinja2.meta.find_undeclared_variables(env.parse(value))
            except jinja2.TemplateSyntaxError as e:
                raise RenderError(f"{key}: {e.message}") from e
            scope = {}
            for name in names:
                if not registries and is_registry_variable(name):
                    scope[name] = PLACEHOLDER
                elif name in data:
                    scope[name] = resolve(name, stack + (key,))
                elif name in context:
                    scope[name] = context[name]
            try:
                value = env.from_string(value).render(scope)
            except jinja2.UndefinedError as e:
                raise RenderError(f"{key}: {e.message}") from e
        if isinstance(value, str) and "{{" in value:
            raise RenderError(f"{key}: still templated after {MAX_PASSES} passes")
        done[key] = value
        return value

    return {key: resolve(key, ()) for key in keys}


def parse_ref(key, rendered, registry=None):
    prefix = (registry or PLACEHOLDER) + "/"
    if not isinstance(rendered, str) or not rendered.startswith(prefix):
        source = registry or "a registry variable"
        raise RenderError(f"{key}: {rendered} is not pulled through {source}")
    name, sep, tag = rendered[len(prefix) :].rpartition(":")
    if not sep or not name or not tag or "/" in tag:
        raise RenderError(f"{key}: {rendered} has no tag")
    if registry is None and "/" not in name:
        name = "library/" + name  # a bare Docker Hub name
    return ImageRef(name, tag)


def image_refs(data, context, errors=None, registry=None):
    """Return {key: ImageRef} for every *_image key of data.

    With errors=None any key that does not render raises RenderError.
    Otherwise (key, message) is appended to errors and the key is skipped.
    registry selects the mode; see the module docstring.
    """
    refs = {}
    registries = registry is not None
    for key in sorted(k for k in data if k.endswith("_image")):
        try:
            rendered = render_values(data, context, [key], registries)[key]
            refs[key] = parse_ref(key, rendered, registry)
        except RenderError as e:
            if errors is None:
                raise
            errors.append((key, str(e)))
    return refs


def inventory_vars_files(base):
    """The files Ansible reads for one group_vars or host_vars entry.

    Like Ansible, the first of base/ (every *.yml and *.yaml beneath it,
    sorted, subdirectories in place), base.yml and base.yaml that exists is
    used, and only that one.
    """
    if base.is_dir():
        return directory_vars_files(base)
    for extension in VARS_EXTENSIONS:
        path = base.with_name(base.name + extension)
        if path.is_file():
            return [path]
    return []


def directory_vars_files(directory):
    found = []
    for path in sorted(directory.iterdir()):
        if path.name.startswith(".") or path.name.endswith("~"):
            continue
        if path.is_dir() and not path.suffix:
            found += directory_vars_files(path)
        elif path.is_file() and path.suffix in VARS_EXTENSIONS:
            found.append(path)
    return found


def load_manager_configuration(root, host):
    """Merge what the manager play on host sees, in Ansible's precedence order.

    run.sh runs it with -i hosts from environments/manager, so the inventory's
    group_vars of MANAGER_GROUPS and then host_vars/<host> apply, beneath the
    -e files of EXTRA_VARS. Overrides in environments/infrastructure/ reach
    only the k8s, netbox and traefik plays and are not read.
    """
    environments = Path(root) / "environments"
    manager = environments / "manager"
    if not (manager / "images.yml").exists():
        raise OSError(f"{manager / 'images.yml'}: not found")
    entries = [manager / "group_vars" / group for group in MANAGER_GROUPS]
    entries.append(manager / "host_vars" / host)
    merged = {}
    for entry in entries:
        for path in inventory_vars_files(entry):
            merged.update(load_yaml(path.read_text()))
    for name in EXTRA_VARS:
        path = environments / name
        if path.exists():
            merged.update(load_yaml(path.read_text()))
    return merged
