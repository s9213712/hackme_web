"""Regression for services.comfyui.execution.generate_image()."""

from services.comfyui import execution as comfy_execution


def test_generate_image_accepts_generate_from_workflow_func():
    called = {}

    def _build_generation_workflow(params):
        called["params"] = dict(params)
        return {"3": {"class_type": "KSampler", "inputs": {"steps": params["steps"]}}}

    def _generate_from_workflow(workflow, *, timeout_seconds=1800, expected_count=1, progress_callback=None):
        called["workflow"] = workflow
        called["timeout_seconds"] = timeout_seconds
        called["expected_count"] = expected_count
        if progress_callback:
            progress_callback({"phase": "running", "percent": 50})
        return {"prompt_id": "p1", "images": [{"image_ref": {"filename": "x.png", "subfolder": "", "type": "output"}}]}

    progress_events = []
    result = comfy_execution.generate_image(
        client=object(),
        params={"steps": 30, "batch_size": 2},
        timeout_seconds=77,
        progress_callback=progress_events.append,
        build_generation_workflow_func=_build_generation_workflow,
        generate_from_workflow_func=_generate_from_workflow,
        error_cls=RuntimeError,
    )

    assert called["params"] == {"steps": 30, "batch_size": 2}
    assert called["workflow"]["3"]["inputs"]["steps"] == 30
    assert called["timeout_seconds"] == 77
    assert called["expected_count"] == 2
    assert progress_events == [{"phase": "running", "percent": 50}]
    assert result["prompt_id"] == "p1"
