# Web Terminal Setup

Web Terminal is an optional root-only feature. It is disabled or unavailable
until its host dependencies pass the environment check.

The terminal never opens a host shell. Each session starts a restricted Docker
container and mounts only the existing root Cloud Drive storage directory into
`/home/root`.

## One Command Setup

From the repository root:

```bash
./install_web_terminal_dependencies.sh --all --venv .venv
```

The script handles the common setup path:

- installs Docker, Node/npm, and `python3-venv` with `sudo apt`
- installs Python dependencies into `.venv`
- installs local xterm.js assets into `public/vendor/xterm`
- builds the required Docker image: `hackme-web-terminal:base`

The image is based on the official Ubuntu 24.04 LTS container distribution and
preinstalls the standard terminal userspace (`ubuntu-standard`, bash, apt tools,
man pages, tmux, git, curl, rsync, ssh client, and common diagnostic commands).
Sessions still run with `network none`, `read-only` rootfs, dropped Linux
capabilities, and only the root user's Cloud Drive mounted at `/home/root`.
Use the Dockerfile and rebuild the image to add more tools; browser sessions are
not intended to install packages live.

Then verify:

```bash
./install_web_terminal_dependencies.sh --doctor --venv .venv
```

## Docker Permission Notes

If Docker was just installed or the current user was just added to the Docker
group, the current shell and any already-running server process may not see the
new group membership yet.

The script prints the exact repair command. The usual fix is:

```bash
sudo usermod -aG docker "$USER"
```

After that, log out and back in, or restart the systemd/service/shell process
that launches Hackme Web. Confirm Docker access without sudo:

```bash
id -nG
docker info
docker image inspect hackme-web-terminal:base
```

If `id -nG "$USER"` shows `docker` but plain `id -nG` does not, the account
database has been updated but the current session has not loaded the new group
membership. Start a fresh login shell, or use this temporary launch path from
the repository root:

```bash
newgrp docker
scripts/run_prod.sh
```

For a one-shot launch without changing the current shell:

```bash
sg docker -c 'scripts/run_prod.sh'
```

If only the image build is blocked by Docker permission and you are in an
interactive terminal, the installer can use sudo for the build:

```bash
sudo ./install_web_terminal_dependencies.sh --image
```

The running Hackme Web process still needs normal Docker access to start
terminal sessions from the browser.

## Browser-Side Check

When root opens the Web Terminal page, the frontend calls the server status API
before enabling the terminal. It checks:

- the feature toggle is enabled
- Docker CLI and daemon access
- `hackme-web-terminal:base` image
- xterm.js local assets
- Python WebSocket package availability
- the resolved Cloud Drive mount path

If any item fails, run:

```bash
./install_web_terminal_dependencies.sh --doctor --venv .venv
```

and follow the printed repair instructions.
