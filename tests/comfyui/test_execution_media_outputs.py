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
