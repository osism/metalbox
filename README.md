# metalbox

1. Download the metalbox image from the well known URL
2. Write the metalbox image to the disk and boot it (initial boot takes some time)
3. Export your NetBox configuration repository with `netbox-manager export`
   and transfer it to `/opt/netbox-export.tar.gz`
4. Run the `import.sh` script in `/opt/configuration/netbox`
5. Deploy the NetBox service with `./run.sh netbox` in `/opt/configuration/environments/manager`
6. Run the `manage.sh` script in `/opt/configuration/netbox`
7. Deploy the Manager service with `./run.sh manager` in `/opt/configuration/environments/manager`
8. Sync inventory with `osism sync inventory`
9. Sync `/etc/hosts` with `osism apply hosts`
10. Sync facts with `osism apply facts`
11. Deploy the infrastructure services

   ```
   osism apply common
   osism apply loadbalancer
   osism apply redis
   osism apply memcached
   osism apply rabbitmq
   osism apply mariadb
   osism apply dnsmasq
   osism apply httpd
   ```

12. Transfer the `sonic-broadcom-enterprise-base.bin` file to
    `/opt/httpd/data/sonic-broadcom-enterprise-base.bin`

13. Copy required Ironic image files

   ```
   docker exec osism-ansible mkdir -p /share/ironic/ironic
   docker cp  /opt/ironic-agent.initramfs osisim-ansible:/share/ironic/ironic/ironic-agent.initramfs
   docker cp  /opt/ironic-agent.kernek osisim-ansible:/share/ironic/ironic/ironic-agent.kernel
   ```

14. Deploy the OpenStack services

   ```
   osism apply keystone
   osism apply ironic
   osism apply openstackclient
   ```

15. Sync baremetal nodes with `osism sync ironic`
