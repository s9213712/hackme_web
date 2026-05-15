# ComfyUI Template Importer — 規格

> **狀態**：Implemented MVP — preview/import/run gate 已落地；本文件保留原始規格與後續 phase 記錄
>
> **作者**：claude (Opus 4.7) · 2026-05-07
>
> **主要落地範圍**：`services/comfyui/template/`、`routes/comfyui_sections/template_routes.py`、`routes/comfyui_sections/workflow_routes.py`
>
> **目的**：讓使用者上傳 ComfyUI workflow JSON，經**解析 → 能力比對 → 安全審查 → 輸入欄位映射 → 預覽確認 → 才能執行**，避免任意 JSON 直接 queue 進 ComfyUI 造成 RCE / 路徑穿越 / 模型 misuse。

---

## 0. TL;DR

目前已完成：

- `POST /api/comfyui/templates/preview`：接受 JSON body、`workflow_text`、multipart JSON 檔，並產生 single-use `preview_token`。
- Preview 階段會執行 normalize → sanitize → analyze → explicit denylist → capability → UI schema。
- `POST /api/comfyui/templates/import`：消耗 `preview_token`，重新 sanitize/analyze/capability 後寫入 workflow preset 與 runtime template bundle。
- `POST /api/comfyui/workflows/<id>/run`：在 strict flag 啟用時走 5-gate enforcement，失敗會回 stage-tagged error 並寫 audit。
- ComfyUI UI graph export (`nodes` / `links`) 已支援在 preview 階段轉換成 API prompt format；run gate 仍只接受已正規化後的 API-format workflow。

仍列為後續 phase：

- IPAdapter / FaceDetailer / ReActor / video workflows 仍拒絕。
- 任意 custom node 仍必須經 allowlist / capability gate，不直接放行。
- 多輸出分支雖可被安全改寫 `SaveImage.filename_prefix`，但產品 UI/UX 與輸出管理仍需單獨驗收後才視為正式支援。

| 階段 | 動作 | 安全角色 |
|---|---|---|
| 1. Upload | `POST /api/comfyui/templates/preview` | 只解析 + 分析，**不執行** |
| 2. Analyze | 後端產生 `WorkflowAnalysis` + `CapabilityCheck` + `UISchema` | 給 frontend 展示用 |
| 3. Confirm | 使用者填欄位 + 按確認 | frontend 互動 |
| 4. Import | `POST /api/comfyui/workflows/import` 帶 `preview_token` | 存 DB（仍未執行） |
| 5. Run | `POST /api/comfyui/workflows/<id>/run` | 5-gate 強制檢查才送 ComfyUI |

任何一個 gate fail → 400 + 操作者可讀的繁中錯誤訊息（永不 silent fallback）。

---

## 1. 既有資產盤點（避免重做）

`services/comfyui/` 已有 30% 骨架：

| 模組 | 既有功能 | 本 plan 需要它 |
|---|---|---|
| [`client.py:135 get_object_info()`](../../services/comfyui/client.py) | wrap `/object_info` REST 呼叫 | 直接用做能力偵測 |
| [`validation/sanitize.py:79 sanitize_workflow_json()`](../../services/comfyui/validation/sanitize.py) | 路徑穿越 / 絕對路徑 / URL / 命令片段全擋 + 大小上限 | 第一道 syntactic 過濾，**不變動** |
| [`validation/rules.py`](../../services/comfyui/validation/rules.py) `WORKFLOW_BLOCKED_*_RE` | regex blocklist | **要補上 explicit allowlist**（更嚴）|
| [`workflow/summary.py:206`](../../services/comfyui/workflow/summary.py) `required_models / loras / controlnets` | 已抽出模型需求清單 | Analyzer 沿用，不重做 |
| [`workflow/builder.py`](../../services/comfyui/workflow/builder.py) text2img / img2img / inpaint base | hardcoded `next_node_id = 10` | **要先 refactor 成 allocator** 才能在它上面疊 importer |
| [`POST /api/comfyui/workflows/import`](../../routes/comfyui.py) | 已存在但只 sanitize + 存 DB | 改造：要求帶 `preview_token` |
| [`POST /api/comfyui/workflows/<id>/run`](../../routes/comfyui.py) | 已存在 | 加 5-gate enforcement |
| `services/comfyui/execution.py:queue_prompt()` | 送 prompt 到 ComfyUI | 不動 |

---

## 2. 支援範圍

### 2.1 第一版 IN（MVP）

| 模式 | 必要節點 | 第一版策略 |
|---|---|---|
| **txt2img** | `CheckpointLoaderSimple` + `CLIPTextEncode` × 2（pos / neg）+ `EmptyLatentImage` + `KSampler` + `VAEDecode` + `SaveImage` | 全 |
| **img2img** | 同上 + `LoadImage` + `VAEEncode` | 全 |
| **inpaint** | 同上 + `LoadImage` × 2（image + mask 或 `LoadImageMask`）+ `VAEEncodeForInpaint` | 全 |
| **outpaint** | 同 inpaint + `ImagePadForOutpaint` | 全 |
| **upscale** | `LoadImage` + `UpscaleModelLoader` + `ImageUpscaleWithModel` + `SaveImage` | 全 |
| **LoRA stack** | `LoraLoader` × N | N ≤ 4 |
| **VAE override** | `VAELoader` × 1 | 全 |
| **ControlNet** | `ControlNetLoader` + `ControlNetApplyAdvanced` + (相應 preprocessor) | **單組**（multi-stack 第二版才開）|

### 2.2 第一版 OUT（明確不支援）

| 不支援 | 理由 |
|---|---|
| **AnimateDiff** workflow | 動態長度 / 多輸出，第一版安全表面太大 |
| **IPAdapter** | 牽涉 image embedding 路徑映射，需要獨立 phase |
| **FaceDetailer / Detailer Pipe** | 多階段內部 pipeline，failure mode 不可預測 |
| **ReActor / face swap** | 隱私 / 法律邊界模糊 |
| **Video workflow**（任何輸出 video 的）| 大量 disk 空間 + 編碼複雜度 |
| **多輸出分支**（>1 個 `SaveImage`）| 後端會安全改寫所有 `SaveImage.filename_prefix`，但輸出管理 UX 尚未列為正式支援 |
| **任意 custom node** | 沒在 allowlist → 拒絕（即使 analyze 看得出意圖也不放行）|
| **ComfyUI UI graph format**（`nodes:[...]` + `links:[...]`）| Preview/import 已支援正規化；run gate 仍只收正規化後的 API format |
| **巢狀 group node** | 第一版攤平；若無法攤平則拒絕 |

### 2.3 第二版以後再開（記錄即可）

- ControlNet 多組 stacking
- IPAdapter
- FaceDetailer
- 多輸出分支 UI/輸出管理驗收

---

## 3. Workflow JSON 格式要求

### 3.1 只接受 ComfyUI API prompt format

> **目前範圍宣告**：run gate 與 DB 內部只保存 *ComfyUI API prompt format*，目標是
> 「能被 ComfyUI API queue 安全執行」。Preview/import 入口可接受常見 ComfyUI UI graph
> export，會先轉成 API prompt format 再進 sanitize/analyze/capability pipeline。
> 不保證匯出後可直接在 ComfyUI 前端 UI 完整還原原始節點位置 / 群組 / widget metadata。

合法形狀（API format）：

```json
{
  "4": {
    "class_type": "CheckpointLoaderSimple",
    "inputs": { "ckpt_name": "v1-5-pruned.safetensors" }
  },
  "6": {
    "class_type": "CLIPTextEncode",
    "inputs": { "text": "a cat", "clip": ["4", 1] }
  },
  ...
}
```

### 3.2 拒收的常見變形

| 形狀 | 拒收原因 |
|---|---|
| `{"nodes": [...], "links": [...]}`（含 `pos`、`size`、`widgets_values` 等 UI 欄位）| ComfyUI **UI graph format**；preview/import 會嘗試轉成 API format。若缺少可轉換節點或 links 形狀錯誤，回 `normalize` stage 錯誤。|
| `{"prompt": {...}, "extra_data": {...}}` | ComfyUI **export-with-metadata** 包裹格式；preview/import 會 unwrap 內層 `prompt`。|
| Top-level array | 不是 dict |
| 包含 `client_id` / `prompt_id` / `extra_pnginfo` 等執行時 metadata | 拒收（暗示是執行記錄）|

> **參考範例**：`docs/comfyui/Unsaved Workflow.json` 是 ComfyUI 前端 editor 直接 Save
> 出來的範例（UI graph format，非 API format）— 包含 `nodes:[...]`、`links:[...]`、
> `pos`、`widgets_values` 等 UI 欄位。preview/import 可以轉換這種格式；run gate
> 仍拒絕未正規化的 UI graph，避免任何執行路徑繞過 sanitize。

### 3.3 大小限制（直接沿用 [`validation/rules.py`](../../services/comfyui/validation/rules.py)）

| 限制 | 值 | 來源 |
|---|---:|---|
| `WORKFLOW_MAX_JSON_BYTES` | 256,000 | rules.py 既有 |
| `WORKFLOW_MAX_NODE_COUNT` | 200 | rules.py 既有 |
| `WORKFLOW_MAX_NESTING_DEPTH` | 10 | rules.py 既有 |
| **MVP 額外**：node count 上限 | **50** | 第一版更嚴；複雜 workflow 等第二版 |
| **MVP 額外**：LoRA 堆疊上限 | **4** | 避免 OOM |
| **MVP 額外**：每 `CLIPTextEncode.text` 最大字元 | **2,000** | prompt 不該到萬字 |

---

## 4. 節點 Allowlist

**設計原則**：allowlist > blocklist。三類處置：

| 類別 | Preview (`/templates/preview`) | Import (`/workflows/import`) | Run (`/workflows/<id>/run`) |
|---|---|---|---|
| **Explicit blocklist 命中**（§4.3，例：`*Eval*` / `*Shell*` / ReActor / AnimateDiff …） | 直接 fail | n/a（preview 已擋） | n/a（preview 已擋） |
| **Allowlist 命中**（§4.1） | OK | OK，前提 capability check passed | 重新 enforce_allowlist + capability check |
| **Unknown class（既非 allow 也非 block）** | OK 但 `capability.overall = "UNSUPPORTED"`，附 `unknown_classes:[...]` | **拒絕**（不允許 import unsupported workflow） | n/a（import 已擋） |

說明：

- Preview 階段對 unknown class **不直接 fail**，是為了讓 user 看到完整 analysis（哪些 node、哪些缺）才能決定要不要拆掉那些節點重做；但 capability 直接標 `UNSUPPORTED`，frontend 必須禁用 import / run 按鈕。
- Import / Run 一律 strict：只接 `SUPPORTED` 或 explicitly-allowed `PARTIALLY_SUPPORTED`。
- Run 階段**永不**信任 import 時的判定 — 一律 re-analyze + re-enforce + re-capability，避免 import 後本地 ComfyUI 規格被改、custom node 被換、allowlist 收緊等漂移情境。

### 4.1 Core MVP allowlist（17 個 class_type）

```python
# services/comfyui/template/allowlist.py
CORE_ALLOWLIST = frozenset({
    # Loaders
    "CheckpointLoaderSimple",
    "VAELoader",
    "LoraLoader",
    "ControlNetLoader",
    "UpscaleModelLoader",
    # Inputs
    "LoadImage",
    "LoadImageMask",
    "EmptyLatentImage",
    # Encoders
    "CLIPTextEncode",
    "VAEEncode",
    "VAEEncodeForInpaint",
    # Sampling
    "KSampler",
    # Decoders
    "VAEDecode",
    # ControlNet apply
    "ControlNetApplyAdvanced",
    # Outpaint helper
    "ImagePadForOutpaint",
    # Upscale apply
    "ImageUpscaleWithModel",
    # Save
    "SaveImage",
})
```

### 4.2 ControlNet preprocessor allowlist

依 `services/comfyui/constants.py:CONTROLNET_TYPE_DEFINITIONS`，allowlist 沿用：

- `CannyEdgePreprocessor`
- `DepthAnythingPreprocessor` / `MiDaS-DepthMapPreprocessor`
- `OpenposePreprocessor` / `DWPreprocessor`
- `LineArtPreprocessor` / `LineartStandardPreprocessor`
- `PiDiNetPreprocessor` / `ScribblePreprocessor`
- `SoftEdgePreprocessor` / `HEDPreprocessor`
- 其餘 type 視 `constants.py` 定義同步擴充

### 4.3 拒絕的常見 class（明確列）

避免「以為 allowlist 就 OK」的盲點，明文拒：

| class_type | 拒因 |
|---|---|
| `*Eval*` / `*Exec*` / `*Shell*` / `*Subprocess*` / `*Python*` | regex 已擋（`WORKFLOW_BLOCKED_CLASS_RE`），**不撤防** |
| `HTTPRequest*` / `*WebSocket*` / `DownloadURL*` | 擋外部請求 |
| `RunCode*` / `EvalString*` | 任意代碼執行 |
| `LoadDirectory*` | 列目錄 |
| `*Save*` 但不是 `SaveImage` | filename / 路徑風險 |

### 4.4 Allowlist 擴充流程

加入新 class **必須**：

1. 寫一個 fixture workflow JSON 包含該 class
2. 寫一個 negative test 證明缺它時 analyze 仍 OK 但 execute 被擋
3. 在 `docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md` §4 補入並寫退出條件
4. 同 commit 加進 `CORE_ALLOWLIST` + 對應 unit test

---

## 5. 輸入欄位分類規則

### 5.1 分類

```python
# services/comfyui/template/analyzer.py
class FieldCategory(str, Enum):
    TEXT = "TEXT"            # CLIPTextEncode.text 等
    IMAGE = "IMAGE"          # LoadImage.image 等
    MODEL = "MODEL"          # ckpt_name / vae_name / lora_name / control_net_name / model_name
    NUMERIC = "NUMERIC"      # KSampler.seed / steps / cfg / denoise
    SAMPLER = "SAMPLER"      # KSampler.sampler_name / scheduler
    UNKNOWN = "UNKNOWN"      # not classifiable
```

### 5.2 分類對應表

| class_type | input field | category | UI hint |
|---|---|---|---|
| `CLIPTextEncode` | `text` | TEXT | textarea，字數上限 2000 |
| `LoadImage` | `image` | IMAGE | hackme_web cloud_drive picker |
| `LoadImageMask` | `image` | IMAGE | 同上，遮罩用 |
| `LoadImageMask` | `channel` | TEXT (enum) | dropdown: alpha / red / green / blue |
| `CheckpointLoaderSimple` | `ckpt_name` | MODEL | 從 ComfyUI `/object_info` 拉選單 |
| `VAELoader` | `vae_name` | MODEL | 同上 |
| `LoraLoader` | `lora_name` | MODEL | 同上 |
| `LoraLoader` | `strength_model`, `strength_clip` | NUMERIC | slider 0.0 - 2.0 |
| `ControlNetLoader` | `control_net_name` | MODEL | 同上 |
| `UpscaleModelLoader` | `model_name` | MODEL | 同上 |
| `KSampler` | `seed` | NUMERIC | int64，「隨機」按鈕生成 -1 → 後端自動換成 random |
| `KSampler` | `steps` | NUMERIC | int 1-150，預設 20 |
| `KSampler` | `cfg` | NUMERIC | float 1.0-30.0，預設 7.0 |
| `KSampler` | `denoise` | NUMERIC | float 0.0-1.0 |
| `KSampler` | `sampler_name` | SAMPLER | 從 `/object_info/KSampler` 拉 enum |
| `KSampler` | `scheduler` | SAMPLER | 同上 |
| `EmptyLatentImage` | `width`, `height` | NUMERIC | int 64-2048，step 8 |
| `EmptyLatentImage` | `batch_size` | NUMERIC | int 1-4 |
| `SaveImage` | `filename_prefix` | — | **強制改寫**（見 §7.2）；不顯示給 user |
| `ImagePadForOutpaint` | `left`, `top`, `right`, `bottom` | NUMERIC | int 0-1024 |
| `ImagePadForOutpaint` | `feathering` | NUMERIC | int 0-100 |

### 5.3 哪些算 user-input、哪些不是

- **`is_user_input=True`**：值要在 UI 顯示讓使用者填或調整
- **`is_user_input=False`**：保持 workflow 原值，**不在 UI 顯示**（例：`KSampler.model = ["4", 0]` 是 graph 連線，不是 user 設定）

判斷規則：

| field 形狀 | is_user_input |
|---|:--:|
| `[node_id, output_idx]`（list）| ❌ 是 graph edge |
| 純字串 / 數字 / boolean | ✅ |
| 其他類型 | ❌（拒絕分類）|

---

## 6. 本地 ComfyUI 能力偵測流程

### 6.1 流程

```
analyze_workflow_json(workflow)
    └─> WorkflowAnalysis (class_types, model requirements, ...)
        └─> check_workflow_capability(analysis, client)
            ├─ client.get_object_info()  # cached 5min
            ├─ for each class_type in analysis.class_types:
            │     if class_type not in object_info: → unsupported
            │     else: check inputs alignment
            ├─ for each model requirement:
            │     query /object_info/<loader>.input_types  # has options list
            │     if requested model not in options: → missing_models
            └─ return CapabilityCheck
```

### 6.2 Cache 策略

`client.get_object_info()` 結果在 process-local 變數 cache **5 分鐘**。原因：

- ComfyUI 重啟才會變
- 每次 import 都拉一次過慢（單次 ~2-5MB JSON）
- 若 user 同時動 100 個 workflow，cache 救命

```python
# services/comfyui/client.py
_OBJECT_INFO_CACHE = {"data": None, "fetched_at": 0.0}
_OBJECT_INFO_TTL_SECONDS = 300

def get_object_info_cached(self):
    import time
    now = time.time()
    if _OBJECT_INFO_CACHE["data"] and (now - _OBJECT_INFO_CACHE["fetched_at"]) < _OBJECT_INFO_TTL_SECONDS:
        return _OBJECT_INFO_CACHE["data"]
    data = self.get_object_info()
    _OBJECT_INFO_CACHE.update(data=data, fetched_at=now)
    return data
```

### 6.3 三級結果

```python
@dataclass
class CapabilityCheck:
    supported: list[str]                       # class_types in both
    partial: list[tuple[str, str]]             # (class_type, reason) — class 在但 input 不對
    unsupported: list[str]                     # class_types missing locally
    missing_models: dict[str, list[str]]       # 'ckpt' → ['v1-5.safetensors', ...]
    sampler_options: dict[str, list[str]]      # 'KSampler.sampler_name' → ['euler', 'dpmpp_2m', ...]
    overall: Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED"]
    blockers: list[str]                        # human-readable 中文說明，UI 直接顯示
```

`overall` 計算規則：

- `UNSUPPORTED`：任一 class 不在本地 → 整 workflow block
- `PARTIALLY_SUPPORTED`：class 全在，但有 missing_models → 警告但允許繼續（user 要先下載模型）
- `SUPPORTED`：class 全在 + 模型全在

---

## 7. 安全強化（4 個 hard-block）

### 7.1 Allowlist enforcement（execute time）

```python
def enforce_allowlist(analysis: WorkflowAnalysis) -> None:
    not_allowed = set(analysis.class_types) - CORE_ALLOWLIST - CONTROLNET_PREPROCESSOR_ALLOWLIST
    if not_allowed:
        raise SafetyError(
            f"workflow 含未授權的節點類型：{sorted(not_allowed)}。"
            f"第一版只支援 17 種核心節點 + ControlNet 標準 preprocessor。"
            f"完整清單見 docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md §4。"
        )
```

**規則**：分析（`/templates/preview`）允許 unknown；執行（`/run`）強制 allowlist。

### 7.2 `SaveImage.filename_prefix` 強制改寫

```python
def rewrite_save_image_prefix(workflow: dict, *, user_id: int, run_id: str) -> dict:
    new_wf = copy.deepcopy(workflow)
    for node_id, node in new_wf.items():
        if node.get("class_type") != "SaveImage":
            continue
        node.setdefault("inputs", {})["filename_prefix"] = f"hackme_web/{user_id}/{run_id}"
    return new_wf
```

**永不**信任 user 提供的 `filename_prefix` — 一律改寫。即使 user 沒給，後端也補一個。

### 7.3 `LoadImage.image` 路徑映射到 hackme_web

```python
def remap_load_image_to_cloud_file(
    workflow: dict, *,
    image_field_assignments: dict[str, int],   # node_id → cloud_file_id
    actor: dict,
    conn,
    run_id: str,
) -> dict:
    new_wf = copy.deepcopy(workflow)
    for node_id, cloud_file_id in image_field_assignments.items():
        node = new_wf.get(node_id)
        if not node or node.get("class_type") not in {"LoadImage", "LoadImageMask"}:
            raise SafetyError(f"node {node_id} 不是 LoadImage / LoadImageMask")
        # 1. 驗證 actor 擁有此 cloud_file_id
        row = conn.execute(
            """
            SELECT owner_user_id, mime_type, byte_size, scan_status, file_extension
            FROM cloud_drive_files WHERE id=? AND deleted_at IS NULL
            """,
            (cloud_file_id,),
        ).fetchone()
        if not row or int(row["owner_user_id"]) != int(actor["id"]):
            raise SafetyError(f"image 檔 {cloud_file_id} 不存在或不屬於你")
        # 2. 驗證 MIME / 副檔名 / 大小 / scan
        if str(row["mime_type"] or "").lower() not in {"image/png", "image/jpeg", "image/webp"}:
            raise SafetyError(f"image 檔 {cloud_file_id} MIME 不允許")
        if str(row["file_extension"] or "").lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise SafetyError(f"image 檔 {cloud_file_id} 副檔名不允許")
        if int(row["byte_size"] or 0) > MAX_LOAD_IMAGE_BYTES:  # 例：8 MiB
            raise SafetyError(f"image 檔 {cloud_file_id} 超過大小上限")
        # 預設只接受 scan_status="clean"。"skipped" 必須由 root 透過站內設定明確
        # 開啟 (`security.upload_scan_skip_allowed=true`) 才視為合法 — 防止未掃描
        # 圖片透過 LoadImage 餵進 ComfyUI（同於 services/security/upload_security.py
        # 的整體掃描規則）。
        allowed_scan_statuses = {"clean"}
        if upload_scan_skip_allowed():
            allowed_scan_statuses.add("skipped")
        if str(row["scan_status"] or "").lower() not in allowed_scan_statuses:
            raise SafetyError(f"image 檔 {cloud_file_id} 未通過安全掃描")
        # 3. 必要時 decode 一次確認真的是合法影像（不只是改副檔名的 zip / shellcode）
        try:
            decode_image_or_raise(load_cloud_file_bytes(cloud_file_id))
        except Exception as exc:
            raise SafetyError(f"image 檔 {cloud_file_id} 解碼失敗：{exc}")
        # 4. 把實體檔複製到 ComfyUI input/ 並用 hashed filename
        comfy_filename = f"{actor['id']}_{run_id}_{node_id}.png"
        copy_cloud_file_to_comfy_input(cloud_file_id, comfy_filename)
        node["inputs"]["image"] = comfy_filename
    return new_wf
```

**絕對**不信任 workflow 內的原始 `image` 字串 — 必須由 user 透過 UI 重新指定 cloud_file_id。
`run_id` 是必填參數，由 caller（`/run` route）每次呼叫時 mint 一個 uuid，再丟進這個函式以便 namespace ComfyUI input 檔名（避免兩個 run 撞檔名）。
不要只檢查 owner — 檔案大小、MIME、副檔名、scan 狀態、可解碼性五項都必檢。

### 7.4 Node ID 安全 allocator

```python
# 共用 helper, 也回填到 services/comfyui/workflow/builder.py
def next_safe_node_id(workflow: dict) -> int:
    used = set()
    for k in workflow.keys():
        try:
            used.add(int(k))
        except (TypeError, ValueError):
            pass
    return max(used) + 1 if used else 1
```

**Builder 重構必做**：[`builder.py`](../../services/comfyui/workflow/builder.py) 寫死 `next_node_id = 10`，importer 上傳的 workflow 若也用 `"10"` 會 collision。先把 builder 改成 allocator → 再 importer 才能保證 collision-free。

---

## 8. Preview / Dry-run gate

### 8.1 新 endpoint `POST /api/comfyui/templates/preview`

**Request**：

```json
{
  "workflow_json": "...",     // 字串或物件
  "title": "我的 inpaint 模板",
  "description": "..."
}
```

**Response（成功）**：

```json
{
  "ok": true,
  "preview_token": "tkn_AbCdEf12...",
  "preview_token_expires_at": "2026-05-07T09:30:00",
  "analysis": {
    "node_count": 12,
    "class_types": {"CheckpointLoaderSimple": 1, "CLIPTextEncode": 2, ...},
    "unknown_classes": [],
    "fields": [
      {"node_id": "6", "class_type": "CLIPTextEncode", "field_name": "text",
       "category": "TEXT", "is_user_input": true, "current_value": "a cat"},
      ...
    ],
    "image_inputs": [...],
    "model_requirements": {"checkpoint": ["v1-5.safetensors"], ...},
    "output_nodes": ["9"],
    "estimated_mode": "txt2img"
  },
  "capability": {
    "overall": "SUPPORTED",
    "supported": [...],
    "unsupported": [],
    "missing_models": {},
    "sampler_options": {"KSampler.sampler_name": ["euler", "dpmpp_2m", ...]}
  },
  "ui_schema": {
    "panels": [
      {"id": "text", "label": "文字輸入", "fields": [...]},
      {"id": "model", "label": "模型需求", "fields": [...]},
      {"id": "sampler", "label": "採樣設定", "fields": [...]},
      {"id": "image", "label": "圖片輸入", "fields": []},
      {"id": "compatibility", "label": "相容性報告", "report": "..."},
      {"id": "raw", "label": "原始 workflow", "preview_text": "..."}
    ]
  },
  "safety_report": {
    "filename_prefix_rewrite_required": true,
    "image_remap_required": false,
    "node_id_collision_risk": false,
    "warnings": []
  }
}
```

**Response（失敗 — 不通過 sanitize）**：

```json
{
  "ok": false,
  "msg": "workflow 欄位 workflow.4.inputs.ckpt_name 不可包含絕對路徑",
  "stage": "sanitize"
}
```

**Response（失敗 — 含未授權節點且不允許）**：

```json
{
  "ok": false,
  "msg": "workflow 含未授權的節點類型：['ReActorFaceSwap']。第一版不支援 face swap workflow。",
  "stage": "allowlist",
  "unknown_classes": ["ReActorFaceSwap"]
}
```

### 8.2 Preview Token

- 形狀：`tkn_<32 hex>`
- TTL：**30 分鐘**（足夠 user 在 UI 填欄位）
- Key：`(token, user_id)`
- Value：完整的 `WorkflowAnalysis` + sanitized workflow JSON

#### 8.2.1 儲存後端

| 部署型態 | 推薦儲存 | 備註 |
|---|---|---|
| **MVP（單 process / sticky session）** | process-local LRU cache | 不寫 DB；server 重啟即失效；最簡單 |
| **multi-worker（gunicorn 多 process / 多容器）** | Redis 或 DB temporary table | preview 在 worker A、import 打到 worker B 時 process-local LRU 會 miss → token 失效 |

**部署檢查**：production 若採 multi-worker（`gunicorn --workers > 1` 或多 instance/容器），**必須**改用共享儲存。實作上提供 `services/comfyui/template/preview_store.py` interface（`set/get/delete/expire`），底層第一版用 in-memory LRU，第二版加 Redis/DB 實作；route 層一律走 interface。

否則會出現 user 上傳成功、按「儲存」卻得到「驗證碼無效或已過期」這種看似 race 但實為 worker affinity 的怪 bug。

### 8.3 Frontend 流程（`public/js/36-comfyui.js`）

1. User 點「上傳模板」→ 出 modal 含拖拉 zone + 貼 JSON 區
2. Submit → `POST /api/comfyui/templates/preview`
3. 顯示 6 個面板（基本輸入 / 模型需求 / 進階參數 / 圖片輸入 / 相容性報告 / 原始 workflow）
4. **若 capability.overall = "UNSUPPORTED"**：禁止「儲存」按鈕，只允許「取消」
5. **若 PARTIALLY_SUPPORTED**：黃色警告 + 顯示需下載哪些模型；允許儲存但不允許執行
6. **若 SUPPORTED**：「儲存」按鈕 enabled
7. User fill in 必要欄位（特別是 `LoadImage.image`）
8. 確認儲存 → `POST /api/comfyui/workflows/import` 帶 `preview_token` + filled values

---

## 9. UI Schema

### 9.1 Panel 標準形狀

```json
{
  "id": "<panel_id>",
  "label": "<繁中標籤>",
  "fields": [
    {
      "id": "node:<node_id>:<field_name>",
      "category": "TEXT|IMAGE|MODEL|NUMERIC|SAMPLER",
      "label": "...",
      "input_type": "textarea|file_picker|select|number|slider",
      "required": true|false,
      "default": "...",
      "constraints": {
        "min": 0, "max": 100, "step": 1,        // numeric / slider
        "max_length": 2000,                       // text
        "options": ["..."],                       // select
        "accept_mime": ["image/*"]                // file
      },
      "current_value": "..."   // workflow 原值，用於回填
    }
  ]
}
```

### 9.2 6 個 Panel

1. **`text`** — 「文字輸入」：所有 `CLIPTextEncode.text`
2. **`image`** — 「圖片輸入」：所有 `LoadImage.image` / `LoadImageMask.image`
3. **`model`** — 「模型需求」：`ckpt_name` / `vae_name` / `lora_name[]` / `control_net_name` / `model_name`
4. **`sampler`** — 「採樣設定」：seed / steps / cfg / denoise / sampler_name / scheduler
5. **`compatibility`** — 「相容性報告」：read-only 狀態（綠 / 黃 / 紅）+ 缺失模型清單
6. **`raw`** — 「原始 workflow」：唯讀 JSON pretty-print，給 advanced user 看

UI 預設 **collapse**，user 開哪個 panel 才展。**不要**一開始就攤平。

---

## 10. 執行 gate

### 10.1 改造 `POST /api/comfyui/workflows/<id>/run`

進入點要強制 5 個 gate：

```python
@app.route("/api/comfyui/workflows/<int:preset_id>/run", methods=["POST"])
@require_csrf
def comfyui_workflow_run(preset_id):
    actor, err = _actor_or_401()
    if err: return err
    
    preset = _load_preset(...)
    user_inputs = request.get_json().get("user_inputs") or {}
    run_id = uuid.uuid4().hex
    
    # Gate 1: sanitize + normalize + analyze
    #   絕不信任 DB / 手動匯入 / 舊版本留下的 workflow_json — preview 時 sanitize 過，
    #   import 時 sanitize 過，run 時還是要再 sanitize 一次（schema 漂移 / migration
    #   bug / 直接寫 DB 都可能繞過先前 gates）。analyze 本身不擋 unknown，後面 gate 接手。
    try:
        workflow = sanitize_workflow_json(preset.workflow_json)        # path traversal / blocklist / size
        workflow = normalize_workflow_api_format(workflow)             # 確認仍為 API format（§3.1）
    except WorkflowValidationError as exc:
        return _err(str(exc), 400, stage="gate1_sanitize")
    analysis = analyze_workflow_json(workflow)
    
    # Gate 2: 能力檢查（區分「本地 ComfyUI 沒有」vs「在 hackme_web allowlist 之外」）
    cap = check_workflow_capability(analysis, client=comfyui_client)
    if cap.overall == "UNSUPPORTED":
        return _err(f"本地 ComfyUI 缺少節點：{cap.unsupported}", 400, stage="gate2_capability")
    if cap.missing_models:
        return _err(f"缺少模型：{cap.missing_models}", 400, stage="gate2_models")
    
    # Gate 3: 強制 allowlist（即使 capability 通過，hackme_web 仍可能拒絕該 class）
    try:
        enforce_allowlist(analysis)
    except SafetyError as exc:
        return _err(str(exc), 400, stage="gate3_allowlist")
    
    # Gate 4: 必要欄位 + numeric / enum / size constraints
    #   先擋掉 user_inputs 缺漏 / 超範圍 / 類型錯誤，避免 Gate 5 已經 copy 圖片到
    #   ComfyUI input/ 才發現 inputs 不合法（造成孤兒暫存檔）。
    missing = required_user_inputs_unfilled(analysis, user_inputs)
    if missing:
        return _err(f"必要欄位未填：{missing}", 400, stage="gate4_inputs")
    try:
        validate_user_input_constraints(analysis, user_inputs)
    except ValueError as exc:
        return _err(str(exc), 400, stage="gate4_constraints")
    
    # Gate 5: 安全改寫 + image remap + apply user_inputs
    #   到這裡才真正動 ComfyUI input/ 暫存檔；上面 4 個 gate 都過了才 copy 圖。
    try:
        workflow = rewrite_save_image_prefix(workflow, user_id=actor["id"], run_id=run_id)
        workflow = remap_load_image_to_cloud_file(
            workflow,
            image_field_assignments=user_inputs.get("images") or {},
            actor=actor, conn=conn, run_id=run_id,
        )
        workflow = apply_user_inputs(workflow, analysis, user_inputs)
    except SafetyError as exc:
        return _err(str(exc), 400, stage="gate5_safety")
    
    # All gates passed — queue
    audit("COMFYUI_TEMPLATE_RUN_GATE_PASS", get_client_ip(),
          user=actor["username"], detail=f"preset_id={preset_id} run_id={run_id}")
    return _queue_and_return(workflow, run_id, ...)
```

### 10.2 Audit log

每個 gate 都寫 audit row：

| event_type | success | detail |
|---|:--:|---|
| `COMFYUI_TEMPLATE_RUN_GATE_FAIL` | false | `gate=<n>, reason=<msg>` |
| `COMFYUI_TEMPLATE_RUN_GATE_PASS` | true | `preset_id=, run_id=, mode=` |
| `COMFYUI_TEMPLATE_SAFETY_REWRITE` | true | `node_count=, save_prefix_rewritten=, image_remapped=<n>` |
| `COMFYUI_TEMPLATE_RUN_INPUT_CLEANUP` | true | `run_id=, files_removed=<n>, reason=<gate5_failure|queue_failure>` |

### 10.3 Implementation Notes（必讀，不是建議）

實作 §10.1 5-gate 流程時，這三點必須跟 happy path 一起寫；漏掉任一條都算 spec 不完整：

1. **Gate fail 必先 audit 再 return**
   每個 `return _err(...)` **前**都要先寫一筆 `COMFYUI_TEMPLATE_RUN_GATE_FAIL`（含 `gate=<n>` 與失敗 stage / reason）。**不可**只在 happy path 結束時記 `..._GATE_PASS`，否則攻擊者多次失敗嘗試在 audit chain 上完全沒留痕。建議用 helper：
   ```python
   def _gate_fail(gate, stage, msg, *, actor, preset_id, run_id, **extra):
       audit("COMFYUI_TEMPLATE_RUN_GATE_FAIL", get_client_ip(),
             user=actor["username"], success=False,
             detail=f"gate={gate} stage={stage} preset_id={preset_id} run_id={run_id} reason={msg} " + _kv(extra))
       return _err(msg, 400, stage=stage)
   ```
   每個 `return _err(...)` 都改走這個 helper，杜絕忘記寫 audit 的可能性。

2. **Gate 5 開始就要可清理：每個 run_id 一個臨時資料夾 + 失敗自動清**
   Gate 5 一旦呼叫 `remap_load_image_to_cloud_file`，就會把 cloud drive 的圖複製到 `ComfyUI input/<run_id>/<node_id>.png`（請務必把 `<run_id>` 當成子目錄，不要平鋪），這意味著從這刻起任何例外都會留下暫存檔。要求：
   - 用 try/except 包整個 Gate 5 + queue。失敗時 `cleanup_run_temp_files(run_id)` 立即刪除 `ComfyUI input/<run_id>/`，並寫 `COMFYUI_TEMPLATE_RUN_INPUT_CLEANUP` 一筆 audit。
   - queue_prompt 成功後，當下不刪（ComfyUI 還在跑）；改成由 `services/comfyui/files.py` 的 sweeper（既有的 background cleanup）負責「`run_id` 完成或超時 → 刪暫存」。
   - **任何時候**對 `ComfyUI input/` 的清理都必須只動本次 `<run_id>` 子樹，禁止 `rmtree(ComfyUI input/)` 或用 glob 跨 run。
   - 若部署環境無 sweeper，spec 要求 ship 一個 `runtime/comfyui_input_cleanup.cron` 或 systemd-timer，每小時 reap > 24h 未完成的 `<run_id>/` 目錄；不能允許「沒清就 ship」。

3. **`apply_user_inputs` 不得覆蓋 image 欄位**
   `remap_load_image_to_cloud_file` 已經把 `LoadImage.image` / `LoadImageMask.image` 改寫成 ComfyUI input 內的安全檔名（`<actor_id>_<run_id>_<node_id>.png`）。`apply_user_inputs` 接著套使用者輸入時：
   - 對 `LoadImage` / `LoadImageMask` 的 `image` 欄位**永不覆蓋**；patch 邏輯要 explicit skip 這幾個 (class_type, input) 組合。
   - 不得把 user 原始上傳字串、`cloud_file_id`、URL 寫回 workflow（避免攻擊者透過 manifest binding 或欄位 fuzzing 把 image 重新指向 cloud drive 路徑或外部來源）。
   - 同樣的禁覆蓋規則套用在 §18.4 之後加進來的任何「自動 image input」panel type — 一律以 remap 結果為最終 ground truth。
   - 建議在 `apply_user_inputs` 開頭明確擋：
     ```python
     PROTECTED_INPUTS = {("LoadImage", "image"), ("LoadImageMask", "image"), ("LoadImageMask", "mask")}
     for node_id, patch in user_input_patches.items():
         class_type = workflow[node_id].get("class_type")
         for input_name in list(patch.keys()):
             if (class_type, input_name) in PROTECTED_INPUTS:
                 raise SafetyError(
                     f"node {node_id}.{input_name} 是受保護欄位（已由安全改寫處理），"
                     f"不允許再透過 user_inputs 覆蓋"
                 )
     ```
   違反這條會直接吃掉 §7.3 的全部安全工作，等於繞過 mime / size / scan / decode 五道驗證，必須 hard fail，不允許 silent skip。

---

## 11. 錯誤訊息 Catalog（繁中）

每個錯誤訊息必須：
1. **指出哪個欄位 / 哪個節點 / 哪個 stage** 出錯
2. **說明為什麼擋**（不是「失敗」這種字）
3. **提示下一步**（如何修）

### 11.1 Sanitize stage

| 條件 | 訊息 |
|---|---|
| JSON parse 失敗 | `workflow JSON 格式錯誤：第 N 行附近無法解析。請確認上傳的是合法 JSON。` |
| 不是 dict | `workflow 必須是 JSON 物件，目前形狀為陣列。` |
| UI graph normalize 失敗 | `workflow UI graph 缺少 nodes / links 格式不正確 / 沒有可轉換的可執行節點。請改用 ComfyUI API format 或修正 UI graph。` |
| 大小超過 256KB | `workflow 大小超過 256KB（目前 NNN KB），第一版不支援大型 workflow。` |
| 節點數超過 50 | `workflow 節點數 N > 50，第一版限制 50 以內。` |
| 含絕對路徑 | `欄位 workflow.<node_id>.inputs.<field> 不可包含絕對路徑：'/...'。請改用 hackme_web 雲端硬碟內的檔案。` |
| 含外部 URL | `欄位 workflow.<node_id>.inputs.<field> 不可包含外部 URL：'http://...'。` |
| 路徑穿越 `../` | `欄位 workflow.<node_id>.inputs.<field> 含有路徑穿越字元 '../'，不允許。` |
| 命令片段 | `欄位 workflow.<node_id>.inputs.<field> 含有命令片段 'bash -c'，不允許。` |

### 11.2 Allowlist stage

| 條件 | 訊息 |
|---|---|
| Unknown class | `workflow 含未授權的節點類型：['<class>', ...]。第一版只支援 17 種核心節點 + ControlNet 標準 preprocessor，完整清單見 docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md §4。` |
| 多個 SaveImage | 後端會全部改寫到 `hackme/<user>/<run_id>` prefix；若產品 UI 尚未完成多輸出管理，前端應提示使用者檢查輸出清單。 |
| LoRA 超過 4 個 | `workflow 含 N 個 LoraLoader 超過上限 4 個，請減少。` |

### 11.3 Capability stage

| 條件 | 訊息 |
|---|---|
| Class 不在本地 | `本地 ComfyUI 缺少以下節點：['<class>', ...]。請先安裝對應的 custom node 套件。` |
| 模型不存在 | `本地 ComfyUI 缺少以下模型：checkpoint=['<name>'], lora=[...]。請到 admin / 模型下載頁面取得。` |
| Sampler 名稱不在 enum | `KSampler 的 sampler_name='<name>' 不在本地可用清單；請改用：['euler', 'dpmpp_2m', ...] 之一。` |

### 11.4 Safety stage

| 條件 | 訊息 |
|---|---|
| LoadImage cloud_file_id 不屬於 actor | `指定的圖片檔（id=<id>）不存在或不屬於你的雲端硬碟。請重新上傳或選擇你擁有的檔案。` |
| Image cloud_file 已軟刪除 | `指定的圖片檔（id=<id>）已被刪除，請重新選擇。` |
| node_id 不是有效字串 | `node_id 必須是字串形式的整數，目前 '<value>' 不合法。` |

### 11.5 Inputs stage

| 條件 | 訊息 |
|---|---|
| 必要 TEXT 為空 | `節點 <node_id>（<class>）的 <field> 為必填，請輸入內容。` |
| 必要 IMAGE 未指定 | `節點 <node_id>（<class>）的 image 必填，請從雲端硬碟選一張圖片。` |
| NUMERIC 超出範圍 | `節點 <node_id>（<class>）的 <field>=<value> 超出允許範圍 [<min>, <max>]。` |
| Preview token 過期 | `預覽 token 已過期（超過 30 分鐘），請重新分析 workflow。` |
| Preview token 不屬於你 | `預覽 token 不屬於你的 session。` |

---

## 12. 測試 Fixture 計畫

`tests/comfyui/template/fixtures/` 內存以下 workflow JSON：

### 12.1 Happy path

| Fixture | 用途 |
|---|---|
| `txt2img_minimal.json` | 最小 txt2img（Checkpoint + 2 × CLIP + Empty + KSampler + VAEDecode + SaveImage = 7 節點）|
| `img2img_basic.json` | 加 LoadImage + VAEEncode |
| `inpaint_basic.json` | 加 LoadImageMask + VAEEncodeForInpaint |
| `outpaint_basic.json` | 加 ImagePadForOutpaint |
| `upscale_only.json` | LoadImage + UpscaleModelLoader + ImageUpscaleWithModel + SaveImage |
| `txt2img_with_lora.json` | 1 個 LoraLoader |
| `txt2img_with_lora_stack_4.json` | 4 個 LoraLoader 上限 |
| `txt2img_with_vae.json` | 額外 VAELoader |
| `controlnet_canny.json` | ControlNetLoader + Canny preprocessor |

### 12.2 Sanitize fail（每個一支）

| Fixture | 預期 stage |
|---|---|
| `bad_ui_graph_format.json` | sanitize: format detection |
| `bad_absolute_path.json` | sanitize: path |
| `bad_external_url.json` | sanitize: url |
| `bad_path_traversal.json` | sanitize: traversal |
| `bad_oversize_50001nodes.json` | sanitize: size |
| `bad_command_injection.json` | sanitize: command |

### 12.3 Allowlist fail

| Fixture | 預期 stage |
|---|---|
| `bad_unknown_class.json` | allowlist: unknown |
| `bad_reactor_faceswap.json` | allowlist: explicitly denied |
| `bad_animatediff.json` | allowlist: animatediff not supported |
| `bad_5_lora.json` | allowlist: lora too many |
| `bad_2_save_image.json` | allowlist: multi output |

### 12.4 Capability fail

| Fixture | 預期 stage |
|---|---|
| `cap_missing_class.json` | capability: ComfyUI 沒裝 |
| `cap_missing_model.json` | capability: 模型不存在 |
| `cap_invalid_sampler.json` | capability: sampler enum |

### 12.5 Safety fail

| Fixture | 預期 stage |
|---|---|
| `safety_load_image_other_user.json` | safety: cloud_file_id 不屬於 actor |
| `safety_save_filename_traversal.json` | safety: filename_prefix（會被改寫，不該 fail；test 確認改寫）|

---

## 13. 階段拆分（acceptance criteria）

| Phase | Scope | Acceptance |
|---|---|---|
| **0** | 規格文件（本檔）+ Codex review | 本檔 commit；Codex 在 cross_agent_sync 簽認 schema |
| **1** | `services/comfyui/template/{analyzer,allowlist}.py` + 9 個 happy fixture + 6 個 sanitize fail fixture | `scripts/testing/pytest_in_tmp.sh tests/comfyui/template/ -q` 全綠；Analyzer 對所有 happy fixture 回傳正確 `class_types` + `fields` |
| **2** | `services/comfyui/template/capability.py` + cache + 3 個 capability fail fixture | Capability 在 mocked client 下能正確分類 SUPPORTED / PARTIAL / UNSUPPORTED |
| **3** | `services/comfyui/template/safety.py` + 5 個 allowlist fail + 2 個 safety fail | 4 個 hard-block 各自有 negative test 證明擋住 |
| **3b** | refactor `services/comfyui/workflow/builder.py` 用 `next_safe_node_id` allocator | builder 既有 test 仍綠；新加 collision regression test |
| **4** | `POST /api/comfyui/templates/preview` + preview_token | E2E test：upload → preview → get token；token 過期 → 401；別 user 拿 token → 403 |
| **5** | `services/comfyui/template/ui_schema.py` + frontend 6 panel | manual UI test：6 panel 分別開合；fill in 後 schema validate |
| **6** | 改造 `POST /api/comfyui/workflows/<id>/run` 加 5-gate | E2E：每 gate 各自 fail 個負面測試；happy path 走完進 ComfyUI queue |

---

## 14. 與既有 code 的整合

### 14.1 不重做

- `sanitize_workflow_json()` 仍是第一道過濾
- `summary.py:required_models / required_loras / required_controlnets` 沿用，Analyzer 在它上面加分類
- `client.get_object_info()` 直接用，加 cache wrapper
- 既有 `POST /api/comfyui/workflows/import` endpoint **不刪**，但要求帶 `preview_token`

### 14.2 必須改

- `services/comfyui/workflow/builder.py` hardcoded `next_node_id = 10` → `next_safe_node_id()` allocator
- `services/comfyui/validation/rules.py` 增加 `MVP_NODE_COUNT_LIMIT = 50`、`MVP_LORA_LIMIT = 4`、`MVP_TEXT_FIELD_LIMIT = 2000`

### 14.3 新增

- `services/comfyui/template/__init__.py`
- `services/comfyui/template/allowlist.py`
- `services/comfyui/template/analyzer.py`
- `services/comfyui/template/capability.py`
- `services/comfyui/template/safety.py`
- `services/comfyui/template/ui_schema.py`
- `services/comfyui/template/preview_token.py`
- `tests/comfyui/template/__init__.py`
- `tests/comfyui/template/fixtures/<name>.json`（25+ 個）
- `tests/comfyui/template/test_analyzer.py`
- `tests/comfyui/template/test_capability.py`
- `tests/comfyui/template/test_safety.py`
- `tests/comfyui/template/test_preview_token.py`
- `tests/comfyui/template/test_run_gate.py`

---

## 15. Roll-out 計畫

1. Phase 0 規格 review（本檔）
2. Codex 確認 schema 後 → branch `feature/comfyui-template-importer` 切出
3. Phase 1-3 純 backend，每 phase 單獨 PR
4. Phase 3b（builder allocator）跟 Phase 3 同 PR 也行（範圍小）
5. Phase 4 加 endpoint：`POST /api/comfyui/workflows/import` 的 **path 保留**，但行為改為 **必須帶 `preview_token`**；單純 sanitize-only 的舊路徑只能在 feature flag `feature_comfyui_template_importer_strict=false` 時暫時保留，且 **絕不允許 run bypass**（即舊路徑寫入的 workflow 仍須經 §10 5-gate 才能執行；新舊兩條 import 路徑落 DB 後共用同一個 run pipeline）。
6. Phase 5 frontend 加新 modal，**舊 generate 介面不動**
7. Phase 6 run gate — flag `feature_comfyui_template_importer_strict` 切 true；同時把 `feature_comfyui_legacy_import_enabled` 切 false，舊 sanitize-only import 路徑全關
8. 全 ship 一個 release 後，下一版才**刪**舊 import endpoint 的 sanitize-only 程式碼路徑與 feature flag

---

## 16. 不做的事（再次強調）

- ❌ 自動修復破 JSON（user 要看到完整錯誤）
- ❌ 自動下載缺失模型（admin 才有權，分流到 model download flow）
- ❌ 改變 ComfyUI 的 prompt queue 機制（不動 `execution.py`）
- ❌ 替 user 「智慧化」改 sampler / steps（user 自己決定）
- ❌ AnimateDiff / IPAdapter / FaceDetailer / ReActor 任何一個（第一版）
- ⚠️ 多輸出分支：後端 safe prefix rewrite 已支援，產品 UI/輸出管理仍需單獨驗收
- ✅ UI graph format 自動轉 API format 已在 preview/import normalize 實作；run gate 不直接收 UI graph
- ❌ Group node / nested workflow（第一版）

---

## 17. Open Questions

需要 user / Codex / root 確認：

1. **`internal_test` mode 是否允許 import？** 我傾向**禁止**（importer 是 production feature；test mode 的 user 應走 system templates）
2. **Preview token 過期後是否允許 silent retry？** 我傾向**不允許**，要 user 重 upload
3. **MVP 是否限定 root + manager 才能 import？** 第一版 user 也能 import；但只給自己用（visibility=private）
4. **是否要把 builder 重構（§14.2）拆獨立 commit 先 ship？** 我傾向**是**（小 PR / 風險低 / 不依賴 importer）
5. **超過 50 節點要不要支援「降級」**：reject 或截斷？ 我傾向**reject**（截斷會破壞 graph 連線）

---

## 18. Phase 2 Addendum — Manifest-Driven Dynamic UI

> **狀態**：Plan / Spec — Phase 2 規劃
>
> **作者**：claude (Opus 4.7) · 2026-05-08
>
> **承接**：Phase 1（§0–§18）解決 *安全* 與 *能力比對* — 所有 workflow 走相同的 sanitize → preview → import → run 5-gate 流程。Phase 2 在這個底座上解 *使用體驗*：UI 不再硬寫、workflow 可獨立擴充、頁面預設極簡。
>
> **不會推翻 Phase 1**：本章新增的 manifest schema、panel 元件、registry 都是 *疊加層*，所有 run 路徑仍然必須通過 §7 / §10 的 5-gate；任何在本章沒重述的安全約束都繼續適用。

---

### 18.0 TL;DR — Phase 1 vs Phase 2

| 面向 | Phase 1（§0–§18）| Phase 2（本章）|
|---|---|---|
| 入口 | 使用者上傳一份 workflow.json | 使用者從 registry 選 workflow |
| UI 來源 | 後端從 workflow.json 自動推導 `UISchema`（§9）| `workflows/comfyui/<id>/manifest.json` 顯式描述 panels |
| 前端架構 | 沿用既有 hardcoded 表單 + 自動 panel | 動態 panel 元件由 manifest 驅動，舊硬寫表單逐步退場 |
| Workflow 來源 | user 上傳 → DB | `workflows/comfyui/<id>/` 目錄（system / user / shared visibility）|
| Run 流程 | preview → import → run（5-gate）| **完全沿用** Phase 1 5-gate，只是輸入是「registry id + 使用者欄位」 |
| Panel 數量 / 類型 | 固定 6 種（§9.2）| 可擴充元件庫；manifest 指名 type |

---

### 18.1 Directory Layout

registry 來源分兩半，**system 走 repo filesystem，user / shared 走 DB**：

| visibility | 儲存位置 | 觸發載入 |
|---|---|---|
| `system` | `workflows/comfyui/<workflow_id>/`（repo 內檔案）| 啟動時掃；root 手動 refresh |
| `user`（私有）| DB `comfyui_workflows` row + `comfyui_workflow_manifests` row | 走 Phase 1 import 流程寫入 |
| `shared` | DB（同上 + `shared_with_*` metadata）| 同 user，registry 過濾後曝露 |

新增 repo 內目錄：

```
workflows/comfyui/
  txt2img_basic/
    workflow.json     # ComfyUI API format，無 hackme_web 私有欄位
    manifest.json     # UI panel + binding 描述
    README.md         # 給操作者的中文說明（可選）
  img2img_basic/
    workflow.json
    manifest.json
    README.md
  inpaint_basic/
    workflow.json
    manifest.json
    README.md
```

**命名注意**：

- 跟既有 `workflows/trading_bot/`（**交易 bot workflow**，用途完全不同；那是 trading 模組的 system templates）區隔；ComfyUI workflow 一律放 `workflows/comfyui/...`，不要把兩者放在同一層或互相 symlink。
- `<workflow_id>` 必須符合 `^[a-z][a-z0-9_]{0,63}$`，registry 載入時驗。
- user-imported workflow **不放 repo 目錄**，永遠走 DB（避免 user 上傳節奏跟 git commit 節奏混在一起）。

---

### 18.2 workflow.json 規範

承接 §3 的所有要求。額外重申：

- runtime/DB 內部 **必須** 是 ComfyUI API format（`{node_id: {class_type, inputs}}`）；preview/import 可接受並轉換 UI graph format。
- **不得**塞 hackme_web 私有欄位（如 `__hackme_meta__`、`_ui_layout`、`_panel_id` 等）。所有 UI metadata 一律放 manifest.json。
- **必須能被 ComfyUI API queue 執行**（送進 `/prompt` endpoint 後流程正常完成）。
- **不承諾**可由 ComfyUI 前端 editor 完整還原 layout（節點位置 / 連線視覺 / 群組 / `pos` / `widgets_values` 等 UI graph 專屬欄位）— preview/import 只做能執行的 API prompt 正規化。
- 從 ComfyUI 重新匯出（API format）後，與 repo 內的版本經 §3.4 normalize 後 `diff` 應為空（除 `class_type` 順序之類無語意差異）。

> 一句話：**workflow.json 是 ComfyUI 的；manifest.json 是 hackme_web 的**。

---

### 18.3 manifest.json Schema

承接 §9.1 的 UISchema panel 形狀，補上以下頂層欄位 + 顯式 schema 版本。

```json
{
  "schema_version": 1,
  "id": "inpaint_basic",
  "name": "Inpaint 基礎修圖",
  "description": "局部重繪工作流",
  "workflow_file": "workflow.json",
  "ui": {
    "initial_collapsed": true,
    "panels": [
      {
        "type": "image_input",
        "id": "source_image",
        "title": "原圖",
        "repeatable": false,
        "required": true,
        "bind": { "node_id": "12", "input": "image" }
      },
      {
        "type": "image_input",
        "id": "mask_image",
        "title": "遮罩",
        "repeatable": false,
        "required": true,
        "bind": { "node_id": "13", "input": "image" }
      },
      {
        "type": "prompt",
        "id": "prompt_positive",
        "title": "正向提示詞",
        "bind": { "node_id": "6", "input": "text" }
      }
    ]
  }
}
```

#### 必填頂層欄位

| 欄位 | 用途 |
|---|---|
| `schema_version` | int；目前固定 `1`。registry 用這個做 forward-compat。 |
| `id` | 跟目錄名一致；用於 URL 與 audit |
| `name` | 顯示用繁中名稱 |
| `description` | 一行簡介（不超過 200 字元）|
| `workflow_file` | 通常為 `"workflow.json"`，預留多 graph 版本 |
| `ui.panels[]` | 至少一個 panel；不得超過 24 個（DoS guard）|

#### Panel 必填欄位

| 欄位 | 用途 |
|---|---|
| `type` | 見 §18.4 |
| `id` | 在這份 manifest 內唯一；用於 frontend state key |
| `title` | 顯示名稱 |
| `bind` | `{node_id, input}`，指向 workflow.json 中的特定節點欄位 |
| `repeatable` | 可選；預設 `false`。`true` 代表使用者可動態 add/remove instance |
| `required` | 可選；預設 `false`。frontend 先檢、backend run gate 也會再檢 |

---

### 18.4 Panel Type Catalog

擴充 §9.2 的 6 種 panel：

| `type` | 對應 §9.2 panel | 綁定的節點/欄位範例 | 備註 |
|---|---|---|---|
| `prompt` | `text` | `CLIPTextEncode.text` | textarea；max 2000 字元 |
| `image_input` | `image` | `LoadImage.image`、`LoadImageMask.image` | 接受 `image/*`；走 §7.4 mime gate |
| `mask_input` | `image`（特化）| `LoadImageMask.image` | 自動切灰階 / Mask 預覽 |
| `slider` | `sampler`（部分）| `KSampler.steps`、`KSampler.cfg` | numeric + min/max/step |
| `seed` | `sampler`（部分）| `KSampler.seed` | 含「鎖定 / 隨機」按鈕 |
| `sampler` | `sampler` | `KSampler.{sampler_name, scheduler, denoise}` | 整組 |
| `controlnet` | `model`（特化）| `ControlNetLoader.control_net_name` + `ControlNetApplyAdvanced.{strength,start_percent,end_percent}` | 第二版才支援 stack |
| `select` | （新）| 任何 enum 型欄位 | 從 manifest constraints.options 取 |
| `repeatable_image` | （新）| `repeatable: true` 的 image_input 集合 | 內部展開為多個 `bind` 串 |

**`type` 必須在 allowlist**（registry 載入時驗）；任何未列入的 `type` → reject 整份 manifest。

---

### 18.5 Folding / Lazy / Repeatable

- **folding**：所有 panel 預設 collapsed（`ui.initial_collapsed=true`）。一鍵 expand all / collapse all。每個 panel state 寫進 `localStorage` 以利 reload。
- **lazy render**：尚未 expand 的 panel 不掛 input handler，避免大 manifest 一次塞滿 DOM。
- **repeatable**：`repeatable: true` 的 panel 可被 add/remove。

#### 18.5.1 Repeatable 的 graph patch 策略

**選定策略 A**：workflow.json 預先放 N 個 placeholder 節點，每個 instance 只 patch input。**不**動態 clone 節點。理由：

- clone 節點要重連 link / 處理 condition / 維持 graph 完整性 → 第一版風險過高
- ComfyUI 原生匯出/匯入 placeholder 節點沒有問題

manifest 必須宣告 `repeatable.max_instances`（≤ N，N 由 workflow.json 預配）：

```json
{
  "type": "image_input",
  "id": "ref_images",
  "repeatable": true,
  "repeatable_max_instances": 4,
  "binds": [
    { "node_id": "21", "input": "image" },
    { "node_id": "22", "input": "image" },
    { "node_id": "23", "input": "image" },
    { "node_id": "24", "input": "image" }
  ]
}
```

**MVP repeatable 規範**（重述以避免誤讀）：

- 只支援 *bounded placeholder*：workflow 作者預配 N 個節點，manifest `binds[]` 一一對應；`repeatable_max_instances == len(binds) == N`。
- 不啟用的 instance 由 workflow 作者保證**不會破壞 graph**（例：用 mute mode、conditional execution、或在 `binds` 之外的節點預設 fallback 值）。
- registry 載入時驗：
  1. `len(binds) == repeatable_max_instances`，且 `repeatable_max_instances ≤ 8`（DoS guard）；
  2. 每個 `binds[i]` 都通過 §18.6 一致性 gate；
  3. workflow 作者必須在 manifest 寫 `unused_instance_strategy: "leave_default" | "mute_node"`，否則 registry reject 該 repeatable panel。
- **第一版不做**：動態 clone node、自動 prune graph branch、unbounded repeatable。任何「N 不固定」的需求列為 Phase 3。

換句話說：repeatable 必須 **bounded、prewired、可驗證**。任何要求「依使用者輸入動態增減節點」的設計都先 reject。

---

### 18.6 Node Binding Validation（Phase 2 安全強化）

承接 §7 的 4 個 hard-block，新增 **manifest-vs-workflow 一致性 gate**：

registry 載入 manifest 時，對 `panels[].bind` / `binds[]` 一一驗：

1. `bind.node_id` 必須存在於 workflow.json 的 nodes
2. 該節點的 `class_type` 必須在 §4 allowlist
3. `bind.input` 必須是該 `class_type` 在 §4 規範中可寫的 input 名稱
4. panel `type` 與 input 的 §5 category 必須相容（例：`prompt` 只能綁 `TEXT` category；`image_input` 只能綁 `IMAGE`；`slider` 只能綁 `NUMERIC`）
5. 同一個 `(node_id, input)` 不得被多個 panel 綁定（避免 race / 後綁覆蓋）
6. 所有 §4 的 *required* input 必須要嘛被某 panel 綁定、要嘛 workflow.json 已寫死合法值；不能兩邊都沒給

任一 fail → registry 拒絕載入該 workflow（system workflow 在 deploy 時就應該 fail；user workflow 由 import-time gate 擋）。

---

### 18.7 Workflow Registry

#### 18.7.1 模組路徑

`services/comfyui/workflow/registry.py`（**不是** `services/comfyui_workflow_registry.py`；保持跟既有 `workflow/builder.py`、`workflow/summary.py` 同 package）。

#### 18.7.2 對外 API

```python
def list_workflows(*, actor) -> list[ManifestSummary]:
    """List workflow manifests visible to actor (system / shared / private)."""

def load_workflow(workflow_id: str) -> tuple[WorkflowJSON, ManifestJSON]:
    """Raise WorkflowNotFound / ManifestInvalid as needed; do not auto-fix."""

def patch_workflow_inputs(
    workflow_id: str,
    user_inputs: dict[str, Any],
    *,
    panels: list[Panel],
) -> WorkflowJSON:
    """Apply validated user inputs through manifest binds; never mutate
    workflow.json on disk. Returns the patched-in-memory WorkflowJSON ready
    for §10 run gate."""
```

#### 18.7.3 Cache / hot reload

- registry 啟動時掃描 `workflows/comfyui/`，建記憶體 index。
- root API `POST /api/admin/comfyui/registry/refresh` 可手動 invalidate；不做 file watcher（避免 inotify 在容器環境的 edge case）。
- user upload 走 Phase 1 import 流程後，registry 把 DB row mount 進同一個 index（visibility 過濾在 `list_workflows` 裡做）。

---

### 18.8 API Surface

跟 §10 的 run gate 整合。**沒有任何 API 繞過 §7 / §10 的 5-gate**。

| Method + Path | 用途 | Gate |
|---|---|---|
| `GET /api/comfyui/workflows` | 列 visible workflows + manifest summary | RBAC + visibility |
| `GET /api/comfyui/workflows/<id>` | 取 manifest + workflow metadata（**不**回 workflow.json 全文）| RBAC |
| `POST /api/comfyui/workflows/<id>/run` | 取 manifest → patch user_inputs → §10 run | 5-gate（capability、sanitize、model availability、quota）|
| `POST /api/comfyui/workflows/import` | Phase 1 import（不變動）| §8 preview token |
| `GET /api/comfyui/workflows/<id>/export` | 匯出原生 workflow.json（不含 manifest）| RBAC |
| `POST /api/admin/comfyui/registry/refresh` | invalidate registry cache | root only |

#### 18.8.1 RBAC

| 操作 | 預設權限 |
|---|---|
| list / view system workflows | 任何 logged-in user |
| list / view shared workflows | 該 workflow `shared_with` 內的 user |
| list / view private workflows | 該 workflow owner |
| run any workflow | 同 view + 不在違規禁用名單 |
| import (Phase 1) | user / manager / root（沿用 §17 Open Question 1 的決議：第一版 user 也能 import 自己的 private workflow）|
| registry refresh | root only |

---

### 18.9 Frontend Module Split

#### 18.9.1 現況問題

`public/js/36-comfyui.js` 目前 **2728 行**，硬寫 txt2img / img2img / inpaint / controlnet 四種表單。直接在這支檔加 manifest dispatcher 會讓檔案爆到 5000+ 行。

#### 18.9.2 目標檔案結構

```
public/js/
  36-comfyui.js                # shell：頁面初始化、workflow selector、panel host
  comfyui/                     # 新子目錄
    panels/
      prompt.js
      image_input.js
      mask_input.js
      slider.js
      seed.js
      sampler.js
      controlnet.js
      select.js
      repeatable_image.js
    registry_client.js          # 包 GET /api/comfyui/workflows*
    panel_dispatcher.js         # type → panel module 的 lookup
    state.js                    # localStorage 狀態保存（folding、user inputs）
```

每個 `panels/*.js` 匯出一個 `mountPanel(rootEl, panel, ctx)` 函式，無 side effect、無全域變數寫入。

#### 18.9.3 載入策略

- 頁面初始：只載 `36-comfyui.js` shell + `registry_client.js`，呼叫 `GET /api/comfyui/workflows` 取列表。
- 使用者選了 workflow → fetch manifest → `panel_dispatcher.js` 動態 import 對應的 `panels/<type>.js`（用 `<script type="module">` + `import()`）。
- 沒被選到的 workflow / panel type 不會被載入（網路 + 解析雙省）。

---

### 18.10 Import / Export

#### 18.10.1 Import

承接 §8 的 preview/import 流程。Phase 2 額外：

- import 時若 user 沒提供 manifest.json → 後端用 §6 / §9 的 auto-derive 邏輯產出 *minimal* manifest（每個必填 input 一個對應 panel，type 從 §5 category 推導）。
- root / manager 可在 import 之後對該 user 的 manifest 做 UI metadata 補強（加 panel title、調整 panel 順序、把多個 input 合併進同一個 panel）。
- user 自己**只能編輯 description / panel title**，不能改 bind（避免繞過 §18.6 一致性檢查）。

#### 18.10.2 Export

- `GET /api/comfyui/workflows/<id>/export` 永遠回 *原生 workflow.json*，**不含** manifest.json。
- 想要連 manifest 一起拿走 → `?include_manifest=1`，回傳 zip（`workflow.json` + `manifest.json` + `README.md`）。
- export 後的 workflow.json 可送進 ComfyUI API queue 執行；UI editor layout 還原**不在保證範圍**。這是 §18.2 「workflow.json 是 ComfyUI API queue 的」的可驗證行為規則。

---

### 18.11 RBAC + Quota（Phase 2 specific）

| 限制項 | 上限 | 強制位置 |
|---|---|---|
| manifest 大小 | 64 KB | registry load |
| panels 數量 | 24 | registry load |
| repeatable_max_instances | 8 | registry load + run-time |
| user-imported workflow 數量 | 預設 50（root 可調）| import API |
| `/run` 並發 per user | 預設 2 | §10 quota gate |

---

### 18.12 Phased Migration Plan

舊硬寫表單不是一次拆掉，分三階段並行：

#### Phase 2.A — 新舊並存（feature flag `comfyui_dynamic_ui_enabled`）

- registry + manifest schema + 新 panel components 全上
- 頁面有 toggle：「使用 manifest 動態 UI」/「使用既有快速表單」
- 老用戶不變；新 workflow 必走 manifest

#### Phase 2.B — 既有 4 種 workflow 遷移

- 把現有的 txt2img / img2img / inpaint / controlnet 各做成一份 `workflows/comfyui/<workflow_id>/{workflow.json, manifest.json, README.md}`
- 對比測試：feature flag 兩端輸出 byte-identical（§3.4 normalize 後）

#### Phase 2.C — 移除老表單

- toggle 預設 ON，`feature_comfyui_legacy_forms_enabled=false`
- 兩個 release 後刪除 `36-comfyui.js` 內舊表單程式碼
- `2728 → 預估 800 行 shell` 

---

### 18.13 Test Plan

| 範圍 | 必跑 test |
|---|---|
| manifest schema 驗證 | `tests/comfyui/test_manifest_schema.py` — 含正反例（ID 格式、panels 上限、必填欄位） |
| §18.6 一致性 gate | `tests/comfyui/test_manifest_workflow_binding.py` — node_id 不存在、input 名稱不對、category 不相容、required 漏綁 |
| Repeatable patch | `tests/comfyui/test_manifest_repeatable.py` — instance 數 vs `repeatable_max_instances`、optional_skip 行為 |
| Registry list / load | `tests/comfyui/test_workflow_registry.py` — visibility filter、cache invalidate |
| Run 5-gate（regression）| `tests/comfyui/test_workflow_run_gates.py` — manifest 路徑必須走完 §7 / §10，**不得**繞過 |
| Import auto-manifest | `tests/comfyui/test_import_auto_manifest.py` — 無 manifest 時 auto-derive 結果合理 |
| Frontend smoke | `tests/frontend/comfyui/test_dynamic_panels.py` — JS 字串檢查 + dispatcher table；類似 §11 既有的 frontend 字串檢查 |

`pytest_in_tmp.sh -q tests/comfyui/ tests/frontend/comfyui/` 必須 100% 過才視為 Phase 2 完成。

---

### 18.14 不做的事（Phase 2）

| 不做 | 理由 |
|---|---|
| ComfyUI UI graph format 完整 round-trip 還原 | preview/import 只轉 API prompt；不保存 UI editor 的完整 layout metadata |
| 動態 clone 節點來支援 unbounded repeatable | §18.5.1 選定 placeholder 策略；unbounded clone 留 Phase 3 |
| Mobile mask 編輯（畫遮罩）| 第一版 mobile 只能上傳已畫好的 mask 圖；in-browser brush 留下一階段 |
| manifest 內含 JS / 表達式 | 純宣告式；任何條件邏輯放後端 §6 capability check |
| user 自己改 manifest binds | §18.10.1 規定 user 只能改 description/title |

---

### 18.15 Open Questions（Phase 2）

1. **Phase 2.A 的 feature flag 預設要 ON 還是 OFF？** 我傾向 **OFF（先 opt-in）**，再依使用回饋切到 ON。
2. **`workflows/comfyui/` 內建幾個 workflow？** 我傾向最少 4 個（txt2img / img2img / inpaint / upscale），對應現有硬寫表單的 1:1 replacement。
3. **manifest panel `title` 是否要支援 i18n？** 第一版只繁中；schema 預留 `title_i18n: {zh-TW, en}` 但 frontend 第一版只讀 `title`。
4. **registry hot-reload 是 root 手動 refresh，還是 server start 時掃一次就固定？** 我傾向**啟動時 + root 手動 refresh** 雙軌；不做 watcher。
5. **export zip 是否要簽章？** 第一版**不簽**；export 視為純使用者方便功能，不是 audit chain 的一環。

---

## 19. 變更履歷

- 2026-05-07 · claude · 初稿（§0–§18，Phase 1）
- 2026-05-08 · claude · 加上 §18 Phase 2 addendum（manifest-driven dynamic UI），承接 §9 的 panel 概念並補上 directory layout / registry / frontend module split / migration plan
- 2026-05-08 · claude · spec review 8 處修正：
  - 殘留 §19.x 引用 → §18.x（章節編號統一）
  - §3.2 釐清 ComfyUI UI graph format vs API prompt format；加 `Unsaved Workflow.json` 範例提示
  - §4 重寫 unknown class 三段處置表（preview pass / import reject / run re-enforce）
  - §7.3 `remap_load_image_to_cloud_file` signature 加 `run_id`；補 MIME / size / 解碼三項驗證
  - §8.2 preview token 補 multi-worker 共享儲存說明（process-local LRU 只適用單 process）
  - §10 run gate 從 4 個拆成 5 個：analyze（不擋）/ capability / allowlist / safety rewrite / inputs，避免把 unknown_class 當最終判斷
  - §18.1 / §18.5.1 registry 目錄統一為 `workflows/comfyui/<id>/`（system 走 filesystem，user / shared 走 DB）
  - §18.5.1 repeatable 補 bounded placeholder 規範 + `unused_instance_strategy` 必填欄位
- 2026-05-08 · claude · spec polish 5 處（pre-implementation review）：
  - §10 Gate 1 從「analyze」擴成「sanitize + normalize + analyze」，避免 DB 內舊 workflow / 手動匯入資料繞過 sanitize（重新跑等於再驗一次 §3.x 限制）
  - §10 Gate 4/5 順序改成：先 inputs + numeric/enum constraints，再 safety rewrite + image remap + apply_user_inputs；避免必填欄位錯時已產生 ComfyUI input 暫存檔（孤兒）
  - §7.3 `scan_status="skipped"` 預設不接受；只有 root 設定 `security.upload_scan_skip_allowed=true` 時才視為合法
  - §18.2 / §15 將「可直接匯入 ComfyUI」改成「可被 ComfyUI API queue 執行；不承諾 UI editor layout 還原」，跟 §3.1 已釐清的 API vs UI graph 區分一致
  - §15 舊 import endpoint：path 保留但必須帶 `preview_token`；sanitize-only 路徑只在 feature flag `feature_comfyui_legacy_import_enabled=true` 時暫存活；**run bypass 永不允許**，新舊路徑落 DB 後共用同一個 §10 5-gate run pipeline
- 2026-05-08 · claude · §10 implementation notes（不是建議，是必做）：
  - 10.2 補 `COMFYUI_TEMPLATE_RUN_INPUT_CLEANUP` audit row
  - 10.3 三條：(a) 每個 gate fail 必先 audit `..._GATE_FAIL` 再 return（用 helper 強制走同一條路徑）；(b) Gate 5 起所有 `ComfyUI input/<run_id>/` 暫存檔在失敗時必須立即清，成功時交給既有 sweeper / cron 清理 24h 未完成項目；(c) `apply_user_inputs` 對 `LoadImage` / `LoadImageMask` 的 `image` 欄位永不覆蓋，必須 hard fail 任何試圖透過 user_inputs 改回原始字串或 cloud_file_id 的 patch — 違反這條等於繞過 §7.3 全部 mime/size/scan/decode 驗證
