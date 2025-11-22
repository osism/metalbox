#!/usr/bin/env bash
#
# Switch Ironic from redfish mode to fake mode
#
# Usage:
#   ./scripts/toggle-ironic-mode.sh [fake|status]
#
# Commands:
#   fake     - Switch to fake mode (for testing without real hardware)
#   status   - Show current mode
#
# Note: This script only supports switching from redfish to fake mode.
#       Switching back to redfish is not supported.
#
# This script modifies:
#   - environments/kolla/files/overlays/ironic/ironic-conductor.conf
#   - environments/manager/files/conductor.yml
#

set -e

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IRONIC_CONDUCTOR_CONF="$PROJECT_ROOT/environments/kolla/files/overlays/ironic/ironic-conductor.conf"
CONDUCTOR_YML="$PROJECT_ROOT/environments/manager/files/conductor.yml"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored messages
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to show usage
usage() {
    cat << EOF
Usage: $(basename "$0") [fake|status]

Commands:
  fake     - Switch to fake mode (for testing without real hardware)
  status   - Show current mode

Note: This script only supports switching from redfish to fake mode.
      Switching back to redfish is not supported.

Examples:
  $(basename "$0") status           # Check current mode
  $(basename "$0") fake             # Switch from redfish to fake mode
EOF
    exit 1
}

# Function to check if we're in the correct directory
check_project_files() {
    if [[ ! -f "$IRONIC_CONDUCTOR_CONF" ]]; then
        print_error "Cannot find $IRONIC_CONDUCTOR_CONF"
        print_error "Project structure may be incorrect"
        exit 1
    fi

    if [[ ! -f "$CONDUCTOR_YML" ]]; then
        print_error "Cannot find $CONDUCTOR_YML"
        print_error "Project structure may be incorrect"
        exit 1
    fi
}

# Function to detect current mode
detect_current_mode() {
    local conductor_conf_mode=""
    local conductor_yml_mode=""

    # Check ironic-conductor.conf
    if grep -q "enabled_hardware_types = redfish" "$IRONIC_CONDUCTOR_CONF" 2>/dev/null; then
        conductor_conf_mode="redfish"
    elif grep -q "enabled_hardware_types = fake-hardware" "$IRONIC_CONDUCTOR_CONF" 2>/dev/null; then
        conductor_conf_mode="fake"
    else
        conductor_conf_mode="unknown"
    fi

    # Check conductor.yml
    if grep -q "driver: redfish" "$CONDUCTOR_YML" 2>/dev/null; then
        conductor_yml_mode="redfish"
    elif grep -q "driver: fake-hardware" "$CONDUCTOR_YML" 2>/dev/null; then
        conductor_yml_mode="fake"
    else
        conductor_yml_mode="unknown"
    fi

    # Check if modes match
    if [[ "$conductor_conf_mode" == "$conductor_yml_mode" ]]; then
        echo "$conductor_conf_mode"
    else
        print_warning "Mode mismatch detected!"
        print_warning "  ironic-conductor.conf: $conductor_conf_mode"
        print_warning "  conductor.yml: $conductor_yml_mode"
        echo "inconsistent"
    fi
}

# Function to switch to fake mode
switch_to_fake() {
    print_info "Switching to FAKE mode..."

    # Modify ironic-conductor.conf
    print_info "Updating $(basename "$IRONIC_CONDUCTOR_CONF")..."

    # Create new fake mode configuration
    cat > "$IRONIC_CONDUCTOR_CONF.new" << 'EOF'
[DEFAULT]
enabled_network_interfaces = noop
default_network_interface = noop
grub_config_path = EFI/ubuntu/grub.cfg

enabled_hardware_types = fake-hardware
enabled_boot_interfaces = fake
enabled_deploy_interfaces = fake,direct
enabled_raid_interfaces = fake,agent
enabled_inspect_interfaces = fake,no-inspect
enabled_console_interfaces = fake,no-console
enabled_bios_interfaces = fake,no-bios
enabled_storage_interfaces = fake,noop
enabled_vendor_interfaces = fake,no-vendor

[deploy]
external_callback_url = http://metalbox:{{ ironic_api_port }}
external_http_url = http://metalbox.osism.xyz/ironic

[conductor]
bootloader = http://metalbox/osism-esp.raw

[fake]
power_delay = 0
boot_delay = 0
deploy_delay = 0
vendor_delay = 0
management_delay = 0
inspect_delay = 0
raid_delay = 0
bios_delay = 0
storage_delay = 0
rescue_delay = 0
EOF

    mv "$IRONIC_CONDUCTOR_CONF.new" "$IRONIC_CONDUCTOR_CONF"

    # Modify conductor.yml
    print_info "Updating $(basename "$CONDUCTOR_YML")..."

    # Create a temporary file with the fake mode configuration
    cat > "$CONDUCTOR_YML.new" << 'EOF'
---
ironic_parameters:
  driver: fake-hardware
  driver_info:
    deploy_kernel: http://metalbox/osism-ipa.kernel
    deploy_ramdisk: http://metalbox/osism-ipa.initramfs
  boot_interface: fake
  properties:
    capabilities: 'boot_mode:uefi'
  instance_info:
    image_source: http://metalbox/osism-node.qcow2
    image_checksum: http://metalbox/osism-node.qcow2.CHECKSUM
EOF

    # Replace the file
    mv "$CONDUCTOR_YML.new" "$CONDUCTOR_YML"

    print_success "Successfully switched to FAKE mode"
    print_info ""
    print_info "Configuration changes:"
    print_info "  - Hardware type: fake-hardware"
    print_info "  - Boot interface: fake"
    print_info "  - Driver: fake-hardware"
}


# Function to show current status
show_status() {
    print_info "Checking current Ironic mode..."
    echo ""

    local current_mode
    current_mode=$(detect_current_mode)

    case "$current_mode" in
        "fake")
            print_success "Current mode: FAKE"
            print_info "Ironic is configured for testing without real hardware"
            ;;
        "redfish")
            print_success "Current mode: REDFISH"
            print_info "Ironic is configured for production with real hardware"
            ;;
        "inconsistent")
            print_error "Configuration files have inconsistent modes!"
            print_info "Please run: $(basename "$0") [fake|redfish] to fix"
            return 1
            ;;
        "unknown")
            print_error "Unable to determine current mode"
            print_info "Configuration may be corrupted or modified manually"
            return 1
            ;;
    esac

    echo ""
    print_info "Configuration files:"
    print_info "  - $IRONIC_CONDUCTOR_CONF"
    print_info "  - $CONDUCTOR_YML"
}

# Main script logic
main() {
    # Check if command provided
    if [[ $# -eq 0 ]]; then
        usage
    fi

    local command="$1"

    # Check project files
    check_project_files

    case "$command" in
        "status")
            show_status
            ;;
        "fake")
            # Check current mode
            local current_mode
            current_mode=$(detect_current_mode)

            if [[ "$current_mode" == "fake" ]]; then
                print_info "Already in FAKE mode. Nothing to do."
                exit 0
            fi

            if [[ "$current_mode" != "redfish" ]]; then
                print_error "Can only switch from REDFISH to FAKE mode"
                print_error "Current mode: $current_mode"
                exit 1
            fi

            # Show confirmation
            echo ""
            print_warning "This will switch Ironic from REDFISH to FAKE mode"
            print_info "Current mode: $current_mode"
            print_info "Target mode: fake"
            echo ""
            print_warning "NOTE: Switching back to redfish mode is not supported by this script!"
            echo ""
            read -p "Continue? (yes/no): " -r
            echo ""

            if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
                print_info "Cancelled by user"
                exit 0
            fi

            # Switch mode
            if switch_to_fake; then
                echo ""
                print_success "Mode switch completed successfully!"
                print_info ""
                print_warning "Next steps:"
                print_info "  1. Restart Ironic services: osism apply ironic"
                print_info "  2. Verify the configuration"
                print_info ""
                print_warning "IMPORTANT: Switching back to redfish mode is not supported."
                print_info "You will need to manually restore the configuration files."

                # Show new status
                echo ""
                show_status
            else
                print_error "Failed to switch mode"
                exit 1
            fi
            ;;
        "redfish")
            print_error "Switching from fake to redfish mode is not supported"
            print_info "This script only supports one-way switching: redfish -> fake"
            print_info ""
            print_info "To restore redfish mode, you need to manually restore the configuration files."
            exit 1
            ;;
        *)
            print_error "Unknown command: $command"
            echo ""
            usage
            ;;
    esac
}

# Run main function
main "$@"
