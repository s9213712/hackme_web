# WebTerminal Docker Branch Postmortem

Branch: `02-WebTerminal-docker`

Status: abandoned historical branch. Do not continue product development here.

This branch tested a root-only browser terminal backed by short-lived Docker
containers. The goal was to avoid opening a host shell while still giving root a
usable Linux workspace connected to the existing Cloud Drive storage.

## Development Flow Tested

1. Install Docker, Node/npm, Python WebSocket dependencies, and local xterm.js
   assets.
2. Build terminal images:
   - `hackme-web-terminal:ubuntu-24.04`
   - `hackme-web-terminal:ubuntu-22.04`
   - `hackme-web-terminal:base` compatibility tag.
3. Let root enable WebTerminal and choose distro/network mode in the web UI.
4. On session start, create a short-lived container with:
   - dropped capabilities
   - no-new-privileges
   - CPU, memory, and PID limits
   - root Cloud Drive storage mounted at `/home/root`
5. Bridge xterm.js to the container through backend WebSocket.
6. Remove the container when the session closes.

The implementation intentionally did not mount the project root, `/`, `/etc`,
`/var`, `/run`, `/var/run/docker.sock`, or arbitrary host paths into the
container.

## Errors Encountered

The Docker route worked for simple shell commands, but had repeated deployment
and usability issues:

- The running web server often could not access `/var/run/docker.sock` even when
  the interactive shell could.
- Docker group membership changes required a new login shell or service restart,
  which made the web UI health check confusing.
- Missing `hackme-web-terminal:base` images produced broken first-run behavior
  unless the image script was run with the right flags.
- Container images that were too small lacked expected Ubuntu tools such as
  `apt`, `screen`, and `htop`.
- Network mode choices created a security/usability tradeoff that is difficult
  to make safe by default.
- Mounting Cloud Drive into a container is operationally simple, but it still
  relies on Docker daemon access from the web backend.
- A compromised root web session with Docker daemon access remains too close to
  host-level control unless the host is designed specifically for that threat
  model.

## Debug Flow That Was Needed

The branch added these helpers:

```bash
./install_web_terminal_dependencies.sh --doctor --venv .venv
./install_web_terminal_dependencies.sh --check --venv .venv
./install_web_terminal_dependencies.sh --image
./install_web_terminal_dependencies.sh --xterm
```

The practical order was:

1. Run `--doctor` and confirm Docker CLI, daemon access, xterm assets, Python
   WebSocket packages, and terminal images.
2. If Docker permission failed, check both account groups and current process
   groups with `id -nG`.
3. Restart the server from a new login shell after adding the server user to the
   Docker group.
4. Rebuild images with `--image` when the UI reported `hackme-web-terminal:base`
   missing.
5. Confirm the Cloud Drive mount path resolved through the existing safe path
   logic.

## Why This Was Abandoned

Docker is easier to set up than QEMU, but it still does not fit this project as
a default feature:

- It requires giving the web backend Docker daemon access.
- Docker socket permission problems are common and confusing for non-operator
  users.
- The security boundary is weaker than a VM unless the host is carefully
  hardened.
- Debugging host Docker state became part of normal web app usage.
- The project goal is an installable web app first; WebTerminal should not make
  the basic deployment depend on container daemon operations.

The branch is kept for historical reference only. The Docker setup script may be
archived in `01.Economy` as a non-product reference, but Docker WebTerminal
routes, frontend entry points, runtime services, and settings should not be
merged back into the active main line.
