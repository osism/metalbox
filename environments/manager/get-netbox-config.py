"""
Fetch device configuration from Netbox and write to Ansible group_vars.

This script queries a Netbox device by name and extracts specific configuration
values from its local_context_data, writing them to an Ansible group_vars YAML file.
"""

import os
import sys
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


def fetch_device_config(nb, device_name):
    """
    Fetch device configuration from Netbox.

    Args:
        nb: Netbox API client
        device_name: Name of the device to query

    Returns:
        dict: Device local_context_data containing configuration values
    """
    try:
        device = nb.dcim.devices.get(name=device_name)

        if not device:
            print(f"Error: Device '{device_name}' not found in Netbox", file=sys.stderr)
            sys.exit(1)

        if not hasattr(device, "local_context_data") or not device.local_context_data:
            print(
                f"Warning: Device '{device_name}' has no local_context_data",
                file=sys.stderr,
            )
            return {}

        return device.local_context_data

    except Exception as e:
        print(
            f"Error: Failed to fetch device configuration from Netbox", file=sys.stderr
        )
        print(f"Details: {e}", file=sys.stderr)
        sys.exit(1)


def extract_config_values(local_context_data):
    """
    Extract required configuration values from local_context_data.

    Args:
        local_context_data: Device's local_context_data dictionary

    Returns:
        dict: Extracted configuration values
    """
    config = {}

    # Extract netbox_secondaries if present
    if "netbox_secondaries" in local_context_data:
        config["netbox_secondaries"] = local_context_data["netbox_secondaries"]

    # Extract chrony_servers if present
    if "chrony_servers" in local_context_data:
        config["chrony_servers"] = local_context_data["chrony_servers"]

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

    # Fetch device configuration
    print(f"Fetching configuration for device '{device_name}'...")
    local_context_data = fetch_device_config(nb, device_name)

    # Extract required values
    config = extract_config_values(local_context_data)

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
