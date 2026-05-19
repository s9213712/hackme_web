from services.comfyui.execution import collect_output_refs


def test_collect_output_refs_includes_video_audio_and_dedupes_aliases():
    record = {
        "outputs": {
            "1": {
                "videos": [
                    {"filename": "clip.mp4", "subfolder": "run", "type": "output", "format": "mp4"},
                ],
                "gifs": [
                    {"filename": "clip.mp4", "subfolder": "run", "type": "output"},
                    {"filename": "loop.gif", "subfolder": "run", "type": "output"},
                ],
            },
            "2": {
                "audio": [{"filename": "voice.wav", "subfolder": "", "type": "output"}],
                "audios": [{"filename": "voice.wav", "subfolder": "", "type": "output"}],
            },
        }
    }

    refs = collect_output_refs(record)

    assert refs["images"] == []
    assert refs["videos"] == [
        {"filename": "clip.mp4", "subfolder": "run", "type": "output", "format": "mp4"},
        {"filename": "loop.gif", "subfolder": "run", "type": "output"},
    ]
    assert refs["audio"] == [{"filename": "voice.wav", "subfolder": "", "type": "output"}]


def test_collect_output_refs_treats_savevideo_images_as_video_media():
    record = {
        "outputs": {
            "108": {
                "images": [
                    {"filename": "ComfyUI_00001.mp4", "subfolder": "wan", "type": "output"},
                ],
            },
            "214": {
                "images": [
                    {"filename": "ComfyUI_00001.png", "subfolder": "wan", "type": "output"},
                ],
            },
        },
    }
    workflow = {
        "108": {"class_type": "SaveVideo", "inputs": {}, "_meta": {"title": "WAN output"}},
        "214": {"class_type": "PreviewImage", "inputs": {}, "_meta": {"title": "Mask preview"}},
    }

    refs = collect_output_refs(record, workflow=workflow)

    assert refs["videos"] == [
        {
            "filename": "ComfyUI_00001.mp4",
            "subfolder": "wan",
            "type": "output",
            "output_node_id": "108",
            "output_label": "WAN output",
        }
    ]
    assert refs["images"] == []


def test_collect_output_refs_accepts_singular_video_output_key():
    record = {
        "outputs": {
            "75": {
                "video": [
                    {"filename": "ltx_output_00001.mp4", "subfolder": "t2v", "type": "output"},
                ],
            },
        },
    }
    workflow = {
        "75": {"class_type": "SaveVideo", "inputs": {}, "_meta": {"title": "LTX video"}},
    }

    refs = collect_output_refs(record, workflow=workflow)

    assert refs["videos"] == [
        {
            "filename": "ltx_output_00001.mp4",
            "subfolder": "t2v",
            "type": "output",
            "output_node_id": "75",
            "output_label": "LTX video",
        }
    ]
    assert refs["images"] == []
