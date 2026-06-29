# Select the key-value store service for the active OpenStack release. Upstream
# kolla-ansible replaced redis with valkey at 2025.2; older releases still ship
# redis. The release is read from the kolla-ansible image label.
valkey_or_redis() {
    local openstack_version
    openstack_version=$(docker inspect --format '{{ index .Config.Labels "de.osism.release.openstack" }}' kolla-ansible 2>/dev/null)
    case "$openstack_version" in
        2023.*|2024.*|2025.1) echo redis ;;
        *) echo valkey ;;
    esac
}
