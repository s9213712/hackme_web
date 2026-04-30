# QEMU/libvirt WebTerminal Attempt

Status: abandoned and historical only.

## Goal

The QEMU version tried to replace Docker with short-lived Ubuntu virtual
machines managed through libvirt/KVM. The VM approach improved isolation in
principle because the terminal ran in a guest OS instead of a container on the
host.

The intended flow was:

- root opens WebTerminal from the browser
- backend clones a prepared Ubuntu cloud image
- libvirt starts a temporary VM
- browser terminal connects through a controlled SSH bridge
- the VM receives a Cloud Drive mount or synchronized workspace
- session close cleans up the VM

## What Worked

- Dependency checks could verify `virsh`, `virt-install`, `qemu-img`,
  `cloud-localds`, SSH tooling, KVM availability, and base images.
- Ubuntu cloud images could be downloaded and used as base images.
- Temporary VMs could be created in some local host configurations.

## Why It Was Abandoned

The isolation was better than Docker, but the deployment cost was too high for
the main project. The feature required host virtualization knowledge and was
fragile across ordinary desktop and server setups.

Repeated failure points included:

- libvirt/KVM group and daemon permissions.
- storage ACLs for `/var/lib/hackme-vms`.
- NAT bridge startup and host firewall backend conflicts.
- guest network connectivity and DNS troubleshooting.
- VM boot timing and SSH readiness detection.
- cloud-init provisioning noise and inconsistent terminal sizing.
- higher memory and disk requirements than the rest of Hackme Web.

## Decision

The QEMU branch was preserved for audit history, but the active `main`
line does not include WebTerminal runtime code. The old QEMU scripts are not a
supported install path.
