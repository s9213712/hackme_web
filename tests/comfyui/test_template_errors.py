"""§11 errors catalog regression."""

import pytest

from services.comfyui.template import errors


def test_stage_tags_are_ascii_for_log_grep():
    """Stage tags appear in audit detail / API stage field; keep them ASCII so
    operator log greps don't depend on Unicode normalization."""
    for name in dir(errors.Stage):
        if name.startswith("_"):
            continue
        value = getattr(errors.Stage, name)
        assert isinstance(value, str)
        assert value.encode("ascii", "ignore").decode() == value, (
            f"Stage.{name}={value!r} is not ASCII"
        )


def test_template_error_format_substitutes_named_keys():
    e = errors.PARSE_MULTIPART_OVERSIZE
    assert e.format(max_kb=256) == "workflow 大小超過 256KB 上限"


def test_template_error_format_falls_back_when_keys_missing():
    e = errors.PARSE_MULTIPART_OVERSIZE
    # Don't pass max_kb at all → returns the raw template instead of crashing.
    assert "{max_kb}" in e.format()


def test_parse_json_decode_renders_with_detail_and_line():
    msg = errors.PARSE_JSON_DECODE.format(detail="Expecting value", line=3)
    assert "格式錯誤" in msg
    assert "Expecting value" in msg
    assert "行 3" in msg


def test_allowlist_denied_classes_message():
    msg = errors.ALLOWLIST_DENIED_CLASSES.format(denied=["ReActorFaceSwap"])
    assert "明確拒絕" in msg
    assert "ReActorFaceSwap" in msg


def test_capability_unsupported_message():
    msg = errors.CAPABILITY_UNSUPPORTED.format(unsupported=["KSamplerAdvanced"])
    assert "本地 ComfyUI" in msg
    assert "KSamplerAdvanced" in msg


def test_token_missing_and_invalid_have_distinct_stage_tags():
    """Operator audit needs to distinguish "no token sent" from "token consumed/expired"."""
    assert errors.TOKEN_MISSING.stage == errors.Stage.TOKEN
    assert errors.TOKEN_INVALID.stage == errors.Stage.TOKEN_INVALID


def test_gate_message_helpers_pair_tag_with_localized_string():
    stage, msg = errors.gate2_capability_msg(["X", "Y"])
    assert stage == errors.Stage.GATE2_CAPABILITY
    assert "X" in msg and "Y" in msg
    stage, msg = errors.gate3_allowlist_msg("custom blocker")
    assert stage == errors.Stage.GATE3_ALLOWLIST
    assert msg == "custom blocker"


def test_all_template_errors_carry_a_stage_tag_present_in_stage_class():
    """No catalog entry may invent a stage tag outside the Stage namespace."""
    valid_stages = {
        getattr(errors.Stage, name)
        for name in dir(errors.Stage)
        if not name.startswith("_")
    }
    for name in dir(errors):
        value = getattr(errors, name)
        if isinstance(value, errors.TemplateError):
            assert value.stage in valid_stages, f"{name}.stage={value.stage!r} not registered"


def test_all_catalog_messages_are_zh():
    """Spot-check that every catalog string contains at least one Chinese
    character — accidentally typing an English-only message would silently
    break the localization invariant."""
    chinese_required = {
        "PARSE_BODY_NOT_JSON",
        "ALLOWLIST_DENIED_CLASSES",
        "CAPABILITY_UNSUPPORTED",
        "TOKEN_MISSING",
        "TOKEN_INVALID",
        "TITLE_BLANK",
        "INPUTS_MISSING",
    }
    for name in chinese_required:
        e = getattr(errors, name)
        assert any(0x4E00 <= ord(ch) <= 0x9FFF for ch in e.template), (
            f"{name} template has no Han characters: {e.template!r}"
        )
