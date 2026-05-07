# ComfyUI Template Importer — 規格

> **狀態**：Plan / Spec — 尚未動工
>
> **作者**：claude (Opus 4.7) · 2026-05-07
>
> **預期分支**：`feature/comfyui-template-importer`（從 `03.Points` 切）
>
> **目的**：讓使用者上傳 ComfyUI workflow JSON，經**解析 → 能力比對 → 安全審查 → 輸入欄位映射 → 預覽確認 → 才能執行**，避免任意 JSON 直接 queue 進 ComfyUI 造成 RCE / 路徑穿越 / 模型 misuse。

---

## 0. TL;DR

| 階段 | 動作 | 安全角色 |
|---|---|---|
| 1. Upload | `POST /api/comfyui/templates/preview` | 只解析 + 分析，**不執行** |
| 2. Analyze | 後端產生 `WorkflowAnalysis` + `CapabilityCheck` + `UISchema` | 給 frontend 展示用 |
| 3. Confirm | 使用者填欄位 + 按確認 | frontend 互動 |
| 4. Import | `POST /api/comfyui/workflows/import` 帶 `preview_token` | 存 DB（仍未執行） |
| 5. Run | `POST /api/comfyui/workflows/<id>/run` | 4-gate 強制檢查才送 ComfyUI |

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
| [`POST /api/comfyui/workflows/<id>/run`](../../routes/comfyui.py) | 已存在 | 加 4-gate enforcement |
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
| **多輸出分支**（>1 個 `SaveImage`）| 路徑命名衝突風險 |
| **任意 custom node** | 沒在 allowlist → 拒絕（即使 analyze 看得出意圖也不放行）|
| **ComfyUI UI graph format**（`nodes:[...]` + `links:[...]`）| 只接受 **API format**（`{node_id: {class_type, inputs}}`） |
| **巢狀 group node** | 第一版攤平；若無法攤平則拒絕 |

### 2.3 第二版以後再開（記錄即可）

- ControlNet 多組 stacking
- IPAdapter
- FaceDetailer
- 多輸出分支（拆獨立 `SaveImage` 管線）

---

## 3. Workflow JSON 格式要求

### 3.1 只接受 ComfyUI API format

合法形狀：

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
| `{"nodes": [...], "links": [...]}` | UI graph format，不是 API format |
| `{"prompt": {...}, "extra_data": {...}}` | ComfyUI **export-with-metadata** 包裹格式；要求使用者**先 unwrap 出內層 prompt** |
| Top-level array | 不是 dict |
| 含 `widgets_values: [...]` 欄位 | UI graph 殘留；API format 不該有 |
| 包含 `client_id` / `prompt_id` / `extra_pnginfo` 等執行時 metadata | 拒收（暗示是執行記錄）|

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

**設計原則**：allowlist > blocklist。Unknown class → analyze 通過、execute 拒絕。

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
    actor: dict, conn,
) -> dict:
    new_wf = copy.deepcopy(workflow)
    for node_id, cloud_file_id in image_field_assignments.items():
        node = new_wf.get(node_id)
        if not node or node.get("class_type") not in {"LoadImage", "LoadImageMask"}:
            raise SafetyError(f"node {node_id} 不是 LoadImage / LoadImageMask")
        # 驗證 actor 擁有此 cloud_file_id
        row = conn.execute(
            "SELECT owner_user_id FROM cloud_drive_files WHERE id=? AND deleted_at IS NULL",
            (cloud_file_id,),
        ).fetchone()
        if not row or int(row["owner_user_id"]) != int(actor["id"]):
            raise SafetyError(f"image 檔 {cloud_file_id} 不存在或不屬於你")
        # 把實體檔複製到 ComfyUI input/ 並用 hashed filename
        comfy_filename = f"{actor['id']}_{run_id}_{node_id}.png"
        copy_cloud_file_to_comfy_input(cloud_file_id, comfy_filename)
        node["inputs"]["image"] = comfy_filename
    return new_wf
```

**絕對**不信任 workflow 內的原始 `image` 字串 — 必須由 user 透過 UI 重新指定 cloud_file_id。

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
- 儲存：process-local LRU cache（不寫 DB；server 重啟即失效）
- Key：`(token, user_id)`
- Value：完整的 `WorkflowAnalysis` + sanitized workflow JSON

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

進入點要強制 4 個 gate：

```python
@app.route("/api/comfyui/workflows/<int:preset_id>/run", methods=["POST"])
@require_csrf
def comfyui_workflow_run(preset_id):
    actor, err = _actor_or_401()
    if err: return err
    
    preset = _load_preset(...)
    user_inputs = request.get_json().get("user_inputs") or {}
    run_id = uuid.uuid4().hex
    
    # Gate 1: cache 重新分析（避免使用快取的舊 capability）
    workflow = preset.workflow_json
    analysis = analyze_workflow_json(workflow)
    if analysis.unknown_classes:
        return _err("workflow 含未授權節點，無法執行", 400, stage="gate1_analysis")
    
    # Gate 2: 能力檢查
    cap = check_workflow_capability(analysis, client=comfyui_client)
    if cap.overall == "UNSUPPORTED":
        return _err(f"本地 ComfyUI 缺少節點：{cap.unsupported}", 400, stage="gate2_capability")
    if cap.missing_models:
        return _err(f"缺少模型：{cap.missing_models}", 400, stage="gate2_models")
    
    # Gate 3: 安全改寫
    try:
        enforce_allowlist(analysis)
        workflow = rewrite_save_image_prefix(workflow, user_id=actor["id"], run_id=run_id)
        workflow = remap_load_image_to_cloud_file(
            workflow,
            image_field_assignments=user_inputs.get("images") or {},
            actor=actor, conn=conn,
        )
    except SafetyError as exc:
        return _err(str(exc), 400, stage="gate3_safety")
    
    # Gate 4: 必要欄位都填了？
    missing = required_user_inputs_unfilled(analysis, user_inputs)
    if missing:
        return _err(f"必要欄位未填：{missing}", 400, stage="gate4_inputs")
    
    # All clear — apply user_inputs and queue
    workflow = apply_user_inputs(workflow, analysis, user_inputs)
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

---

## 11. 錯誤訊息 Catalog（繁中）

每個錯誤訊息必須：
1. **指出哪個欄位 / 哪個節點 / 哪個 stage** 出錯
2. **說明為什麼擋**（不是「失敗」這種字）
3. **提示下一步**（如何修）

### 11.1 Sanitize stage

| 條件 | 訊息 |
|---|---|
| JSON parse 失敗 | `workflow JSON 格式錯誤：第 N 行附近無法解析。請確認上傳的是 ComfyUI API format（不是 UI graph）。` |
| 不是 dict | `workflow 必須是 JSON 物件，目前形狀為陣列；請使用 ComfyUI 的「Save (API Format)」匯出。` |
| 含 `nodes:[...]` 或 `links:[...]` | `這是 ComfyUI UI graph format，本系統只接受 API format。請用 ComfyUI 的「Save (API Format)」按鈕重新匯出。` |
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
| 多個 SaveImage | `workflow 含多個輸出節點（SaveImage × N）。第一版只允許單一輸出，請拆成多個 workflow 或合併。` |
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
| **1** | `services/comfyui/template/{analyzer,allowlist}.py` + 9 個 happy fixture + 6 個 sanitize fail fixture | `pytest tests/comfyui/template/ -q` 全綠；Analyzer 對所有 happy fixture 回傳正確 `class_types` + `fields` |
| **2** | `services/comfyui/template/capability.py` + cache + 3 個 capability fail fixture | Capability 在 mocked client 下能正確分類 SUPPORTED / PARTIAL / UNSUPPORTED |
| **3** | `services/comfyui/template/safety.py` + 5 個 allowlist fail + 2 個 safety fail | 4 個 hard-block 各自有 negative test 證明擋住 |
| **3b** | refactor `services/comfyui/workflow/builder.py` 用 `next_safe_node_id` allocator | builder 既有 test 仍綠；新加 collision regression test |
| **4** | `POST /api/comfyui/templates/preview` + preview_token | E2E test：upload → preview → get token；token 過期 → 401；別 user 拿 token → 403 |
| **5** | `services/comfyui/template/ui_schema.py` + frontend 6 panel | manual UI test：6 panel 分別開合；fill in 後 schema validate |
| **6** | 改造 `POST /api/comfyui/workflows/<id>/run` 加 4-gate | E2E：每 gate 各自 fail 個負面測試；happy path 走完進 ComfyUI queue |

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
5. Phase 4 加 endpoint，**舊 import endpoint 仍 work**（向後兼容）
6. Phase 5 frontend 加新 modal，**舊 generate 介面不動**
7. Phase 6 run gate — 加 feature flag `feature_comfyui_template_importer_strict`，預設 false；驗證一段時間後改 true
8. 全 ship 一個 release 後，下一版才**刪**舊 import endpoint 的 sanitize-only 路徑

---

## 16. 不做的事（再次強調）

- ❌ 自動修復破 JSON（user 要看到完整錯誤）
- ❌ 自動下載缺失模型（admin 才有權，分流到 model download flow）
- ❌ 改變 ComfyUI 的 prompt queue 機制（不動 `execution.py`）
- ❌ 替 user 「智慧化」改 sampler / steps（user 自己決定）
- ❌ AnimateDiff / IPAdapter / FaceDetailer / ReActor 任何一個（第一版）
- ❌ 多輸出分支（第一版）
- ❌ UI graph format 自動轉 API format（user 自己用 ComfyUI export 切換）
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

## 18. 變更履歷

- 2026-05-07 · claude · 初稿
