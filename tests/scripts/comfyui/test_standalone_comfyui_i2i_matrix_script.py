from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "comfyui" / "standalone_comfyui_i2i_matrix.py"


def test_standalone_comfyui_i2i_matrix_help_lists_core_modes():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--interactive" in result.stdout
    assert "--comfyui-url" in result.stdout
    assert "--controlnet-type" in result.stdout
    assert "--controlnet-model" in result.stdout
    assert "--upscale-factor" in result.stdout
    assert "--outpaint-top" in result.stdout
    assert "--outpaint-bottom" in result.stdout
    assert "--only-case" in result.stdout
    assert "--source-image-path" in result.stdout
    assert "--case-prompt" in result.stdout
    assert "--case-denoise" in result.stdout
    assert "--mask-shape" in result.stdout
    assert "--inpaint-method" in result.stdout
    assert "--differential-diffusion" in result.stdout
    assert "--blend-image-path" in result.stdout
    assert "--blend-denoise" in result.stdout
    assert "--style-image-path" in result.stdout
    assert "--ipadapter-preset" in result.stdout
    assert "kimono_clothes" in result.stdout


def test_standalone_comfyui_i2i_matrix_documents_i2i_cases():
    text = SCRIPT.read_text(encoding="utf-8")
    for keyword in (
        "img2img_redraw_sunset",
        "inpaint_remove_repair",
        "inpaint_replace_edit",
        "outpaint_expand_beach",
        "controlnet_copy_composition",
        "upscale_redraw_imagescale",
        "two_image_blend_mix",
        "ipadapter_style_reference",
        "ipadapter_inpaint_reference",
    ):
        assert keyword in text
