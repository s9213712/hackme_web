import json
import os
import re
import grp
import pwd
import shutil
import socket
import stat
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


VM_NAME_RE = re.compile(r"^hackme-term-u\d+-[a-f0-9]{10}$")
SAFE_NETWORK_MODES = {"none", "nat", "restricted", "user"}
SAFE_DISTROS = {"ubuntu-22.04", "ubuntu-24.04"}
HEALTH_HINTS = {
    "command:virsh": {
        "label": "virsh 指令",
        "why": "後端需要 virsh 連到 libvirt 管理 VM。",
        "repair": "./install_web_terminal_qemu_dependencies.sh --system",
    },
    "command:virt-install": {
        "label": "virt-install 指令",
        "why": "建立 cloud image VM 時需要 virt-install。",
        "repair": "./install_web_terminal_qemu_dependencies.sh --system",
    },
    "command:qemu-img": {
        "label": "qemu-img 指令",
        "why": "建立 qcow2 overlay disk 時需要 qemu-img。",
        "repair": "./install_web_terminal_qemu_dependencies.sh --system",
    },
    "command:cloud-localds": {
        "label": "cloud-localds 指令",
        "why": "建立 cloud-init seed ISO 時需要 cloud-localds。",
        "repair": "./install_web_terminal_qemu_dependencies.sh --system",
    },
    "command:ssh": {
        "label": "ssh 指令",
        "why": "目前 MVP 透過 SSH 將 VM terminal 串到 WebSocket。",
        "repair": "./install_web_terminal_qemu_dependencies.sh --system",
    },
    "kvm_device": {
        "label": "/dev/kvm",
        "why": "KVM 加速需要 /dev/kvm；缺少時通常是 BIOS/UEFI 未開啟虛擬化或 WSL/外層 VM 未開 nested virtualization。",
        "repair": "確認 BIOS/UEFI virtualization 與 nested virtualization，然後重新登入主機。",
    },
    "base_image": {
        "label": "Ubuntu base image",
        "why": "WebTerminal 會從 Ubuntu cloud image 建立臨時 VM overlay；檔案不存在或不可讀都不能啟動。",
        "repair": "./install_web_terminal_qemu_dependencies.sh --image；若檔案存在但不可讀，執行 ./install_web_terminal_qemu_dependencies.sh --fix-vm-storage-permissions",
    },
    "vm_storage_dir": {
        "label": "VM 儲存目錄",
        "why": "後端需要在 VM 儲存目錄建立 overlay disk、cloud-init seed 與 session key。",
        "repair": "./install_web_terminal_qemu_dependencies.sh --dirs，並確認啟動 server 的使用者在 libvirt 群組。",
    },
    "libvirt_connection": {
        "label": "libvirt 連線",
        "why": "後端必須能連到 qemu:///system；失敗通常是 libvirtd 未啟動或 server 使用者沒有 libvirt 權限。",
        "repair": "sudo systemctl enable --now libvirtd；sudo usermod -aG libvirt,kvm $USER；登出重登並重啟 server。",
    },
    "libvirt_default_network": {
        "label": "libvirt default NAT network",
        "why": "NAT/受限 NAT 模式需要 libvirt default network，否則 VM 取不到 IP，WebSocket SSH bridge 無法連線。",
        "repair": "sudo virsh net-start default；sudo virsh net-autostart default",
    },
    "interactive_network": {
        "label": "WebTerminal 互動網路",
        "why": "目前 WebTerminal MVP 透過 SSH bridge 連線，必須使用 NAT、受限 NAT 或 QEMU user-mode NAT。network=none 要等 serial console bridge 實作後才能互動。",
        "repair": "到 root 系統設定將 WebTerminal 網路模式改成 QEMU user-mode NAT、NAT 出網或受限 NAT。",
    },
}


class WebTerminalQemuError(RuntimeError):
    pass


@dataclass
class TerminalSession:
    session_id: str
    user_id: int
    username: str
    vm_name: str
    status: str = "provisioning"
    message: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    ip_address: str = ""
    ssh_username: str = "root"
    ssh_key_path: str = ""
    host_ssh_port: int = 0
    disk_path: str = ""
    seed_dir: str = ""
    network_mode: str = "none"
    distro: str = "ubuntu-22.04"
    vcpus: int = 1
    memory_mb: int = 1024
    disk_gb: int = 10

    def payload(self):
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "username": self.username,
            "vm_name": self.vm_name,
            "status": self.status,
            "message": self.message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "ip_address": self.ip_address,
            "ssh_username": self.ssh_username,
            "host_ssh_port": self.host_ssh_port,
            "network_mode": self.network_mode,
            "distro": self.distro,
            "vcpus": self.vcpus,
            "memory_mb": self.memory_mb,
            "disk_gb": self.disk_gb,
        }


def _setting(settings, key, default):
    value = (settings or {}).get(key, default)
    return default if value is None else value


def _int_setting(settings, key, default, *, minimum, maximum):
    try:
        value = int(_setting(settings, key, default))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _name_for_uid(uid):
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _name_for_gid(gid):
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def _hypervisor_can_probably_read(path):
    try:
        st = Path(path).stat()
    except OSError:
        return False
    mode = st.st_mode
    owner = _name_for_uid(st.st_uid)
    group = _name_for_gid(st.st_gid)
    if owner == "libvirt-qemu" and mode & stat.S_IRUSR:
        return True
    if group in {"libvirt", "kvm", "libvirt-qemu"} and mode & stat.S_IRGRP:
        return True
    return bool(mode & stat.S_IROTH)


def qemu_config_from_settings(settings, *, base_dir):
    distro = str(
        _setting(
            settings,
            "web_terminal_qemu_distro",
            _setting(settings, "web_terminal_distribution", "ubuntu-22.04"),
        ) or "ubuntu-22.04"
    ).strip()
    if distro not in SAFE_DISTROS:
        distro = "ubuntu-22.04"
    network_mode = str(
        _setting(
            settings,
            "web_terminal_qemu_network_mode",
            _setting(settings, "web_terminal_network_mode", "none"),
        ) or "none"
    ).strip()
    if network_mode in {"bridge", "internet", "online"}:
        network_mode = "nat"
    if network_mode in {"usernat", "slirp", "qemu-user", "qemu_user"}:
        network_mode = "user"
    if network_mode in {"offline", "disabled"}:
        network_mode = "none"
    if network_mode not in SAFE_NETWORK_MODES:
        network_mode = "none"
    vm_root = str(_setting(settings, "web_terminal_qemu_storage_dir", "/var/lib/hackme-vms") or "").strip()
    base_image = str(_setting(settings, "web_terminal_qemu_base_image_path", "") or "").strip()
    if not base_image:
        image_name = "jammy-server-cloudimg-amd64.img" if distro == "ubuntu-22.04" else "noble-server-cloudimg-amd64.img"
        base_image = str(Path(vm_root) / "base" / image_name)
    return {
        "enabled": bool(_setting(settings, "web_terminal_enabled", False)),
        "libvirt_uri": str(_setting(settings, "web_terminal_qemu_libvirt_uri", "qemu:///system") or "qemu:///system"),
        "vm_root": vm_root,
        "base_image": base_image,
        "distro": distro,
        "network_mode": network_mode,
        "vcpus": _int_setting(settings, "web_terminal_qemu_vcpus", 1, minimum=1, maximum=4),
        "memory_mb": _int_setting(settings, "web_terminal_qemu_memory_mb", 1024, minimum=512, maximum=8192),
        "disk_gb": _int_setting(settings, "web_terminal_qemu_disk_gb", 10, minimum=5, maximum=100),
        "idle_timeout_seconds": _int_setting(settings, "web_terminal_qemu_idle_timeout_seconds", 900, minimum=60, maximum=86400),
        "cloud_drive_sync": str(_setting(settings, "web_terminal_qemu_cloud_drive_sync", "staged") or "staged"),
        "base_dir": base_dir,
    }


def validate_vm_root(vm_root, *, project_base_dir):
    raw = str(vm_root or "").strip()
    if not raw:
        raise ValueError("VM storage dir is required")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("VM storage dir must be absolute")
    resolved = path.resolve()
    forbidden = {Path("/"), Path("/etc"), Path("/var/run"), Path("/run"), Path("/proc"), Path("/sys"), Path("/dev")}
    if resolved in forbidden:
        raise ValueError("VM storage dir is unsafe")
    project = Path(project_base_dir).resolve()
    if resolved == project or project in resolved.parents:
        raise ValueError("VM storage dir must not be inside the project")
    return resolved


class LibvirtQemuProvider:
    def __init__(self, *, libvirt_uri="qemu:///system", timeout=30):
        self.libvirt_uri = libvirt_uri
        self.timeout = timeout

    def run(self, args, *, timeout=None, input_text=None):
        completed = subprocess.run(
            list(args),
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout or self.timeout,
            check=False,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "ok": completed.returncode == 0,
            "args": list(args),
        }

    def virsh(self, *args, timeout=None):
        return self.run(["virsh", "-c", self.libvirt_uri, *args], timeout=timeout)

    def health(self, config):
        checks = []

        def add(name, ok, message="", detail=None):
            hint = HEALTH_HINTS.get(name, {})
            checks.append({
                "name": name,
                "label": hint.get("label", name),
                "ok": bool(ok),
                "message": message,
                "detail": detail,
                "why": hint.get("why", ""),
                "repair": "" if ok else hint.get("repair", ""),
            })

        def path_state(path):
            try:
                p = Path(path)
                exists = p.exists()
                readable = os.access(p, os.R_OK) if exists else False
                return exists, readable, ""
            except OSError as exc:
                return False, False, str(exc)

        for command in ("virsh", "virt-install", "qemu-img", "cloud-localds", "ssh"):
            add(f"command:{command}", bool(shutil.which(command)), "found" if shutil.which(command) else "missing")

        add("kvm_device", os.path.exists("/dev/kvm"), "/dev/kvm exists" if os.path.exists("/dev/kvm") else "/dev/kvm missing")
        image_exists, image_readable, image_error = path_state(config["base_image"])
        image_hypervisor_readable = _hypervisor_can_probably_read(config["base_image"]) if image_exists else False
        image_message = config["base_image"]
        if image_error:
            image_message = f"{config['base_image']}: {image_error}"
        elif image_exists and not image_readable:
            image_message = (
                f"{config['base_image']} exists but is not readable by server process "
                f"(uid={os.getuid()}, gid={os.getgid()}, groups={','.join(str(g) for g in os.getgroups())}); "
                f"hypervisor_readable={'yes' if image_hypervisor_readable else 'unknown'}"
            )
        add(
            "base_image",
            image_exists and (image_readable or image_hypervisor_readable),
            image_message,
        )
        try:
            vm_root = validate_vm_root(config["vm_root"], project_base_dir=config["base_dir"])
            add("vm_storage_dir", vm_root.exists() and os.access(vm_root, os.W_OK), str(vm_root))
        except Exception as exc:
            add("vm_storage_dir", False, str(exc))

        if shutil.which("virsh"):
            result = self.virsh("list", "--all", timeout=8)
            add("libvirt_connection", result["ok"], (result["stderr"] or result["stdout"]).strip())
            if config["network_mode"] in {"nat", "restricted"}:
                net = self.virsh("net-info", "default", timeout=8)
                network_active = bool(net["ok"] and re.search(r"(?m)^Active:\s+yes\b", net["stdout"] or ""))
                add("libvirt_default_network", network_active, (net["stderr"] or net["stdout"]).strip())
            elif config["network_mode"] == "none":
                add("interactive_network", False, "network=none 無法搭配目前的 SSH bridge")
        else:
            add("libvirt_connection", False, "virsh missing")

        failed = [row for row in checks if not row["ok"]]
        ok = not failed
        summary = "WebTerminal QEMU/libvirt 環境可用" if ok else f"{len(failed)} 個必要項目未完成"
        return {
            "ok": ok,
            "summary": summary,
            "failed_checks": [row["name"] for row in failed],
            "checks": checks,
            "config": public_config(config),
        }

    def create_overlay_disk(self, *, base_image, disk_path, disk_gb):
        result = self.run([
            "qemu-img", "create", "-f", "qcow2",
            "-u",
            "-F", "qcow2", "-b", base_image,
            disk_path,
            f"{int(disk_gb)}G",
        ])
        if not result["ok"]:
            raise WebTerminalQemuError(result["stderr"] or "qemu-img create failed")

    def create_seed_iso(self, *, seed_iso, user_data, meta_data):
        result = self.run(["cloud-localds", seed_iso, user_data, meta_data])
        if not result["ok"]:
            raise WebTerminalQemuError(result["stderr"] or "cloud-localds failed")

    def virt_install(self, *, session, seed_iso, os_variant):
        args = [
            "virt-install",
            "--connect", self.libvirt_uri,
            "--name", session.vm_name,
            "--memory", str(session.memory_mb),
            "--vcpus", str(session.vcpus),
            "--cpu", "host",
            "--import",
            "--disk", f"path={session.disk_path},format=qcow2,bus=virtio",
            "--disk", f"path={seed_iso},device=cdrom",
            "--os-variant", os_variant,
            "--graphics", "none",
            "--console", "pty,target_type=serial",
            "--noautoconsole",
        ]
        if session.network_mode == "none":
            args.extend(["--network", "none"])
        elif session.network_mode == "user":
            args.extend([
                "--network",
                (
                    f"type=user,model=virtio,"
                    f"xpath0.create=./portForward,"
                    f"xpath1.set=./portForward/@proto=tcp,"
                    f"xpath2.set=./portForward/@address=127.0.0.1,"
                    f"xpath3.create=./portForward/range,"
                    f"xpath4.set=./portForward/range/@start={int(session.host_ssh_port)},"
                    f"xpath5.set=./portForward/range/@to=22"
                ),
            ])
        else:
            args.extend(["--network", "network=default,model=virtio"])
        result = self.run(args, timeout=120)
        if not result["ok"]:
            raise WebTerminalQemuError(result["stderr"] or "virt-install failed")

    def add_user_host_forward(self, *, vm_name, host_port, guest_port=22):
        if not VM_NAME_RE.fullmatch(vm_name or ""):
            raise ValueError("unsafe VM name")
        command = f"hostfwd_add tcp:127.0.0.1:{int(host_port)}-:{int(guest_port)}"
        result = self.virsh("qemu-monitor-command", vm_name, "--hmp", command, timeout=10)
        if not result["ok"]:
            raise WebTerminalQemuError(result["stderr"] or result["stdout"] or "qemu hostfwd_add failed")
        return result

    def destroy_and_undefine(self, vm_name):
        if not VM_NAME_RE.fullmatch(vm_name or ""):
            raise ValueError("unsafe VM name")
        self.virsh("destroy", vm_name, timeout=20)
        return self.virsh("undefine", vm_name, "--remove-all-storage", timeout=60)

    def domain_ip(self, vm_name):
        if not VM_NAME_RE.fullmatch(vm_name or ""):
            raise ValueError("unsafe VM name")
        result = self.virsh("domifaddr", vm_name, "--source", "agent", timeout=8)
        if not result["ok"]:
            result = self.virsh("domifaddr", vm_name, timeout=8)
        output = result["stdout"] or ""
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)/\d+", output)
        return match.group(1) if match else ""


def public_config(config):
    return {
        "enabled": bool(config.get("enabled")),
        "provider": "libvirt-qemu",
        "libvirt_uri": config.get("libvirt_uri"),
        "vm_root": config.get("vm_root"),
        "base_image": config.get("base_image"),
        "distro": config.get("distro"),
        "network_mode": config.get("network_mode"),
        "vcpus": config.get("vcpus"),
        "memory_mb": config.get("memory_mb"),
        "disk_gb": config.get("disk_gb"),
        "idle_timeout_seconds": config.get("idle_timeout_seconds"),
        "cloud_drive_sync": config.get("cloud_drive_sync"),
    }


class QemuWebTerminalManager:
    def __init__(self, *, base_dir, storage_dir, get_settings, audit, provider=None):
        self.base_dir = base_dir
        self.storage_dir = storage_dir
        self.get_settings = get_settings
        self.audit = audit
        self.provider = provider
        self.sessions = {}
        self.lock = threading.Lock()

    def config(self):
        return qemu_config_from_settings(self.get_settings() or {}, base_dir=self.base_dir)

    def health(self):
        config = self.config()
        provider = self.provider or LibvirtQemuProvider(libvirt_uri=config["libvirt_uri"])
        return provider.health(config)

    def list_sessions(self):
        with self.lock:
            return [session.payload() for session in self.sessions.values()]

    def create_session(self, *, actor, ip="-", ua="-"):
        config = self.config()
        if not config["enabled"]:
            self._audit("WEB_TERMINAL_QEMU_CREATE_BLOCKED", actor, ip, False, {"reason": "disabled"})
            return None, "Web Terminal 尚未啟用"
        health = self.health()
        if not health["ok"]:
            self._audit("WEB_TERMINAL_QEMU_CREATE_BLOCKED", actor, ip, False, {"reason": "health_failed", "health": health})
            return None, "Web Terminal 環境檢查失敗"
        if config["network_mode"] == "none":
            self._audit("WEB_TERMINAL_QEMU_CREATE_BLOCKED", actor, ip, False, {"reason": "network_none_not_interactive"})
            return None, "目前 Web Terminal 透過 SSH bridge 連線，請先將網路模式改成 NAT 或受限 NAT"
        vm_root = validate_vm_root(config["vm_root"], project_base_dir=self.base_dir)
        session_id = uuid.uuid4().hex
        vm_name = f"hackme-term-u{int(actor['id'])}-{session_id[:10]}"
        if not VM_NAME_RE.fullmatch(vm_name):
            return None, "VM 名稱不安全"
        session_root = vm_root / "sessions" / session_id
        image_dir = vm_root / "images" / "terminal"
        seed_dir = vm_root / "seed" / session_id
        for path in (session_root, image_dir, seed_dir):
            path.mkdir(parents=True, exist_ok=True)
        session = TerminalSession(
            session_id=session_id,
            user_id=int(actor["id"]),
            username=str(actor["username"]),
            vm_name=vm_name,
            ssh_key_path=str(session_root / "id_ed25519"),
            disk_path=str(image_dir / f"{vm_name}.qcow2"),
            seed_dir=str(seed_dir),
            network_mode=config["network_mode"],
            host_ssh_port=self._allocate_host_port() if config["network_mode"] == "user" else 0,
            distro=config["distro"],
            vcpus=config["vcpus"],
            memory_mb=config["memory_mb"],
            disk_gb=config["disk_gb"],
        )
        with self.lock:
            self.sessions[session_id] = session
        self._audit("WEB_TERMINAL_QEMU_SESSION_CREATE", actor, ip, True, {
            "session_id": session_id,
            "vm_name": vm_name,
            "network_mode": session.network_mode,
            "host_ssh_port": session.host_ssh_port or None,
            "distro": session.distro,
            "vcpus": session.vcpus,
            "memory_mb": session.memory_mb,
            "disk_gb": session.disk_gb,
            "mount_strategy": "cloud_drive_staged_sync",
            "host_mounts": "none",
        })
        threading.Thread(target=self._provision_session, args=(session_id, config, actor, ip, ua), daemon=True).start()
        return session.payload(), None

    def close_session(self, session_id, *, actor=None, ip="-", reason="user_close"):
        session = self.get_session(session_id)
        if not session:
            return False, "找不到 terminal session"
        provider = self.provider or LibvirtQemuProvider(libvirt_uri=self.config()["libvirt_uri"])
        try:
            provider.destroy_and_undefine(session.vm_name)
            self._set_status(session_id, "closed", reason)
            self._audit("WEB_TERMINAL_QEMU_SESSION_CLOSED", actor, ip, True, {"session_id": session_id, "vm_name": session.vm_name, "reason": reason})
            return True, ""
        except Exception as exc:
            self._set_status(session_id, "failed", str(exc))
            self._audit("WEB_TERMINAL_QEMU_SESSION_CLOSE_FAILED", actor, ip, False, {"session_id": session_id, "vm_name": session.vm_name, "error": str(exc)})
            return False, str(exc)

    def get_session(self, session_id):
        with self.lock:
            return self.sessions.get(str(session_id or ""))

    def websocket_ssh_command(self, session_id):
        session = self.get_session(session_id)
        if not session:
            raise WebTerminalQemuError("session not found")
        if session.status != "ready" or not session.ip_address:
            raise WebTerminalQemuError("session is not ready")
        command = [
            "ssh",
            "-tt",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=10",
            "-i", session.ssh_key_path,
        ]
        if session.host_ssh_port:
            command.extend(["-p", str(session.host_ssh_port)])
        command.append(f"{session.ssh_username}@{session.ip_address}")
        return command

    def _provision_session(self, session_id, config, actor, ip, ua):
        session = self.get_session(session_id)
        if not session:
            return
        provider = self.provider or LibvirtQemuProvider(libvirt_uri=config["libvirt_uri"])
        try:
            self._write_ssh_keypair(session)
            user_data, meta_data = self._write_cloud_init(session)
            seed_iso = str(Path(session.seed_dir) / "seed.iso")
            provider.create_overlay_disk(base_image=config["base_image"], disk_path=session.disk_path, disk_gb=session.disk_gb)
            provider.create_seed_iso(seed_iso=seed_iso, user_data=user_data, meta_data=meta_data)
            os_variant = "ubuntu22.04" if session.distro == "ubuntu-22.04" else "ubuntu24.04"
            provider.virt_install(session=session, seed_iso=seed_iso, os_variant=os_variant)
            if session.network_mode == "user":
                provider.add_user_host_forward(vm_name=session.vm_name, host_port=session.host_ssh_port, guest_port=22)
                with self.lock:
                    session.ip_address = "127.0.0.1"
                deadline = time.time() + 120
                while time.time() < deadline:
                    if self._ssh_ready(session):
                        self._set_status(session_id, "ready", f"VM 已啟動；SSH forwarded to 127.0.0.1:{session.host_ssh_port}")
                        return
                    time.sleep(2)
                self._set_status(session_id, "failed", f"VM 已建立但 120 秒內無法透過 127.0.0.1:{session.host_ssh_port} SSH 連線")
                return
            deadline = time.time() + 120
            while time.time() < deadline:
                ip_addr = provider.domain_ip(session.vm_name)
                if ip_addr:
                    with self.lock:
                        session.ip_address = ip_addr
                    self._set_status(session_id, "ready", "VM 已啟動")
                    return
                time.sleep(2)
            self._set_status(session_id, "failed", "VM 已建立但 120 秒內未取得 IP")
        except Exception as exc:
            self._set_status(session_id, "failed", str(exc))
            self._audit("WEB_TERMINAL_QEMU_SESSION_FAILED", actor, ip, False, {"session_id": session_id, "vm_name": session.vm_name, "error": str(exc)})

    def _allocate_host_port(self):
        for _ in range(50):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                port = int(sock.getsockname()[1])
            if port >= 1024:
                return port
        raise WebTerminalQemuError("failed to allocate local SSH forward port")

    def _ssh_ready(self, session):
        command = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=3",
            "-i", session.ssh_key_path,
        ]
        if session.host_ssh_port:
            command.extend(["-p", str(session.host_ssh_port)])
        command.append(f"{session.ssh_username}@{session.ip_address}")
        command.append("true")
        result = subprocess.run(command, text=True, capture_output=True, timeout=8, check=False)
        return result.returncode == 0

    def _write_ssh_keypair(self, session):
        key_path = Path(session.ssh_key_path)
        if key_path.exists():
            return
        result = subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path)],
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        if result.returncode != 0:
            raise WebTerminalQemuError(result.stderr or "ssh-keygen failed")
        key_path.chmod(0o600)

    def _write_cloud_init(self, session):
        seed = Path(session.seed_dir)
        public_key = Path(session.ssh_key_path + ".pub").read_text(encoding="utf-8").strip()
        user_data = seed / "user-data"
        meta_data = seed / "meta-data"
        user_data.write_text(
            "\n".join([
                "#cloud-config",
                "hostname: " + session.vm_name,
                "manage_etc_hosts: true",
                "users:",
                "  - name: root",
                "    shell: /bin/bash",
                "    lock_passwd: true",
                "    ssh_authorized_keys:",
                f"      - {public_key}",
                "ssh_pwauth: false",
                "disable_root: false",
                "package_update: false",
                "runcmd:",
                "  - echo 'hackme_web libvirt terminal VM' > /etc/motd",
                "",
            ]),
            encoding="utf-8",
        )
        meta_data.write_text(f"instance-id: {session.session_id}\nlocal-hostname: {session.vm_name}\n", encoding="utf-8")
        return str(user_data), str(meta_data)

    def _set_status(self, session_id, status, message):
        with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return
            session.status = status
            session.message = message
            session.updated_at = datetime.now().isoformat()

    def _audit(self, event, actor, ip, success, detail):
        try:
            self.audit(
                event,
                ip or "-",
                user=(actor or {}).get("username", "-") if isinstance(actor, dict) else "-",
                success=bool(success),
                detail=json.dumps(detail or {}, ensure_ascii=False, sort_keys=True),
            )
        except Exception:
            pass


def bridge_ssh_to_websocket(command, ws, *, idle_timeout_seconds=900):
    import os
    import pty
    import select

    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(command[0], command)
    last_activity = time.time()
    ws_closed = False
    try:
        while True:
            if time.time() - last_activity > idle_timeout_seconds:
                try:
                    ws.send("\r\n[session idle timeout]\r\n")
                except Exception:
                    pass
                break
            readable, _, _ = select.select([fd], [], [], 0.1)
            if fd in readable:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                last_activity = time.time()
                ws.send(data.decode("utf-8", errors="replace"))
            if not ws_closed:
                try:
                    incoming = ws.receive(timeout=0.01)
                except TypeError:
                    incoming = None
                except Exception:
                    ws_closed = True
                    incoming = None
                if incoming:
                    last_activity = time.time()
                    if isinstance(incoming, str):
                        incoming = incoming.encode("utf-8")
                    os.write(fd, incoming)
    finally:
        try:
            os.close(fd)
        except Exception:
            pass
        try:
            os.kill(pid, 15)
        except Exception:
            pass
