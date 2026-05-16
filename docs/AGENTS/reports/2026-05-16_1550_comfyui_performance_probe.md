# 2026-05-16 ComfyUI Performance Probe

## Findings

### High - Large-model load can stall ComfyUI and visibly slow the main server

After pointing hackme_web at the running ComfyUI backend on `localhost:8189`,
the live probe submitted a minimal `txt2img` job: `512x512`, `2` steps,
batch size `1`. The job did not finish within the 60 second probe timeout and
remained stuck at node `4`, progress `0%`, phase `running`.

Impact:

- A very small generation can stay in model-load / initialization for over a
  minute on this host.
- During the stuck generation, unrelated `GET /api/version` latency rose from
  about `0.03s` idle to `1.5s-4.8s`.
- `GET /api/comfyui/jobs/<job_id>` took `13.64s` while still returning
  `status=running`.
- `POST /api/comfyui/interrupt` did not return to the client within a 20 second
  timeout, although the server eventually logged HTTP 200 later.
- ComfyUI RSS grew from roughly `0.9GB` idle to about `1.98GB`; GPU utilization
  stayed near `0%` and VRAM stayed low, which points to model loading /
  CPU-RAM / disk I/O / low-VRAM offload rather than active GPU inference.

Evidence:

- `/tmp/hackme_comfyui_feature_probe_8189.json`
- ComfyUI job id: `cc322cd1248b946a949a17ba`
- `curl /api/version` during load: up to `4.848252s`
- `curl /api/comfyui/jobs/cc322cd1248b946a949a17ba`: `13.642094s`
- ComfyUI log: `/mnt/d/share/ComfyUI_windows_portable/ComfyUI/user/comfyui_8189.log`

Likely cause:

- The host has a 4GB RTX 3050 Laptop GPU.
- ComfyUI runs with `--lowvram --force-fp16 --use-split-cross-attention`.
- Models and ComfyUI files are under `/mnt/d/share/ComfyUI_windows_portable`,
  so large checkpoint loading crosses the WSL Windows-mounted filesystem.
- The log shows slow startup/import characteristics, including ComfyUI-Manager
  prestartup `85.1s` and import `22.8s`.

This looks consistent with large-model loading under constrained VRAM rather
than normal GPU generation.

### Medium - Incorrect ComfyUI port fails cleanly and quickly

Before updating the test runtime to `8189`, hackme_web was still configured for
`localhost:8192`. `GET /api/comfyui/status` returned HTTP 200 with
`available=false` and `Connection refused` quickly. This is acceptable behavior
for a wrong/offline backend and did not block the main server.

Evidence:

- `/tmp/hackme_comfyui_feature_probe_5000.json`

## Passes

- Standalone Playwright workflow-builder check passed:
  `python3 scripts/testing/playwright_comfyui_workflow_builder_check.py`
- After killing the stuck ComfyUI process, `GET /api/version` returned to
  `0.029831s`.
- GPU memory was released after stopping ComfyUI: `nvidia-smi` showed no
  running GPU processes and about `110MiB / 4096MiB` in use.

## Cleanup

The stuck ComfyUI process `PID 1565884` was stopped after interrupt proved too
slow. Port `8189` is no longer listening. The hackme_web test server on
`https://127.0.0.1:5000` remained up.

## Recommended Hardening

- Treat ComfyUI generation as an external long-running worker. Do not let any
  request path synchronously wait on model loading, generation, or interrupt.
- Add short backend timeouts for status, queue, job polling, and interrupt
  calls; stale job state should be marked `backend_unresponsive`.
- Reduce job polling write frequency while a job remains at the same progress
  state to avoid extra DB/log churn.
- Prefer moving frequently used checkpoints from `/mnt/d` to native WSL/Linux
  storage or a faster local model cache.
- For 4GB VRAM, use smaller/default-safe checkpoints and expose a root warning
  when a selected model is likely to exceed VRAM and trigger heavy offload.

## Follow-up Implemented

- `POST /api/comfyui/generate` now always returns a background job instead of
  waiting synchronously for generation.
- Generation, backend HTTP calls, status checks and interrupt calls now have
  bounded configurable timeouts.
- Running jobs that stop reporting progress are surfaced as
  `backend_unresponsive` in the job status payload.
- Job Center progress writes are throttled to reduce DB churn during repeated
  progress polling.
- Deployment guidance is documented in
  `docs/comfyui/COMFYUI_PERFORMANCE_HARDENING.md`, including moving common
  checkpoints off `/mnt/d` and onto native Linux storage.
