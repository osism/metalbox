# Metalbox installation on an existing server

## Prerequisites

The server needs to be running Ubuntu 24.04 LTS. We recommend having
at least 8 vCPUs, 32 GB RAM and 100 GB SSD disk.

## Basic preparation

Execute these commands as some user on the server that has sudo
access at least via a password. In the command example below
this user is named `osism`, amend the commands accordingly if
you are using a different username.

```
cd
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y git pipx python3-venv sshpass
git clone https://github.com/osism/metalbox/
sudo mv metalbox /opt/configuration
cd /opt/configuration/environments/manager/
echo "ansible_connection: local" >> host_vars/metalbox/vars.yml
./run.sh operator
sudo chown -R dragon:dragon /opt/configuration
```

Note that the `./run.sh operator` playbook invocation creates the
`dragon` user and allows SSH login for
it with a well-known SSH key that is contained in this repo. If your
VM is reachable from the Internet via SSH, you should replace that
key with some locally-generated secure SSH key.

## Log in again as dragon

The previous steps created the `dragon` user account which
will be used to run the Metalbox service. Log in as that user
either directly or by executing `sudo -iu dragon` from your
existing account.

## Prepare the Metalbox installation

Prepare the environment:

```
cd
git clone https://github.com/osism/openstack-ironic-images
cd /opt/configuration/environments/manager/
# Install ansible roles
./run.sh noop
# Run the metalbox preparation playbook
venv/bin/ansible-playbook ~/openstack-ironic-images/elements/metalbox/static/root/part1.yml
# Install some more python libs and another ansible collection
pipx install netbox-manager
pipx install 'ansible-core>=2.19.0,<2.20.0'
/home/dragon/.local/bin/ansible-galaxy collection install netbox.netbox
```

The Metalbox installation runs a set of docker containers from a local registry.
Fill the registry volume with the container images and start the registry:

```
cd
wget -O registry.tar.bz2 https://nbg1.your-objectstorage.com/osism/metalbox/registry.tar.bz2
docker run --rm -v registry:/volume -v /home/dragon:/import library/alpine:3 sh -c 'cd /volume && tar xjf /import/registry.tar.bz2'
docker run -d -p 0.0.0.0:5001:5000 -v registry:/var/lib/registry --name registry --restart always library/registry:3
```

Add a well-known IP address in order for some API operations to work.
Depending on how your network is configured, you may want to add
this configuration to your permanent configuration, e.g. by adding
it to a file in `/etc/netplan`.

```
sudo ip link add metalbox type dummy
sudo ip addr add 192.168.42.10/32 dev metalbox
sudo ip link set up metalbox
```

## Fill the netbox directory

In the directory containing your netbox data (this can be either a
dedicated git repo or the `netbox` subdirectory of your cloudpod
repository) run:

```
netbox-manager export-archive
netbox-manager import-archive
```

This will copy the relevant data into `/opt/configuration/netbox/`.

Deploy the netbox and fill it with data:

```
deploy-netbox.sh
netbox-manage.sh 
```

Each of the above commands can take a couple of minutes to complete.

Run `get-netbox-config.sh NODE` to get the specific configuration for this Metalbox from                                                                     
the NetBox. Replace `NODE` with the name of the Metalbox device in the NetBox.

## Finish the Metalbox installation

Deploy the manager and import the inventory from the NetBox:

```
deploy-manager.sh 
osism sync inventory
```

You can now perform further tasks on the Metalbox as documented
in the general documentation, e.g. manage Ironic nodes or Sonic switches.
