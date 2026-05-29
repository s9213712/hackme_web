#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROBE_SCRIPT="${PROBE_SCRIPT:-${SCRIPT_DIR}/standalone_hf_diffusers_txt2img.py}"
OUT_ROOT="${OUT_ROOT:-/tmp/hackme_hf_diffusers_repo_smoke}"
HF_CACHE_ROOT="${HF_CACHE_ROOT:-}"
HF_TOKEN_ENV="${HF_TOKEN_ENV:-HF_TOKEN}"
HF_TOKEN_FILE=""
HF_TOKEN_VALUE=""
HF_TOKEN_TEMP_FILE=""
HF_TOKEN_STDIN=0
DEVICE="${DEVICE:-cuda}"
DTYPE_WAS_SET=0
if [[ -n "${DTYPE+x}" ]]; then
  DTYPE_WAS_SET=1
fi
DTYPE="${DTYPE:-float16}"
DEVICE_MAP_WAS_SET=0
if [[ -n "${DEVICE_MAP+x}" ]]; then
  DEVICE_MAP_WAS_SET=1
fi
DEVICE_MAP="${DEVICE_MAP:-disabled}"
PIPELINE_LOADER_WAS_SET=0
if [[ -n "${PIPELINE_LOADER+x}" ]]; then
  PIPELINE_LOADER_WAS_SET=1
fi
PIPELINE_LOADER="${PIPELINE_LOADER:-diffusion}"
DTYPE_KWARG_WAS_SET=0
if [[ -n "${DTYPE_KWARG+x}" ]]; then
  DTYPE_KWARG_WAS_SET=1
fi
DTYPE_KWARG="${DTYPE_KWARG:-torch_dtype}"
MODEL_CARD_HINTS="${MODEL_CARD_HINTS:-auto}"
PREFLIGHT_ONLY=0
WIDTH="${WIDTH:-1024}"
HEIGHT="${HEIGHT:-1024}"
STEPS="${STEPS:-20}"
CFG="${CFG:-6.5}"
SEED="${SEED:-20260529}"
PROMPT="${PROMPT:-anime style, by ogipote, adult woman, 1girl, solo, cat girl, bikini, lying on a beach towel on the beach, sunny day, ocean background, detailed anime illustration}"
NEGATIVE_PROMPT="${NEGATIVE_PROMPT:-child, minor, underage, loli, teen, nude, naked, explicit, low quality, worst quality, blurry, watermark, text, bad anatomy, bad hand, bad fingers, bad legs, extra fingers, missing fingers, monochrome}"
TWO_GIRLS_PROMPT="${TWO_GIRLS_PROMPT:-adult women, fully clothed, by ogipote, 2girls, girls love, kiss, saliva, maid uniform, cat ears, cat tail}"
TWO_GIRLS_NEGATIVE_PROMPT="${TWO_GIRLS_NEGATIVE_PROMPT:-child, minor, underage, loli, teen, nude, naked, explicit, low quality, blurry, watermark, distorted, extra fingers, missing fingers, monochrome, text, bad hand, bad fingers, bad legs, bad anatomy}"
PROMPT_SUITE="${PROMPT_SUITE:-dual}"
PROMPT_SUITE_SET=0
CUSTOM_PROMPT=0
CUSTOM_NEGATIVE_PROMPT=0
REPOS=()

usage() {
  cat <<'EOF'
Usage: hf_diffusers_repo_smoke.sh [options] [repo[=variant] ...]

Options:
  --python PATH             Python executable.
  --probe-script PATH       standalone_hf_diffusers_txt2img.py path.
  --out-root PATH           Output directory root.
  --hf-cache-root PATH      Hugging Face cache root.
  --hf-token-env NAME       Read token from this environment variable.
  --hf-token-file PATH      Read token from file, passed through to probe.
  --hf-token-stdin          Read one token line from stdin.
  --device VALUE            cuda, cpu, auto, etc.
  --dtype VALUE             float16, bfloat16, float32, auto.
  --dtype-kwarg VALUE       torch_dtype or dtype. Model-card hints may override if unset.
  --device-map VALUE        disabled, auto, balanced, etc.
  --pipeline-loader VALUE   diffusion or auto. Defaults to diffusion unless model-card hints override.
  --model-card-hints VALUE  auto, off, or force. Defaults to auto.
  --preflight-only          Verify cache/token/import environment without loading.
  --width N --height N --steps N --cfg N --seed N
  --prompt TEXT
  --negative-prompt TEXT
  --prompt-suite VALUE     dual or single. Defaults to dual unless --prompt is supplied.

Repo arguments may be repo=variant. Use an empty variant by omitting =variant.
Env/stdin tokens are bridged through a temporary hidden token file so Windows
python.exe launched from WSL can read them; the file is removed on exit.
Default outputs are copied to OUT_ROOT/<repo-slug>.png. Dual prompt mode also
copies the legacy 2girls prompt to OUT_ROOT/<repo-slug>_2girls.png.
EOF
}

cleanup_token_temp_file() {
  if [[ -n "$HF_TOKEN_TEMP_FILE" && -f "$HF_TOKEN_TEMP_FILE" ]]; then
    rm -f -- "$HF_TOKEN_TEMP_FILE"
  fi
}

trap cleanup_token_temp_file EXIT INT TERM

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python) PYTHON_BIN="$2"; shift 2 ;;
    --probe-script) PROBE_SCRIPT="$2"; shift 2 ;;
    --out-root) OUT_ROOT="$2"; shift 2 ;;
    --hf-cache-root) HF_CACHE_ROOT="$2"; shift 2 ;;
    --hf-token-env) HF_TOKEN_ENV="$2"; shift 2 ;;
    --hf-token-file) HF_TOKEN_FILE="$2"; shift 2 ;;
    --hf-token-stdin) HF_TOKEN_STDIN=1; shift ;;
    --device) DEVICE="$2"; shift 2 ;;
    --dtype) DTYPE="$2"; DTYPE_WAS_SET=1; shift 2 ;;
    --dtype-kwarg) DTYPE_KWARG="$2"; DTYPE_KWARG_WAS_SET=1; shift 2 ;;
    --device-map) DEVICE_MAP="$2"; DEVICE_MAP_WAS_SET=1; shift 2 ;;
    --pipeline-loader) PIPELINE_LOADER="$2"; PIPELINE_LOADER_WAS_SET=1; shift 2 ;;
    --model-card-hints) MODEL_CARD_HINTS="$2"; shift 2 ;;
    --preflight-only) PREFLIGHT_ONLY=1; shift ;;
    --width) WIDTH="$2"; shift 2 ;;
    --height) HEIGHT="$2"; shift 2 ;;
    --steps) STEPS="$2"; shift 2 ;;
    --cfg) CFG="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --prompt) PROMPT="$2"; CUSTOM_PROMPT=1; shift 2 ;;
    --negative-prompt) NEGATIVE_PROMPT="$2"; CUSTOM_NEGATIVE_PROMPT=1; shift 2 ;;
    --prompt-suite) PROMPT_SUITE="$2"; PROMPT_SUITE_SET=1; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    -*) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    *) REPOS+=("$1"); shift ;;
  esac
done

if [[ "$HF_TOKEN_STDIN" == "1" ]]; then
  restore_echo=0
  if [[ -t 0 ]]; then
    stty -echo
    restore_echo=1
    echo "hf_token_stdin_ready" >&2
  fi
  IFS= read -r HF_TOKEN_VALUE || HF_TOKEN_VALUE=""
  if [[ "$restore_echo" == "1" ]]; then
    stty echo
    printf '\n'
  fi
fi

if [[ ${#REPOS[@]} -eq 0 ]]; then
  REPOS=(
    "Heartsync/NSFW-Uncensored=fp16"
    "John6666/perfect-rsb-mix-illustrious-real-anime-sfw-nsfw-definitive-iota-sdxl"
    "cagliostrolab/animagine-xl-4.0"
  )
fi

if [[ "$PROMPT_SUITE_SET" == "0" && ( "$CUSTOM_PROMPT" == "1" || "$CUSTOM_NEGATIVE_PROMPT" == "1" ) ]]; then
  PROMPT_SUITE="single"
fi

case "$PROMPT_SUITE" in
  single)
    PROMPT_LABELS=("default")
    PROMPTS=("$PROMPT")
    NEGATIVE_PROMPTS=("$NEGATIVE_PROMPT")
    ;;
  dual)
    PROMPT_LABELS=("default" "2girls")
    PROMPTS=("$PROMPT" "$TWO_GIRLS_PROMPT")
    NEGATIVE_PROMPTS=("$NEGATIVE_PROMPT" "$TWO_GIRLS_NEGATIVE_PROMPT")
    ;;
  *)
    echo "Unsupported --prompt-suite: $PROMPT_SUITE" >&2
    exit 2
    ;;
esac

slugify_repo() {
  printf '%s' "$1" | tr '/' '_' | tr -cd 'A-Za-z0-9._-'
}

windows_path_for_python() {
  local value="$1"
  if [[ "$PYTHON_BIN" == *.exe && "$value" =~ ^/mnt/([A-Za-z])/(.*)$ ]]; then
    local drive="${BASH_REMATCH[1]}"
    local rest="${BASH_REMATCH[2]}"
    drive="$(printf '%s' "$drive" | tr '[:lower:]' '[:upper:]')"
    printf '%s:/%s' "$drive" "$rest"
  else
    printf '%s' "$value"
  fi
}

mkdir -p "$OUT_ROOT"
PYTHON_PROBE_SCRIPT="$(windows_path_for_python "$PROBE_SCRIPT")"

if [[ -z "$HF_TOKEN_FILE" ]]; then
  if [[ -z "$HF_TOKEN_VALUE" && -n "$HF_TOKEN_ENV" && -n "${!HF_TOKEN_ENV:-}" ]]; then
    HF_TOKEN_VALUE="${!HF_TOKEN_ENV}"
  fi
  if [[ -n "$HF_TOKEN_VALUE" ]]; then
    HF_TOKEN_TEMP_FILE="$(mktemp "${OUT_ROOT}/.hf_token.XXXXXX")"
    chmod 600 "$HF_TOKEN_TEMP_FILE" 2>/dev/null || true
    printf '%s' "$HF_TOKEN_VALUE" > "$HF_TOKEN_TEMP_FILE"
    HF_TOKEN_FILE="$HF_TOKEN_TEMP_FILE"
  fi
fi

for entry in "${REPOS[@]}"; do
  repo="${entry%%=*}"
  variant=""
  if [[ "$entry" == *"="* ]]; then
    variant="${entry#*=}"
  fi
  slug="$(slugify_repo "$repo")"
  if [[ -n "$variant" ]]; then
    slug="${slug}_${variant}"
  else
    slug="${slug}_default"
  fi
  for index in "${!PROMPT_LABELS[@]}"; do
    prompt_label="${PROMPT_LABELS[$index]}"
    prompt_text="${PROMPTS[$index]}"
    negative_text="${NEGATIVE_PROMPTS[$index]}"
    output_slug="$slug"
    if [[ "$prompt_label" != "default" ]]; then
      output_slug="${slug}_${prompt_label}"
    fi
    out_dir="${OUT_ROOT}/${output_slug}"
    mkdir -p "$out_dir"
    args=(
      "$PYTHON_PROBE_SCRIPT"
      --model "$repo"
      --variant "$variant"
      --prompt "$prompt_text"
      --negative-prompt "$negative_text"
      --width "$WIDTH"
      --height "$HEIGHT"
      --steps "$STEPS"
      --cfg "$CFG"
      --seed "$SEED"
      --device "$DEVICE"
      --model-card-hints "$MODEL_CARD_HINTS"
      --low-cpu-mem-usage true
      --hf-token-env "$HF_TOKEN_ENV"
      --out-dir "$out_dir"
      --out-json "${out_dir}/hf_diffusers_report.json"
    )
    if [[ "$DTYPE_WAS_SET" == "1" ]]; then
      args+=(--dtype "$DTYPE")
    fi
    if [[ "$DTYPE_KWARG_WAS_SET" == "1" ]]; then
      args+=(--dtype-kwarg "$DTYPE_KWARG")
    fi
    if [[ "$DEVICE_MAP_WAS_SET" == "1" ]]; then
      args+=(--device-map "$DEVICE_MAP")
    fi
    if [[ "$PIPELINE_LOADER_WAS_SET" == "1" ]]; then
      args+=(--pipeline-loader "$PIPELINE_LOADER")
    fi
    if [[ -n "$HF_CACHE_ROOT" ]]; then
      args+=(--hf-cache-root "$HF_CACHE_ROOT")
    fi
    if [[ -n "$HF_TOKEN_FILE" ]]; then
      args+=(--hf-token-file "$HF_TOKEN_FILE")
    fi
    if [[ "$PREFLIGHT_ONLY" == "1" ]]; then
      args+=(--preflight-only)
    fi
    token_state="unset"
    if [[ -n "$HF_TOKEN_FILE" || ( -n "$HF_TOKEN_ENV" && -n "${!HF_TOKEN_ENV:-}" ) ]]; then
      token_state="set"
    fi
    echo "=== ${repo} variant=${variant:-default} prompt=${prompt_label} token=${token_state} ==="
    "$PYTHON_BIN" "${args[@]}"
    if [[ -s "${out_dir}/hf_diffusers.png" ]]; then
      cp -f "${out_dir}/hf_diffusers.png" "${OUT_ROOT}/${output_slug}.png"
      echo "named_output=${OUT_ROOT}/${output_slug}.png"
    fi
  done
done
