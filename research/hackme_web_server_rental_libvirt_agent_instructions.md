# hackme_web Server Rental — libvirt/KVM 沙盒伺服器租借系統 Agent 指令檔 v1.0

> 目標：以「未來部署在純 Linux 主機」為基礎，使用 libvirt + KVM 建立可租借的 Ubuntu 22.04 沙盒 VM。  
> 整合：hackme_web 積分 / 訂閱 / 權限 / root 回收權。  
> 定位：正式版以 VM 隔離為主，不使用 WSL，不只靠 Docker。

---

## 0. 最高設計原則

你要為 hackme_web 建立一套「Server Rental Manager」：

```text
使用者付費 / 積分訂閱
→ 系統建立 Ubuntu 22.04 VM
→ 使用者取得 SSH 連線資訊
→ 訂閱期間可使用
→ 到期 / 違規 / 資源不足時 root 可暫停、關機、回收
```

必須符合：

```text
1. 使用 libvirt/KVM 建立真正 VM。
2. 每個使用者的沙盒 VM 與 hackme_web 主系統隔離。
3. 使用者拿到的是 VM 內 root，不是宿主機 root。
4. hackme_web 主資料庫、管理 API、內部服務不得暴露給 VM。
5. 所有建立、續租、扣費、暫停、刪除都必須有 audit log。
6. 訂閱到期後可 suspend，寬限期後可 delete。
7. root 保留強制回收權。
8. MVP 預設 OS 為 Ubuntu 22.04 cloud image。
```

---

# Part A — 宿主機依賴與環境

## A1. 目標宿主機

建議：

```text
Ubuntu Server 22.04 LTS 或 24.04 LTS
CPU 支援 Intel VT-x / AMD-V
BIOS/UEFI 已開啟 virtualization
建議至少 32GB RAM
建議 NVMe SSD
建議獨立網路 bridge 或 NAT network
```

MVP 可以使用 Ubuntu Server 22.04。

---

## A2. 必裝套件

在宿主機執行：

```bash
sudo apt update

sudo apt install -y \
  qemu-kvm \
  libvirt-daemon-system \
  libvirt-clients \
  virtinst \
  virt-manager \
  bridge-utils \
  cloud-image-utils \
  genisoimage \
  libguestfs-tools \
  cpu-checker \
  jq \
  curl \
  wget \
  openssh-client \
  openssh-server \
  uuid-runtime \
  python3 \
  python3-pip \
  python3-venv
```

說明：

```text
qemu-kvm：KVM/QEMU 虛擬化核心
libvirt-daemon-system：libvirt system daemon
libvirt-clients：virsh 等管理工具
virtinst：virt-install 建立 VM
virt-manager：可選 GUI 管理工具
bridge-utils：bridge networking 工具
cloud-image-utils：cloud-init seed image 工具
genisoimage：製作 seed ISO
libguestfs-tools：檢查 / 修改 VM image
cpu-checker：檢查 KVM 支援
jq/curl/wget：API 與腳本工具
uuid-runtime：產生 UUID
python3：若 hackme_web 或管理腳本使用 Python
```

Ubuntu 官方 libvirt 文件列出的核心安裝套件包含 `qemu-kvm` 與 `libvirt-daemon-system`；Ubuntu cloud image 透過 libvirt 啟動時也常用 virt-manager / virt-install 相關工具。

---

## A3. 使用者群組

將管理 VM 的使用者加入群組：

```bash
sudo usermod -aG libvirt "$USER"
sudo usermod -aG kvm "$USER"
```

重新登入或執行：

```bash
newgrp libvirt
```

檢查：

```bash
groups
```

---

## A4. 啟動服務

```bash
sudo systemctl enable --now libvirtd
sudo systemctl status libvirtd
```

若系統使用 modular daemon，也檢查：

```bash
sudo systemctl status virtqemud || true
```

---

## A5. 檢查硬體虛擬化

```bash
egrep -c '(vmx|svm)' /proc/cpuinfo
```

結果大於 0 才表示 CPU 支援。

也可執行：

```bash
sudo kvm-ok
```

期望看到：

```text
KVM acceleration can be used
```

---

## A6. 檢查 libvirt

```bash
virsh -c qemu:///system list --all
virsh -c qemu:///system net-list --all
```

啟用 default network：

```bash
sudo virsh net-start default || true
sudo virsh net-autostart default
```

---

# Part B — 建議目錄結構

在宿主機建立：

```bash
sudo mkdir -p /var/lib/hackme-vms/{base,images,seed,logs,backups,templates}
sudo chown -R root:libvirt /var/lib/hackme-vms
sudo chmod -R 0770 /var/lib/hackme-vms
```

用途：

```text
/var/lib/hackme-vms/base       Ubuntu cloud base image
/var/lib/hackme-vms/images     每台 VM 的 qcow2 disk
/var/lib/hackme-vms/seed       cloud-init seed ISO
/var/lib/hackme-vms/logs       provision / audit logs
/var/lib/hackme-vms/backups    快照 / 備份
/var/lib/hackme-vms/templates  workflow / cloud-init templates
```

---

# Part C — Ubuntu 22.04 Cloud Image

## C1. 下載 base image

```bash
cd /var/lib/hackme-vms/base

sudo wget -O ubuntu-22.04-server-cloudimg-amd64.img \
  https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img
```

設定權限：

```bash
sudo chmod 0640 /var/lib/hackme-vms/base/ubuntu-22.04-server-cloudimg-amd64.img
```

---

## C2. 建立 VM disk

每台 VM 用 backing file 建立 qcow2，避免複製整個 base image。

```bash
VM_ID="sandbox-test-001"
DISK_SIZE="20G"

sudo qemu-img create -f qcow2 \
  -F qcow2 \
  -b /var/lib/hackme-vms/base/ubuntu-22.04-server-cloudimg-amd64.img \
  /var/lib/hackme-vms/images/${VM_ID}.qcow2

sudo qemu-img resize /var/lib/hackme-vms/images/${VM_ID}.qcow2 ${DISK_SIZE}
```

---

# Part D — Cloud-init

## D1. user-data 範本

請建立 `/var/lib/hackme-vms/templates/user-data.tpl`：

```yaml
#cloud-config
hostname: ${VM_HOSTNAME}
manage_etc_hosts: true

users:
  - name: ${VM_USERNAME}
    groups: sudo
    shell: /bin/bash
    sudo: ['ALL=(ALL) NOPASSWD:ALL']
    lock_passwd: true
    ssh_authorized_keys:
      - ${SSH_PUBLIC_KEY}

ssh_pwauth: false
disable_root: false

package_update: true
packages:
  - curl
  - wget
  - git
  - vim
  - htop
  - tmux
  - ca-certificates
  - ufw

runcmd:
  - ufw default deny incoming
  - ufw default allow outgoing
  - ufw allow 22/tcp
  - ufw --force enable
  - echo "hackme_web sandbox VM initialized" > /etc/motd
```

安全要求：

```text
1. 預設關閉 SSH 密碼登入。
2. 只允許 SSH key 登入。
3. 使用者可在 VM 內 sudo/root。
4. 不注入 hackme_web 任何 secret。
5. 不掛載主系統目錄。
```

---

## D2. meta-data 範本

```yaml
instance-id: ${VM_ID}
local-hostname: ${VM_HOSTNAME}
```

---

## D3. network-config 範本

MVP 可先使用 DHCP：

```yaml
version: 2
ethernets:
  ens3:
    dhcp4: true
```

---

## D4. 建立 seed ISO

```bash
VM_ID="sandbox-test-001"

sudo mkdir -p /var/lib/hackme-vms/seed/${VM_ID}

sudo cloud-localds \
  /var/lib/hackme-vms/seed/${VM_ID}/seed.iso \
  /var/lib/hackme-vms/seed/${VM_ID}/user-data \
  /var/lib/hackme-vms/seed/${VM_ID}/meta-data
```

若使用 network-config：

```bash
sudo cloud-localds \
  --network-config=/var/lib/hackme-vms/seed/${VM_ID}/network-config \
  /var/lib/hackme-vms/seed/${VM_ID}/seed.iso \
  /var/lib/hackme-vms/seed/${VM_ID}/user-data \
  /var/lib/hackme-vms/seed/${VM_ID}/meta-data
```

---

# Part E — 建立 VM

## E1. virt-install 範例

```bash
VM_ID="sandbox-test-001"

sudo virt-install \
  --name ${VM_ID} \
  --memory 2048 \
  --vcpus 2 \
  --cpu host \
  --import \
  --disk path=/var/lib/hackme-vms/images/${VM_ID}.qcow2,format=qcow2,bus=virtio \
  --disk path=/var/lib/hackme-vms/seed/${VM_ID}/seed.iso,device=cdrom \
  --os-variant ubuntu22.04 \
  --network network=default,model=virtio \
  --graphics none \
  --console pty,target_type=serial \
  --noautoconsole
```

---

## E2. VM 管理命令

```bash
virsh -c qemu:///system list --all
virsh -c qemu:///system dominfo sandbox-test-001
virsh -c qemu:///system domifaddr sandbox-test-001
virsh -c qemu:///system shutdown sandbox-test-001
virsh -c qemu:///system destroy sandbox-test-001
virsh -c qemu:///system suspend sandbox-test-001
virsh -c qemu:///system resume sandbox-test-001
virsh -c qemu:///system undefine sandbox-test-001 --remove-all-storage
```

---

# Part F — hackme_web 系統設計

## F1. 模組名稱

新增：

```text
ServerRentalService
LibvirtProvider
SandboxProvisioner
SandboxBillingService
SandboxAuditService
```

---

## F2. 使用者流程

```text
1. 使用者進入 /server-rental
2. 選擇方案
3. 輸入或上傳 SSH public key
4. 系統顯示價格與租期
5. 使用者確認
6. PointsLedgerService.debit() 扣點或建立訂閱
7. 建立 sandbox_servers 記錄
8. LibvirtProvider 建立 VM
9. 注入 cloud-init
10. 啟動 VM
11. 回傳 SSH 連線資訊
12. 使用者登入 VM 使用
13. 到期自動 suspend
14. 寬限期後 delete
```

---

## F3. Root 回收權

root 必須能：

```text
1. 強制 suspend VM
2. 強制 shutdown VM
3. 強制 destroy VM
4. delete VM and disk
5. revoke subscription
6. freeze user rental
7. 查看資源用量
8. 查看 audit log
9. 建立 snapshot
10. rollback snapshot
11. block network
```

---

# Part G — 資料表設計

## G1. sandbox_plans

```sql
CREATE TABLE sandbox_plans (
  id BIGSERIAL PRIMARY KEY,

  plan_code VARCHAR(80) NOT NULL UNIQUE,
  name VARCHAR(120) NOT NULL,

  vcpus INT NOT NULL,
  memory_mb INT NOT NULL,
  disk_gb INT NOT NULL,

  os_image VARCHAR(120) NOT NULL DEFAULT 'ubuntu-22.04',

  duration_hours INT NOT NULL,
  price_points BIGINT NOT NULL,
  currency_type VARCHAR(20) NOT NULL DEFAULT 'hard',

  max_instances_per_user INT NOT NULL DEFAULT 1,

  enabled BOOLEAN NOT NULL DEFAULT TRUE,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (vcpus >= 1),
  CHECK (memory_mb >= 512),
  CHECK (disk_gb >= 5),
  CHECK (price_points >= 0)
);
```

---

## G2. sandbox_servers

```sql
CREATE TABLE sandbox_servers (
  id BIGSERIAL PRIMARY KEY,
  server_uuid UUID NOT NULL UNIQUE,

  user_id BIGINT NOT NULL,

  plan_id BIGINT NOT NULL,
  vm_name VARCHAR(160) NOT NULL UNIQUE,

  provider VARCHAR(50) NOT NULL DEFAULT 'libvirt',
  libvirt_uri VARCHAR(120) NOT NULL DEFAULT 'qemu:///system',

  os_image VARCHAR(120) NOT NULL DEFAULT 'ubuntu-22.04',

  status VARCHAR(40) NOT NULL DEFAULT 'provisioning',

  vcpus INT NOT NULL,
  memory_mb INT NOT NULL,
  disk_gb INT NOT NULL,

  ssh_username VARCHAR(80) NOT NULL DEFAULT 'ubuntu',
  ssh_public_key_fingerprint CHAR(64),
  ssh_host VARCHAR(160),
  ssh_port INT DEFAULT 22,

  internal_ip VARCHAR(80),
  external_ip VARCHAR(80),

  disk_path TEXT,
  seed_iso_path TEXT,

  debit_ledger_uuid UUID,

  started_at TIMESTAMP,
  expires_at TIMESTAMP NOT NULL,
  suspended_at TIMESTAMP,
  deleted_at TIMESTAMP,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (status IN (
    'provisioning',
    'running',
    'stopped',
    'suspended',
    'expired',
    'deleting',
    'deleted',
    'failed',
    'revoked'
  ))
);
```

---

## G3. sandbox_actions

```sql
CREATE TABLE sandbox_actions (
  id BIGSERIAL PRIMARY KEY,

  server_id BIGINT NOT NULL,
  actor_user_id BIGINT,
  actor_role VARCHAR(50),

  action_type VARCHAR(80) NOT NULL,
  status VARCHAR(40) NOT NULL DEFAULT 'pending',

  message TEXT,
  metadata_json TEXT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP
);
```

---

## G4. sandbox_resource_usage

```sql
CREATE TABLE sandbox_resource_usage (
  id BIGSERIAL PRIMARY KEY,

  server_id BIGINT NOT NULL,

  cpu_seconds BIGINT DEFAULT 0,
  memory_current_mb INT,
  disk_used_gb INT,
  network_rx_bytes BIGINT DEFAULT 0,
  network_tx_bytes BIGINT DEFAULT 0,

  collected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

# Part H — API 設計

## H1. User API

```http
GET  /api/server-rental/plans
POST /api/server-rental/quote
POST /api/server-rental/servers
GET  /api/server-rental/servers
GET  /api/server-rental/servers/:server_uuid
POST /api/server-rental/servers/:server_uuid/renew
POST /api/server-rental/servers/:server_uuid/stop
POST /api/server-rental/servers/:server_uuid/start
POST /api/server-rental/servers/:server_uuid/delete
GET  /api/server-rental/servers/:server_uuid/connection
```

限制：

```text
1. user 只能看到自己的 server。
2. user 不能更改 vCPU/RAM/Disk 超過 plan。
3. user 不能指定 arbitrary libvirt XML。
4. user 不能指定任意 disk path。
5. user 不能選擇未開放 image。
```

---

## H2. Admin / Root API

```http
GET  /api/admin/server-rental/servers
GET  /api/admin/server-rental/servers/:server_uuid
POST /api/admin/server-rental/servers/:server_uuid/suspend
POST /api/admin/server-rental/servers/:server_uuid/resume
POST /api/admin/server-rental/servers/:server_uuid/shutdown
POST /api/admin/server-rental/servers/:server_uuid/revoke
POST /api/admin/server-rental/servers/:server_uuid/delete
GET  /api/admin/server-rental/resource-usage
```

Root-only：

```http
POST /api/root/server-rental/plans
PUT  /api/root/server-rental/plans/:id
POST /api/root/server-rental/host/health-check
POST /api/root/server-rental/host/sync-libvirt
POST /api/root/server-rental/servers/:server_uuid/force-destroy
```

---

# Part I — LibvirtProvider 需求

請實作 LibvirtProvider，封裝所有 virsh / libvirt 操作。

建議方法：

```text
check_host()
list_domains()
create_vm(server)
start_vm(vm_name)
shutdown_vm(vm_name)
destroy_vm(vm_name)
suspend_vm(vm_name)
resume_vm(vm_name)
delete_vm(vm_name, remove_storage=True)
get_ip(vm_name)
get_stats(vm_name)
create_snapshot(vm_name)
rollback_snapshot(vm_name, snapshot_name)
```

實作方式可選：

```text
1. Python libvirt binding
2. subprocess 呼叫 virsh / virt-install
```

MVP 可先用 subprocess，但必須：

```text
1. 不拼接未清理 shell 字串。
2. 使用 argument list。
3. 嚴格驗證 vm_name。
4. 所有命令寫 log。
5. timeout。
6. 捕捉 stderr。
```

---

# Part J — VM 命名規則

VM 名稱必須可控：

```text
hackme-sbx-u{user_id}-{short_uuid}
```

範例：

```text
hackme-sbx-u104-a1b2c3d4
```

禁止使用：

```text
使用者自訂 VM 名稱
空白
斜線
shell metacharacters
過長名稱
```

---

# Part K — 網路隔離

## K1. MVP NAT 模式

使用 libvirt default NAT network。

優點：

```text
簡單
VM 可出網
外部不能直接連 VM
```

問題：

```text
使用者 SSH 連線需要 port forwarding、VPN、web terminal，或 admin 查 IP 後內網連線。
```

---

## K2. 建議正式模式

三種選擇：

### 選項 A：Port Forwarding

每台 VM 分配一個 host port：

```text
host:22001 → vm:22
host:22002 → vm:22
```

### 選項 B：WireGuard VPN

使用者先進 VPN，再 SSH 進內網 VM。

### 選項 C：Web SSH Console

hackme_web 提供 Web terminal proxy。

MVP 建議：

```text
先做 host port forwarding 或僅 root/admin 測試內網 SSH。
正式再做 WireGuard / Web SSH。
```

---

## K3. 禁止 VM 存取主站內網

必須設計防火牆規則，阻止 VM 連到：

```text
hackme_web DB
hackme_web admin API
宿主機管理 port
libvirt socket
Redis
內部 object storage
ComfyUI 管理 port
```

建議：

```text
1. VM network 與 app network 分離。
2. 宿主機用 nftables/iptables 阻擋 VM subnet 到內部服務。
3. 只允許 VM 出網到 Internet。
4. 如需 callback，使用受控 API gateway。
```

---

# Part L — 訂閱與扣費

## L1. 扣費策略

MVP：

```text
建立 VM 前一次性扣除整個租期點數。
```

流程：

```text
1. 使用者選 plan。
2. 系統 quote。
3. 檢查餘額。
4. PointsLedgerService.debit()
5. 建立 VM。
6. VM 建立失敗則 refund/reversal。
```

action_type：

```text
server_rental_debit
server_rental_refund
server_rental_renew_debit
```

reference_type：

```text
sandbox_server
```

reference_id：

```text
server_uuid
```

---

## L2. 到期流程

背景 job 每分鐘或每 5 分鐘檢查：

```text
expires_at < now AND status = running
→ virsh suspend/shutdown
→ status = expired/suspended
→ audit log
```

寬限期後：

```text
expired > grace_period
→ delete VM and disk
→ status = deleted
```

建議 grace period：

```text
24 小時或 72 小時，由 root 設定。
```

---

# Part M — UI 要求

## M1. User UI

路由：

```text
/server-rental
/server-rental/servers
/server-rental/servers/:server_uuid
```

頁面顯示：

```text
方案列表
CPU/RAM/Disk/租期/價格
SSH key 輸入
預估費用
確認建立
我的伺服器列表
狀態
到期時間
連線資訊
續租
停止
啟動
刪除
```

---

## M2. Admin / Root UI

```text
所有 VM 列表
依 user 查詢
狀態
資源使用
到期時間
強制 suspend
強制 shutdown
強制 delete
資源不足警示
libvirt host health
```

---

# Part N — 安全限制

必須做到：

```text
1. 不允許使用者提供 libvirt XML。
2. 不允許使用者提供 disk path。
3. 不允許使用者自訂 cloud-init 任意內容。
4. 不允許使用者掛載 host path。
5. 不允許 privileged container。
6. 不允許 VM 存取 libvirt socket。
7. 不允許 VM 存取 hackme_web secrets。
8. 不允許 VM 存取主資料庫。
9. 不允許 VM 任意開 public port，除非 root 開放。
10. 建立/刪除/暫停都必須 audit log。
```

---

# Part O — 風控與資源管理

## O1. Host capacity check

建立 VM 前檢查：

```text
可用 vCPU
可用 RAM
可用 disk
目前 running VM 數
使用者現有 VM 數
```

若不足：

```text
不扣點
顯示資源不足
```

---

## O2. 每人限制

```text
Starter：最多 1 台
Dev：最多 2 台
高階方案：root 設定
```

---

## O3. 違規處理

root/admin 可：

```text
suspend
shutdown
revoke
delete
block renew
freeze subscription
```

所有處置要寫 sandbox_actions。

---

# Part P — 測試要求

必測：

```text
1. host kvm check 正常。
2. libvirt 連線正常。
3. plan quote 正確。
4. 餘額不足不能建立。
5. 扣點成功後建立 VM。
6. VM 建立失敗會退款。
7. cloud-init SSH key 可登入。
8. 使用者只能看自己的 VM。
9. 使用者不能操作別人的 VM。
10. 到期會 suspend。
11. 寬限期後會 delete。
12. root 可強制 shutdown/delete。
13. VM 名稱不能注入 shell。
14. disk path 不能被使用者控制。
15. VM 不能連到主資料庫。
16. audit log 完整。
```

---

# Part Q — 管理命令

若 hackme_web 有 manage.py，實作：

```bash
python manage.py sandbox host-check
python manage.py sandbox sync-libvirt
python manage.py sandbox create --user-id <id> --plan <plan_code> --ssh-key <path>
python manage.py sandbox suspend <server_uuid>
python manage.py sandbox shutdown <server_uuid>
python manage.py sandbox delete <server_uuid>
python manage.py sandbox expire-check
python manage.py sandbox usage-collect
```

若不是 Python，請用現有技術棧建立等效 CLI。

---

# Part R — 系統健康檢查

必須檢查：

```text
KVM acceleration
libvirtd running
default network active
base image exists
storage dir writable
seed dir writable
available memory
available disk
virsh command available
virt-install command available
cloud-localds available
```

輸出：

```json
{
  "kvm": true,
  "libvirt": true,
  "default_network": true,
  "base_image": true,
  "storage_writable": true,
  "available_memory_mb": 32768,
  "available_disk_gb": 500
}
```

---

# Part S — MVP 建議方案

預設建立三個方案：

```text
sandbox_starter_1d
- Ubuntu 22.04
- 1 vCPU
- 1GB RAM
- 10GB disk
- 24 hours

sandbox_dev_7d
- Ubuntu 22.04
- 2 vCPU
- 4GB RAM
- 40GB disk
- 7 days

sandbox_dev_30d
- Ubuntu 22.04
- 2 vCPU
- 4GB RAM
- 40GB disk
- 30 days
```

GPU 方案不要放在 MVP。

---

# Part T — 文件要求

新增：

```text
docs/server_rental_libvirt_design.md
docs/server_rental_security_model.md
docs/server_rental_operations_runbook.md
docs/server_rental_user_guide.md
docs/server_rental_admin_guide.md
```

README 補充：

```text
宿主機依賴
libvirt 安裝
base image 準備
sandbox plans
安全限制
MVP 限制
```

---

# Part U — 完成後回報格式

請用以下格式回報：

```text
# libvirt Server Rental 完成摘要

## 已完成
-

## 宿主機依賴
-

## 新增資料表
-

## 新增 Service
-

## 新增 API
-

## 新增 UI
-

## libvirt 測試
-

## 扣費 / 退款
-

## 到期回收
-

## 安全隔離
-

## 尚未完成
-

## 需要 root 人工確認
-

## 建議下一階段
-
```

---

# Part V — 最高提醒

這不是一般 Docker 沙盒，而是付費 / 積分租借 VM。

最高原則：

```text
使用者可以控制 VM 內環境
但不能碰宿主機
不能碰 hackme_web 主系統
不能碰主資料庫
不能繞過扣費
不能保留到期資源
root 必須永遠能回收
```
