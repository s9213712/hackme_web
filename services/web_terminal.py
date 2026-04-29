import os
import pty
import select
import shutil
import subprocess
import threading
import time
import uuid
import grp
import pwd
from dataclasses import dataclass
from datetime import datetime

from services.storage_paths import resolve_storage_path


DEFAULT_TERMINAL_IMAGE = "hackme-web-terminal:base"
DEFAULT_IDLE_TIMEOUT_SECONDS = 900
DEFAULT_CPU_LIMIT = "0.5"
DEFAULT_MEMORY_LIMIT = "256m"
DEFAULT_PIDS_LIMIT = "128"
DEFAULT_NETWORK_MODE = "bridge"
ALLOWED_NETWORK_MODES = {"none", "bridge", "host"}


def normalize_web_terminal_network_mode(value):
    mode = str(value or DEFAULT_NETWORK_MODE).strip().lower()
    return mode if mode in ALLOWED_NETWORK_MODES else DEFAULT_NETWORK_MODE


def ensure_web_terminal_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS web_terminal_sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            status TEXT NOT NULL,
            container_name TEXT,
            container_id TEXT,
            image TEXT NOT NULL,
            mount_path TEXT NOT NULL,
            cpu_limit TEXT NOT NULL,
            memory_limit TEXT NOT NULL,
            pids_limit TEXT NOT NULL,
            network_mode TEXT NOT NULL DEFAULT 'none',
            no_new_privileges INTEGER NOT NULL DEFAULT 1,
            cap_drop TEXT NOT NULL DEFAULT 'ALL',
            created_at TEXT NOT NULL,
            last_activity_at TEXT NOT NULL,
            closed_at TEXT,
            close_reason TEXT,
            error_message TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_web_terminal_sessions_user ON web_terminal_sessions(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_web_terminal_sessions_status ON web_terminal_sessions(status, created_at)")


def root_terminal_mount_path(storage_root, root_user_id):
    relative = f"users/{int(root_user_id)}"
    path = resolve_storage_path(storage_root, relative, create_parent=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class WebTerminalPolicy:
    image: str = DEFAULT_TERMINAL_IMAGE
    cpu_limit: str = DEFAULT_CPU_LIMIT
    memory_limit: str = DEFAULT_MEMORY_LIMIT
    pids_limit: str = DEFAULT_PIDS_LIMIT
    idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS
    network_mode: str = DEFAULT_NETWORK_MODE


def build_container_command(*, session_id, mount_path, policy=None):
    policy = policy or WebTerminalPolicy()
    container_name = f"hackme_web_terminal_{session_id}"
    return [
        "docker",
        "run",
        "--rm",
        "-i",
        "-t",
        "--name",
        container_name,
        "--network",
        policy.network_mode,
        "--cpus",
        str(policy.cpu_limit),
        "--memory",
        str(policy.memory_limit),
        "--pids-limit",
        str(policy.pids_limit),
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=64m",
        "--tmpfs",
        "/run:rw,nosuid,nodev,noexec,size=16m",
        "--tmpfs",
        "/var/tmp:rw,nosuid,nodev,noexec,size=64m",
        "-e",
        "TERM=xterm-256color",
        "-v",
        f"{str(mount_path)}:/home/root:rw",
        "-w",
        "/home/root",
        str(policy.image),
        "/bin/bash",
        "-l",
    ]


class WebTerminalSession:
    def __init__(self, *, session_id, actor, mount_path, command, process, master_fd, audit, conn_factory, idle_timeout_seconds):
        self.session_id = session_id
        self.actor = actor
        self.mount_path = mount_path
        self.command = command
        self.process = process
        self.master_fd = master_fd
        self.audit = audit
        self.conn_factory = conn_factory
        self.idle_timeout_seconds = idle_timeout_seconds
        self.last_activity = time.time()
        self.closed = False
        self._lock = threading.Lock()

    def touch(self):
        self.last_activity = time.time()

    def idle_expired(self):
        return time.time() - self.last_activity > self.idle_timeout_seconds

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8", "ignore")
        os.write(self.master_fd, data)
        self.touch()

    def read_available(self, timeout=0.2):
        ready, _, _ = select.select([self.master_fd], [], [], timeout)
        if not ready:
            return b""
        data = os.read(self.master_fd, 4096)
        if data:
            self.touch()
        return data

    def close(self, reason="closed"):
        with self._lock:
            if self.closed:
                return
            self.closed = True
        try:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
        finally:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            try:
                conn = self.conn_factory()
                try:
                    ensure_web_terminal_schema(conn)
                    conn.execute(
                        """
                        UPDATE web_terminal_sessions
                        SET status='closed', closed_at=?, close_reason=?
                        WHERE id=?
                        """,
                        (datetime.now().isoformat(), str(reason), self.session_id),
                    )
                    conn.commit()
                finally:
                    conn.close()
            except Exception:
                pass
            self.audit(
                "WEB_TERMINAL_SESSION_CLOSE",
                "",
                user=self.actor.get("username"),
                success=True,
                detail=f"session_id={self.session_id}, reason={reason}, mount_path={self.mount_path}",
            )


class WebTerminalManager:
    def __init__(self, *, get_db, storage_root, audit, policy=None, policy_provider=None):
        self.get_db = get_db
        self.storage_root = storage_root
        self.audit = audit
        self.policy = policy or WebTerminalPolicy()
        self.policy_provider = policy_provider

    def _policy(self):
        if not self.policy_provider:
            return self.policy
        policy = self.policy_provider()
        if isinstance(policy, WebTerminalPolicy):
            return policy
        return self.policy

    def create_session(self, actor):
        if not actor or actor.get("username") != "root":
            raise PermissionError("only root can open web terminal")
        policy = self._policy()
        session_id = uuid.uuid4().hex
        mount_path = root_terminal_mount_path(self.storage_root, actor["id"])
        command = build_container_command(session_id=session_id, mount_path=mount_path, policy=policy)
        container_name = f"hackme_web_terminal_{session_id}"
        created_at = datetime.now().isoformat()

        conn = self.get_db()
        try:
            ensure_web_terminal_schema(conn)
            conn.execute(
                """
                INSERT INTO web_terminal_sessions (
                    id, user_id, username, status, container_name, image, mount_path,
                    cpu_limit, memory_limit, pids_limit, network_mode, no_new_privileges,
                    cap_drop, created_at, last_activity_at
                ) VALUES (?, ?, ?, 'starting', ?, ?, ?, ?, ?, ?, ?, 1, 'ALL', ?, ?)
                """,
                (
                    session_id,
                    int(actor["id"]),
                    actor["username"],
                    container_name,
                    policy.image,
                    str(mount_path),
                    policy.cpu_limit,
                    policy.memory_limit,
                    policy.pids_limit,
                    policy.network_mode,
                    created_at,
                    created_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        self.audit(
            "WEB_TERMINAL_CONTAINER_LIMITS",
            "",
            user=actor.get("username"),
            success=True,
            detail=(
                f"session_id={session_id}, image={policy.image}, cpu={policy.cpu_limit}, "
                f"memory={policy.memory_limit}, pids={policy.pids_limit}, network={policy.network_mode}, "
                f"no_new_privileges=1, cap_drop=ALL"
            ),
        )
        self.audit(
            "WEB_TERMINAL_MOUNT_PATH",
            "",
            user=actor.get("username"),
            success=True,
            detail=f"session_id={session_id}, mount_path={mount_path}, container_path=/home/root",
        )

        master_fd, slave_fd = pty.openpty()
        try:
            process = subprocess.Popen(
                command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                start_new_session=True,
            )
        except Exception as exc:
            os.close(master_fd)
            os.close(slave_fd)
            self._mark_failed(session_id, actor, mount_path, exc)
            raise
        finally:
            try:
                os.close(slave_fd)
            except OSError:
                pass

        conn = self.get_db()
        try:
            ensure_web_terminal_schema(conn)
            conn.execute(
                "UPDATE web_terminal_sessions SET status='active', container_id=?, last_activity_at=? WHERE id=?",
                (str(process.pid), datetime.now().isoformat(), session_id),
            )
            conn.commit()
        finally:
            conn.close()

        self.audit(
            "WEB_TERMINAL_SESSION_CREATE",
            "",
            user=actor.get("username"),
            success=True,
            detail=f"session_id={session_id}, container_name={container_name}, mount_path={mount_path}",
        )
        return WebTerminalSession(
            session_id=session_id,
            actor=actor,
            mount_path=mount_path,
            command=command,
            process=process,
            master_fd=master_fd,
            audit=self.audit,
            conn_factory=self.get_db,
            idle_timeout_seconds=policy.idle_timeout_seconds,
        )

    def _mark_failed(self, session_id, actor, mount_path, exc):
        conn = self.get_db()
        try:
            ensure_web_terminal_schema(conn)
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE web_terminal_sessions SET status='failed', closed_at=?, close_reason='failed', error_message=? WHERE id=?",
                (now, str(exc), session_id),
            )
            conn.commit()
        finally:
            conn.close()
        self.audit(
            "WEB_TERMINAL_SESSION_FAIL",
            "",
            user=actor.get("username") if actor else None,
            success=False,
            detail=f"session_id={session_id}, mount_path={mount_path}, error={exc}",
        )

    def status_payload(self, actor, *, feature_enabled=True):
        policy = self._policy()
        websocket_available = False
        websocket_error = ""
        try:
            import flask_sock  # noqa: F401
            websocket_available = True
        except Exception as exc:
            websocket_available = False
            websocket_error = str(exc)
        runtime = _find_runtime_binary()
        runtime_accessible = False
        runtime_error = ""
        image_available = False
        image_error = ""
        process_info = _process_docker_context()
        if runtime:
            runtime_accessible, runtime_error = _docker_daemon_accessible(runtime)
            if runtime_accessible:
                image_available, image_error = _docker_image_available(runtime, policy.image)
        return {
            "enabled": bool(feature_enabled and actor and actor.get("username") == "root"),
            "websocket_available": websocket_available,
            "websocket_error": websocket_error,
            "runtime_binary_available": bool(runtime),
            "runtime_available": bool(runtime and runtime_accessible),
            "runtime_error": runtime_error,
            "runtime": runtime or "docker",
            "image_available": image_available,
            "image_error": image_error,
            "image": policy.image,
            "process": process_info,
            "limits": {
                "cpu": policy.cpu_limit,
                "memory": policy.memory_limit,
                "pids": policy.pids_limit,
                "network": policy.network_mode,
                "no_new_privileges": True,
                "cap_drop": "ALL",
                "idle_timeout_seconds": policy.idle_timeout_seconds,
            },
        }


def _find_runtime_binary():
    for name in ("docker",):
        if shutil.which(name):
            return name
    return None


def _docker_image_available(runtime, image):
    try:
        result = subprocess.run(
            [runtime, "image", "inspect", str(image)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or "").strip()


def _docker_daemon_accessible(runtime):
    try:
        result = subprocess.run(
            [runtime, "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or "").strip()


def _process_docker_context():
    groups = []
    try:
        groups = [grp.getgrgid(gid).gr_name for gid in os.getgroups()]
    except Exception:
        groups = [str(gid) for gid in os.getgroups()]
    socket = {"path": "/var/run/docker.sock", "exists": False}
    try:
        stat = os.stat("/var/run/docker.sock")
        socket = {
            "path": "/var/run/docker.sock",
            "exists": True,
            "uid": int(stat.st_uid),
            "gid": int(stat.st_gid),
            "user": pwd.getpwuid(stat.st_uid).pw_name,
            "group": grp.getgrgid(stat.st_gid).gr_name,
            "mode": oct(stat.st_mode & 0o777),
        }
    except Exception as exc:
        socket["error"] = str(exc)
    return {
        "uid": os.getuid(),
        "gid": os.getgid(),
        "user": pwd.getpwuid(os.getuid()).pw_name,
        "groups": groups,
        "docker_sock": socket,
    }
