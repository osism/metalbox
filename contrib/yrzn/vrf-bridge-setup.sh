#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# VRF Bridge Setup: Default VRF <-> VRF
# =============================================================================
#
# Problem:
#   - Ironic runs in the default VRF (on metalbox device)
#   - IPA agents run on bare-metal nodes in a separate VRF
#   - Ironic needs outbound access to IPA on port 9999 (deploy steps)
#   - IPA needs inbound access to httpd on ports 80/443 and Ironic API on port 6385
#     (configurable via DNAT_PORTS)
#
# Solution:
#   A veth pair connects both VRFs at L3. SNAT/DNAT ensures source IPs are
#   known in the fabric and inbound traffic is forwarded correctly.
#
# Outbound packet flow (Ironic -> IPA):
#   Ironic (default VRF) -> 198.51.100.x:9999
#     -> route via vrf-bridge0 -> vrf-bridge1 (VRF)
#     -> SNAT rewrites src to LOOPBACK1_IP (announced via BGP in the fabric)
#     -> fabric -> node
#     -> reply comes back to dst=LOOPBACK1_IP
#     -> ip rule steers reply back through veth into default VRF
#     -> conntrack performs reverse SNAT
#     -> Ironic receives reply
#
# Inbound packet flow (IPA -> httpd):
#   IPA (VRF) -> LOOPBACK1_IP:80/443/6385
#     -> DNAT rewrites dst to METALBOX_IP (metalbox in default VRF)
#     -> crosses veth into default VRF
#     -> httpd responds
#     -> route via veth sends reply back into VRF
#     -> conntrack performs reverse DNAT (src becomes LOOPBACK1_IP again)
#     -> fabric -> node
#
# =============================================================================

# =============================================================================
# Configuration
# =============================================================================

# VRF name and routing table ID
VRF_NAME="vrf-os001"
VRF_TABLE="100"

# Interface names used to auto-detect IPs
LOOPBACK1_DEV="loopback1"
METALBOX_DEV="metalbox"

# Bare-metal networks (where IPA agents live, in VRF)
# Cannot be derived from loopback1 (which is a /32), must be set explicitly.
# Space-separated list of CIDRs, e.g. "198.51.100.0/21 203.0.113.0/21"
BM_NETWORKS="198.51.100.0/24"

# Transit network between the veth pair (link-local, arbitrary)
TRANSIT_IP_DEFAULT="169.254.100.1"
TRANSIT_IP_VRF="169.254.100.2"
TRANSIT_CIDR="30"

# Fabric-facing interfaces (for ip rule to steer SNAT replies back)
FABRIC_INTERFACES="data1 data2"

# Ports to DNAT from LOOPBACK1_IP to METALBOX_IP (comma-separated)
DNAT_PORTS="80,443,6385"

# MTU for the veth pair (should match the fabric MTU)
VETH_MTU="1500"

# Set to true to enable IP forwarding via sysctl.
# Set to false if forwarding is already enabled elsewhere.
ENABLE_SYSCTL="false"

# Load configuration from file if provided via VRF_BRIDGE_CONFIG or as first argument.
# Sourced AFTER defaults so that user values override them.
CONFIG_FILE="${VRF_BRIDGE_CONFIG:-${1:-}}"
if [[ -n "${CONFIG_FILE}" ]]; then
  if [[ ! -f "${CONFIG_FILE}" ]]; then
    echo "ERROR: Configuration file not found: ${CONFIG_FILE}" >&2
    exit 1
  fi
  echo "INFO: Loading configuration from ${CONFIG_FILE}"
  # shellcheck source=/dev/null
  source "${CONFIG_FILE}"
fi

# =============================================================================
# Auto-detect IPs from interfaces
# =============================================================================

# Read first IPv4 address from loopback1 (e.g. 198.51.100.1/32 -> 198.51.100.1)
LOOPBACK1_IP=$(ip -4 -o addr show dev "${LOOPBACK1_DEV}" \
  | awk '{print $4}' | cut -d/ -f1 | head -1)

if [[ -z "${LOOPBACK1_IP}" ]]; then
  echo "ERROR: Could not detect IPv4 address on ${LOOPBACK1_DEV}" >&2
  exit 1
fi

# Read first IPv4 address and CIDR from metalbox (e.g. 192.168.42.10/24)
METALBOX_ADDR=$(ip -4 -o addr show dev "${METALBOX_DEV}" \
  | awk '{print $4}' | head -1)

if [[ -z "${METALBOX_ADDR}" ]]; then
  echo "ERROR: Could not detect IPv4 address on ${METALBOX_DEV}" >&2
  exit 1
fi

METALBOX_IP=$(echo "${METALBOX_ADDR}" | cut -d/ -f1)
METALBOX_CIDR=$(echo "${METALBOX_ADDR}" | cut -d/ -f2)

# Derive metalbox network from IP and CIDR (e.g. 192.168.42.0/24)
MB_NETWORK=$(python3 -c "
import ipaddress
n = ipaddress.ip_network('${METALBOX_ADDR}', strict=False)
print(n)
")

echo "INFO: Detected LOOPBACK1_IP=${LOOPBACK1_IP} (from ${LOOPBACK1_DEV})"
echo "INFO: Detected METALBOX_IP=${METALBOX_IP}/${METALBOX_CIDR} (from ${METALBOX_DEV})"
echo "INFO: Derived MB_NETWORK=${MB_NETWORK}"
echo "INFO: BM_NETWORKS=${BM_NETWORKS}, VRF=${VRF_NAME} (table ${VRF_TABLE})"

# =============================================================================
# Setup
# =============================================================================

# -----------------------------------------------------------------------------
# 1. Create veth pair
#    - vrf-bridge0 stays in the default VRF
#    - vrf-bridge1 is placed into the VRF
#    - Transit addresses serve as next-hops for cross-VRF routing
# -----------------------------------------------------------------------------
echo "INFO: [1/7] Creating veth pair (vrf-bridge0 <-> vrf-bridge1, MTU ${VETH_MTU})..."
ip link add vrf-bridge0 type veth peer name vrf-bridge1
ip link set vrf-bridge1 master "${VRF_NAME}"
ip link set vrf-bridge0 mtu "${VETH_MTU}"
ip link set vrf-bridge1 mtu "${VETH_MTU}"
ip addr add "${TRANSIT_IP_DEFAULT}/${TRANSIT_CIDR}" dev vrf-bridge0
ip addr add "${TRANSIT_IP_VRF}/${TRANSIT_CIDR}" dev vrf-bridge1
ip link set vrf-bridge0 up
ip link set vrf-bridge1 up

# -----------------------------------------------------------------------------
# 2. Static ARP entries
#    The kernel does not reliably answer ARP across veth+VRF boundaries.
#    Static neighbors with the actual MAC addresses of each veth end are
#    required. MACs are read dynamically (they differ per box).
# -----------------------------------------------------------------------------
echo "INFO: [2/7] Adding static ARP entries for veth pair..."
MAC0=$(cat /sys/class/net/vrf-bridge0/address)
MAC1=$(cat /sys/class/net/vrf-bridge1/address)
echo "INFO:   vrf-bridge0 MAC=${MAC0}, vrf-bridge1 MAC=${MAC1}"
ip neigh replace "${TRANSIT_IP_VRF}" lladdr "${MAC1}" dev vrf-bridge0 nud permanent
ip neigh replace "${TRANSIT_IP_DEFAULT}" lladdr "${MAC0}" dev vrf-bridge1 nud permanent

# -----------------------------------------------------------------------------
# 3. Enable IP forwarding (optional)
#    Required so the kernel forwards packets between VRFs.
#    Skipped if ENABLE_SYSCTL=false (e.g. when already enabled system-wide).
# -----------------------------------------------------------------------------
echo "INFO: [3/7] IP forwarding (ENABLE_SYSCTL=${ENABLE_SYSCTL})..."
if [[ "${ENABLE_SYSCTL}" == "true" ]]; then
  echo "INFO:   Enabling ip_forward and per-interface forwarding"
  sysctl -w net.ipv4.ip_forward=1
  sysctl -w net.ipv4.conf.vrf-bridge0.forwarding=1
  sysctl -w net.ipv4.conf.vrf-bridge1.forwarding=1
fi

# -----------------------------------------------------------------------------
# 4. Routes
#    - Default VRF: bare-metal network reachable via veth
#      (so Ironic can reach IPA agents on port 9999)
#    - VRF: metalbox network reachable via veth
#      (so httpd replies can reach back to the node)
# -----------------------------------------------------------------------------
echo "INFO: [4/7] Adding cross-VRF routes..."
for bm_net in ${BM_NETWORKS}; do
  echo "INFO:   default VRF: ${bm_net} via ${TRANSIT_IP_VRF} dev vrf-bridge0"
  ip route add "${bm_net}" via "${TRANSIT_IP_VRF}" dev vrf-bridge0
done
echo "INFO:   VRF (table ${VRF_TABLE}): ${MB_NETWORK} via ${TRANSIT_IP_DEFAULT} dev vrf-bridge1"
ip route add "${MB_NETWORK}" via "${TRANSIT_IP_DEFAULT}" dev vrf-bridge1 table "${VRF_TABLE}"

# -----------------------------------------------------------------------------
# 5. Return path for SNAT replies
#    Problem: Outbound traffic is SNATed to src=LOOPBACK1_IP. The reply comes
#    back to dst=LOOPBACK1_IP. But that address is local on loopback1 in the
#    VRF — the kernel would deliver the packet locally instead of sending it
#    back through the veth pair.
#
#    Solution: A dedicated routing table (200) that routes LOOPBACK1_IP
#    through the veth, combined with ip rules that only apply to traffic
#    arriving on the fabric-facing interfaces.
#
#    DNAT traffic (DNAT_PORTS) is not affected because DNAT rewrites the
#    destination to METALBOX_IP before the routing decision — so the ip rule
#    matching "to LOOPBACK1_IP" does not trigger for those packets.
# -----------------------------------------------------------------------------
echo "INFO: [5/7] Setting up SNAT return path (table 200, interfaces: ${FABRIC_INTERFACES})..."
ip route add "${LOOPBACK1_IP}/32" via "${TRANSIT_IP_DEFAULT}" dev vrf-bridge1 table 200

for iface in ${FABRIC_INTERFACES}; do
  echo "INFO:   ip rule: iif ${iface} to ${LOOPBACK1_IP} -> table 200"
  ip rule add iif "${iface}" to "${LOOPBACK1_IP}" lookup 200 priority 100
done

# -----------------------------------------------------------------------------
# 6. SNAT (outbound)
#    Traffic from the transit network gets LOOPBACK1_IP as source — the only
#    address announced via BGP in the fabric. Without SNAT, the switches
#    would not be able to route replies because the transit IPs are unknown
#    in the fabric.
# -----------------------------------------------------------------------------
echo "INFO: [6/7] Adding SNAT rule (outbound: src ${TRANSIT_IP_DEFAULT}/${TRANSIT_CIDR} -> ${LOOPBACK1_IP})..."
iptables -t nat -A POSTROUTING \
  -s "${TRANSIT_IP_DEFAULT}/${TRANSIT_CIDR}" \
  -j SNAT --to-source "${LOOPBACK1_IP}"

# -----------------------------------------------------------------------------
# 7. DNAT (inbound)
#    IPA agents connect to LOOPBACK1_IP on the configured DNAT_PORTS
#    (default: 80, 443, 6385). All services run on METALBOX_IP in the default VRF. DNAT rewrites
#    the destination, the packet crosses the veth into the default VRF, and
#    conntrack handles the reverse path automatically.
# -----------------------------------------------------------------------------
echo "INFO: [7/7] Adding DNAT rule (inbound: dst ${LOOPBACK1_IP}:${DNAT_PORTS} -> ${METALBOX_IP})..."
iptables -t nat -A PREROUTING \
  -d "${LOOPBACK1_IP}/32" -p tcp -m multiport --dports "${DNAT_PORTS}" \
  -j DNAT --to-destination "${METALBOX_IP}"

echo "INFO: VRF bridge setup complete."

# =============================================================================
# FRR compatibility
# =============================================================================
# No changes to the FRR configuration are needed. The redistribute route-maps
# only match loopback0 (BMC) and loopback1 (data). vrf-bridge0/vrf-bridge1
# are NOT announced into the fabric. All static routes remain local.
#
# =============================================================================
# Verification
# =============================================================================
# Outbound (Ironic -> IPA):
#   ping <any-node-ip>
#   curl -k https://<any-node-ip>:9999/v1/commands/
#
# Inbound (IPA -> httpd):
#   sudo ip vrf exec ${VRF_NAME} curl http://${LOOPBACK1_IP}:80/
#   sudo ip vrf exec ${VRF_NAME} curl -k https://${LOOPBACK1_IP}:443/
#   sudo ip vrf exec ${VRF_NAME} curl http://${LOOPBACK1_IP}:6385/
#
# =============================================================================
# Teardown (if needed)
# =============================================================================
# for iface in ${FABRIC_INTERFACES}; do
#   ip rule del iif "${iface}" to "${LOOPBACK1_IP}" lookup 200 priority 100
# done
# ip route del "${LOOPBACK1_IP}/32" table 200
# for bm_net in ${BM_NETWORKS}; do
#   ip route del "${bm_net}" via "${TRANSIT_IP_VRF}"
# done
# ip route del "${MB_NETWORK}" via "${TRANSIT_IP_DEFAULT}" table "${VRF_TABLE}"
# iptables -t nat -D POSTROUTING -s "${TRANSIT_IP_DEFAULT}/${TRANSIT_CIDR}" -j SNAT --to-source "${LOOPBACK1_IP}"
# iptables -t nat -D PREROUTING -d "${LOOPBACK1_IP}/32" -p tcp -m multiport --dports "${DNAT_PORTS}" -j DNAT --to-destination "${METALBOX_IP}"
# ip link del vrf-bridge0
