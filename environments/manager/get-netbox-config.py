"""
Fetch device configuration from Netbox and write to Ansible group_vars.

This script queries a Netbox device by name and extracts specific configuration
values from its local_context_data, writing them to an Ansible group_vars YAML file.
Additionally, it reads the device's site information and sets the managed Netbox site
by calling the netbox-site.sh script.
"""

import os
import sys
import subprocess
import yaml
from pathlib import Path
from pynetbox import api


def literal_str_representer(dumper, data):
    """
    Custom YAML representer that uses literal scalar style (|) for multiline strings.

    This preserves all content including Ansible Vault headers and formats the output
    with proper indentation for readability.

    Args:
        dumper: YAML dumper instance
        data: String data to represent

    Returns:
        YAML scalar node with appropriate style
    """
    if "\n" in data:
        # Use literal scalar style (|) for multiline strings
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    # Use default style for single-line strings
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


# Register the custom representer for all string types
yaml.add_representer(str, literal_str_representer)


class VaultString(str):
    """
    A string subclass to mark Ansible Vault encrypted values.
    This allows the YAML dumper to recognize and properly tag vault strings.
    """

    pass


def vault_representer(dumper, data):
    """
    Custom YAML representer for Ansible Vault encrypted strings.

    Outputs the vault string with the !vault tag and literal scalar style (|).

    Args:
        dumper: YAML dumper instance
        data: VaultString data to represent

    Returns:
        YAML scalar node with !vault tag
    """
    # Use literal scalar style (|) for vault strings
    return dumper.represent_scalar("!vault", data, style="|")


# Register the custom representers
yaml.add_representer(VaultString, vault_representer)


def get_netbox_client():
    """
    Create and return a Netbox API client.

    Returns:
        pynetbox.api: Configured Netbox API client
    """
    netbox_url = os.environ.get("NETBOX_API_URL", "http://192.168.42.10:8121")
    netbox_token = os.environ.get(
        "NETBOX_API_TOKEN", "0000000000000000000000000000000000000000"
    )

    try:
        nb = api(netbox_url, token=netbox_token)
        return nb
    except Exception as e:
        print(
            f"Error: Failed to connect to Netbox API at {netbox_url}", file=sys.stderr
        )
        print(f"Details: {e}", file=sys.stderr)
        sys.exit(1)


def set_netbox_site(site_slug):
    """
    Set the managed Netbox site by calling the netbox-site.sh script.

    Args:
        site_slug: The site slug to set as the managed site

    Raises:
        SystemExit: If the subprocess call fails
    """
    script_path = "/opt/configuration/scripts/netbox-site.sh"

    try:
        print(f"Setting managed Netbox site to '{site_slug}'...")
        result = subprocess.run(
            [script_path, site_slug], check=True, capture_output=True, text=True
        )

        # Log stdout if present
        if result.stdout:
            print(f"netbox-site.sh output: {result.stdout.strip()}")

        print(f"Successfully set managed site to '{site_slug}'")

    except FileNotFoundError:
        print(f"Error: Script not found at {script_path}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to set Netbox site '{site_slug}'", file=sys.stderr)
        print(f"Script exited with code {e.returncode}", file=sys.stderr)
        if e.stderr:
            print(f"Error output: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: Unexpected error calling netbox-site.sh", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        sys.exit(1)


def fetch_device_config(nb, device_name):
    """
    Fetch device configuration and site information from Netbox.

    Args:
        nb: Netbox API client
        device_name: Name of the device to query

    Returns:
        tuple: (local_context_data dict, site object or None, custom_fields dict)
    """
    try:
        device = nb.dcim.devices.get(name=device_name)

        if not device:
            print(f"Error: Device '{device_name}' not found in Netbox", file=sys.stderr)
            sys.exit(1)

        # Extract site information if available
        site = device.site if hasattr(device, "site") and device.site else None

        # Extract local context data
        local_context_data = {}
        if hasattr(device, "local_context_data") and device.local_context_data:
            local_context_data = device.local_context_data
        else:
            print(
                f"Warning: Device '{device_name}' has no local_context_data",
                file=sys.stderr,
            )

        # Extract custom fields
        custom_fields = {}
        if hasattr(device, "custom_fields") and device.custom_fields:
            # Convert custom_fields to dictionary if it's not already
            if isinstance(device.custom_fields, dict):
                custom_fields = device.custom_fields
            else:
                # Try to convert to dict
                custom_fields = dict(device.custom_fields)
        else:
            print(
                f"Warning: Device '{device_name}' has no custom_fields",
                file=sys.stderr,
            )

        return local_context_data, site, custom_fields

    except Exception as e:
        print(
            f"Error: Failed to fetch device configuration from Netbox", file=sys.stderr
        )
        print(f"Details: {e}", file=sys.stderr)
        sys.exit(1)


def extract_config_values(local_context_data, custom_fields):
    """
    Extract required configuration values from local_context_data and custom_fields.

    Behavior:
    - Copies selected values from local_context_data.
    - Copies ALL custom_fields except "secrets".
    - Expands the "secrets" custom field into individual variables.
    - Automatically tags Ansible Vault strings with !vault for proper YAML output.
    """

    # Final dictionary that will be written to group_vars
    config = {}

    # ---------------------------------------------------------
    # 1) Extract selected values from local_context_data
    # ---------------------------------------------------------
    # Only copy specific known keys. This prevents dumping
    # unrelated context values into group_vars unintentionally.
    for key in ("netbox_secondaries", "chrony_servers"):
        if key in local_context_data:
            config[key] = local_context_data[key]

    # ---------------------------------------------------------
    # 2) Copy ALL custom fields except "secrets"
    # ---------------------------------------------------------
    # This ensures we do not ignore other custom fields.
    # We skip "secrets" here because it is handled separately
    # with special logic below.
    if custom_fields:
        for key, value in custom_fields.items():
            # Skip secrets (handled later)
            if key == "secrets":
                continue

            # Only include fields that actually have a value
            if value is not None:
                config[key] = value

    # ---------------------------------------------------------
    # 3) Special handling for "secrets" custom field
    # ---------------------------------------------------------
    # The secrets field may contain:
    #   - A dictionary of multiple secrets
    #   - A single string value
    #   - An Ansible Vault encrypted value
    #
    # We expand secrets into top-level variables so Ansible
    # can use them directly.
    secrets = (custom_fields or {}).get("secrets")

    if secrets:

        # Case A: secrets is a dictionary
        if isinstance(secrets, dict):
            for secret_key, secret_value in secrets.items():

                # If the value looks like an Ansible Vault string,
                # wrap it in VaultString so the YAML dumper adds
                # the !vault tag and preserves literal formatting.
                if (
                    isinstance(secret_value, str)
                    and secret_value.strip().startswith("$ANSIBLE_VAULT")
                ):
                    config[secret_key] = VaultString(secret_value)
                else:
                    config[secret_key] = secret_value

        # Case B: secrets is a single value (not a dict)
        else:
            if (
                isinstance(secrets, str)
                and secrets.strip().startswith("$ANSIBLE_VAULT")
            ):
                config["netbox_secrets"] = VaultString(secrets)
            else:
                config["netbox_secrets"] = secrets

    return config


def write_group_vars(config):
    """
    Write configuration to Ansible group_vars YAML file.

    Args:
        config: Dictionary containing configuration values to write
    """
    output_dir = Path("group_vars/all")
    output_file = output_dir / "netbox.yml"

    try:
        # Create directory if it doesn't exist
        output_dir.mkdir(parents=True, exist_ok=True)

        # Write YAML file
        with open(output_file, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        print(f"Successfully wrote configuration to {output_file}")

    except Exception as e:
        print(f"Error: Failed to write configuration file", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """Main script execution."""
    # Check command-line arguments
    if len(sys.argv) < 2:
        print("Usage: fetch_netbox_config.py <device_name>", file=sys.stderr)
        print("", file=sys.stderr)
        print("Environment variables:", file=sys.stderr)
        print(
            "  NETBOX_API_URL   - Netbox API URL (default: http://192.168.42.10:8121)",
            file=sys.stderr,
        )
        print(
            "  NETBOX_API_TOKEN - Netbox API token (default: 0000000000000000000000000000000000000000)",
            file=sys.stderr,
        )
        sys.exit(1)

    device_name = sys.argv[1]

    # Connect to Netbox
    print(f"Connecting to Netbox...")
    nb = get_netbox_client()

    # Fetch device configuration and site information
    print(f"Fetching configuration for device '{device_name}'...")
    local_context_data, site, custom_fields = fetch_device_config(nb, device_name)

    # Set the managed Netbox site if available
    if site:
        # Extract site slug from the site object
        site_slug = site.slug if hasattr(site, "slug") else None

        if site_slug:
            set_netbox_site(site_slug)
        else:
            print(
                f"Warning: Device '{device_name}' has a site but no slug available",
                file=sys.stderr,
            )
    else:
        print(
            f"Warning: Device '{device_name}' has no site configured in Netbox",
            file=sys.stderr,
        )

    # Extract required values
    config = extract_config_values(local_context_data, custom_fields)

    # Add operator_ps1_custom with site slug if available
    if site and site_slug:
        config["operator_ps1_custom"] = f"[{site_slug}]"

    if not config:
        print(
            f"Warning: No configuration values (netbox_secondaries, chrony_servers) found in device's local_context_data",
            file=sys.stderr,
        )

    # Write to group_vars
    write_group_vars(config)

    print("Configuration fetch complete!")


if __name__ == "__main__":
    main()
