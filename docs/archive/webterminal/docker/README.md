# Docker WebTerminal Attempt

Status: abandoned and historical only.

## Goal

The Docker version tried to provide a root-only browser terminal by creating a
short-lived Linux container for each terminal session. The container mounted only
the root user's existing Cloud Drive storage directory so the terminal would not
create a second file system.

The intended constraints were:

- no host shell access
- no project-root mount
- no `/`, `/etc`, `/var/run/docker.sock` mount inside the terminal container
- limited CPU, memory, pids, capabilities, and network mode
- session cleanup on close
- audit log entries for session lifecycle and mount paths

## What Worked

- The basic environment check flow could report Docker daemon reachability.
- A container image could be built locally.
- The browser could show a terminal panel.

## Why It Was Abandoned

The design depended on the web backend being able to control Docker. On typical
hosts this meant the server process needed Docker daemon permissions, which is
easy to misconfigure and hard for non-expert users to debug. Giving a web
process Docker access also raised the blast radius of a web compromise.

Operational issues repeatedly showed up:

- Docker socket permission failures.
- Image build and image lookup drift.
- Confusing host/user group requirements.
- Minimal container images lacked expected tools.
- Cloud Drive bind mounts needed careful ownership mapping.
- Terminal UX depended heavily on image choice and shell provisioning.

## Decision

The Docker branch was preserved for reference, but removed from the active
project. It should not be treated as a supported optional feature.

