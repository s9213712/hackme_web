from services.comfyui.template.normalize import convert_ui_graph_to_api_workflow


def test_ui_graph_skips_rgthree_group_bypasser_node():
    workflow = {
        "nodes": [
            {
                "id": 1,
                "type": "Fast Groups Bypasser (rgthree)",
                "inputs": [],
                "outputs": [{"name": "OPT_CONNECTION", "type": "*", "links": []}],
                "widgets_values": [],
            },
            {
                "id": 2,
                "type": "LoadImage",
                "inputs": [],
                "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [10]}],
                "widgets_values": ["source.png", "image"],
            },
            {
                "id": 3,
                "type": "PreviewImage",
                "inputs": [{"name": "images", "type": "IMAGE", "link": 10}],
                "outputs": [],
                "widgets_values": [],
            },
        ],
        "links": [[10, 2, 0, 3, 0, "IMAGE"]],
    }

    converted = convert_ui_graph_to_api_workflow(workflow)

    assert "1" not in converted
    assert {node["class_type"] for node in converted.values()} == {"LoadImage", "PreviewImage"}


def test_ui_graph_subgraph_expansion_allocates_links_after_root_links():
    workflow = {
        "nodes": [
            {
                "id": 10,
                "type": "demo-subgraph",
                "inputs": [{"name": "image", "type": "IMAGE", "link": 101}],
                "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [103]}],
                "widgets_values": [],
            },
            {
                "id": 20,
                "type": "LoadImage",
                "inputs": [],
                "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [101, 102]}],
                "widgets_values": ["source.png", "image"],
            },
            {
                "id": 30,
                "type": "PreviewImage",
                "inputs": [{"name": "images", "type": "IMAGE", "link": 102}],
                "outputs": [],
                "widgets_values": [],
            },
            {
                "id": 40,
                "type": "PreviewImage",
                "inputs": [{"name": "images", "type": "IMAGE", "link": 103}],
                "outputs": [],
                "widgets_values": [],
            },
        ],
        "links": [
            [101, 20, 0, 10, 0, "IMAGE"],
            [102, 20, 0, 30, 0, "IMAGE"],
            [103, 10, 0, 40, 0, "IMAGE"],
        ],
        "definitions": {
            "subgraphs": [
                {
                    "id": "demo-subgraph",
                    "nodes": [
                        {
                            "id": 1,
                            "type": "PreviewImage",
                            "inputs": [{"name": "images", "type": "IMAGE", "link": 100}],
                            "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [99]}],
                            "widgets_values": [],
                        },
                    ],
                    "links": [
                        {"id": 100, "origin_id": -10, "origin_slot": 0, "target_id": 1, "target_slot": 0, "type": "IMAGE"},
                        {"id": 99, "origin_id": 1, "origin_slot": 0, "target_id": -20, "target_slot": 0, "type": "IMAGE"},
                    ],
                },
            ],
        },
    }

    converted = convert_ui_graph_to_api_workflow(workflow)

    assert converted["30"]["inputs"]["images"] == ["20", 0]


def test_ui_graph_resize_image_mask_widget_values_keep_dynamic_order():
    workflow = {
        "nodes": [
            {
                "id": 1,
                "type": "LoadImage",
                "inputs": [],
                "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [10]}],
                "widgets_values": ["source.png", "image"],
            },
            {
                "id": 2,
                "type": "ResizeImageMaskNode",
                "inputs": [
                    {"name": "input", "type": "IMAGE,MASK", "link": 10},
                    {"name": "resize_type.longer_size", "type": "INT", "widget": {"name": "resize_type.longer_size"}, "link": None},
                    {"name": "scale_method", "type": "COMBO", "widget": {"name": "scale_method"}, "link": None},
                ],
                "outputs": [{"name": "resized", "type": "IMAGE", "links": []}],
                "widgets_values": ["scale longer dimension", 1024, "lanczos"],
            },
        ],
        "links": [[10, 1, 0, 2, 0, "IMAGE"]],
    }

    converted = convert_ui_graph_to_api_workflow(workflow)

    assert converted["2"]["inputs"]["resize_type"] == "scale longer dimension"
    assert converted["2"]["inputs"]["resize_type.longer_size"] == 1024
    assert converted["2"]["inputs"]["scale_method"] == "lanczos"


def test_ui_graph_resize_image_mask_dimensions_uses_nested_crop_input():
    workflow = {
        "nodes": [
            {
                "id": 1,
                "type": "LoadImage",
                "inputs": [],
                "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [10]}],
                "widgets_values": ["source.png", "image"],
            },
            {
                "id": 2,
                "type": "ResizeImageMaskNode",
                "inputs": [
                    {"name": "input", "type": "IMAGE,MASK", "link": 10},
                    {"name": "resize_type.width", "type": "INT", "widget": {"name": "resize_type.width"}, "link": None},
                    {"name": "resize_type.height", "type": "INT", "widget": {"name": "resize_type.height"}, "link": None},
                    {"name": "scale_method", "type": "COMBO", "widget": {"name": "scale_method"}, "link": None},
                ],
                "outputs": [{"name": "resized", "type": "IMAGE", "links": []}],
                "widgets_values": ["scale dimensions", 960, 540, "center", "lanczos"],
            },
        ],
        "links": [[10, 1, 0, 2, 0, "IMAGE"]],
    }

    converted = convert_ui_graph_to_api_workflow(workflow)

    assert converted["2"]["inputs"]["resize_type.crop"] == "center"
    assert "crop" not in converted["2"]["inputs"]


def test_ui_graph_resize_image_mask_total_pixels_uses_nested_megapixels_input():
    workflow = {
        "nodes": [
            {
                "id": 1,
                "type": "LoadImage",
                "inputs": [],
                "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [10]}],
                "widgets_values": ["source.png", "image"],
            },
            {
                "id": 2,
                "type": "ResizeImageMaskNode",
                "inputs": [
                    {"name": "input", "type": "IMAGE,MASK", "link": 10},
                ],
                "outputs": [{"name": "resized", "type": "IMAGE", "links": []}],
                "widgets_values": ["scale total pixels", 1.6, "area"],
            },
        ],
        "links": [[10, 1, 0, 2, 0, "IMAGE"]],
    }

    converted = convert_ui_graph_to_api_workflow(workflow)

    assert converted["2"]["inputs"]["resize_type"] == "scale total pixels"
    assert converted["2"]["inputs"]["resize_type.megapixels"] == 1.6
    assert converted["2"]["inputs"]["scale_method"] == "area"


def test_ui_graph_video_widget_values_map_to_current_api_inputs():
    workflow = {
        "nodes": [
            {
                "id": 1,
                "type": "LoadVideo",
                "inputs": [],
                "outputs": [{"name": "VIDEO", "type": "VIDEO", "links": [10]}],
                "widgets_values": ["input.mp4", "image"],
            },
            {
                "id": 2,
                "type": "SaveVideo",
                "inputs": [{"name": "video", "type": "VIDEO", "link": 10}],
                "outputs": [],
                "widgets_values": ["video/ComfyUI", "auto", "auto"],
            },
        ],
        "links": [[10, 1, 0, 2, 0, "VIDEO"]],
    }

    converted = convert_ui_graph_to_api_workflow(workflow)

    assert converted["1"]["inputs"]["file"] == "input.mp4"
    assert converted["2"]["inputs"]["format"] == "auto"
    assert converted["2"]["inputs"]["codec"] == "auto"


def test_ui_graph_group_titles_are_preserved_as_node_metadata():
    workflow = {
        "groups": [
            {"title": "Outer", "bounding": [0, 0, 1000, 1000]},
            {"title": "一次放大", "bounding": [100, 100, 250, 250]},
        ],
        "nodes": [
            {
                "id": 1,
                "type": "LatentUpscaleBy",
                "pos": [150, 150],
                "inputs": [],
                "outputs": [],
                "widgets_values": ["nearest-exact", 2],
            },
            {
                "id": 2,
                "type": "UpscaleModelLoader",
                "title": "二次放大",
                "pos": [700, 700],
                "inputs": [],
                "outputs": [],
                "widgets_values": ["ESRGAN/model.safetensors"],
            },
        ],
        "links": [],
    }

    converted = convert_ui_graph_to_api_workflow(workflow)

    assert converted["1"]["_meta"] == {"group_title": "一次放大", "title": "一次放大"}
    assert converted["2"]["_meta"] == {"group_title": "Outer", "title": "二次放大"}


def test_subgraph_inputs_match_by_name_not_position():
    workflow = {
        "nodes": [
            {
                "id": 10,
                "type": "video-subgraph",
                "inputs": [{"name": "video", "type": "VIDEO", "link": 101}],
                "outputs": [],
                "widgets_values": [],
            },
            {
                "id": 20,
                "type": "LoadVideo",
                "inputs": [],
                "outputs": [{"name": "VIDEO", "type": "VIDEO", "links": [101]}],
                "widgets_values": ["input.mp4", "image"],
            },
        ],
        "links": [[101, 20, 0, 10, 0, "VIDEO"]],
        "definitions": {
            "subgraphs": [
                {
                    "id": "video-subgraph",
                    "inputs": [
                        {"name": "vae_name", "type": "COMBO", "linkIds": [10]},
                        {"name": "video", "type": "VIDEO", "linkIds": [11]},
                    ],
                    "nodes": [
                        {
                            "id": 1,
                            "type": "VAELoader",
                            "inputs": [{"name": "vae_name", "type": "COMBO", "widget": {"name": "vae_name"}, "link": 10}],
                            "outputs": [{"name": "VAE", "type": "VAE", "links": []}],
                            "widgets_values": ["default.vae"],
                        },
                        {
                            "id": 2,
                            "type": "GetVideoComponents",
                            "inputs": [{"name": "video", "type": "VIDEO", "link": 11}],
                            "outputs": [],
                            "widgets_values": [],
                        },
                    ],
                    "links": [
                        {"id": 10, "origin_id": -10, "origin_slot": 0, "target_id": 1, "target_slot": 0, "type": "COMBO"},
                        {"id": 11, "origin_id": -10, "origin_slot": 1, "target_id": 2, "target_slot": 0, "type": "VIDEO"},
                    ],
                },
            ],
        },
    }

    converted = convert_ui_graph_to_api_workflow(workflow)

    vae_loader = next(node for node in converted.values() if node["class_type"] == "VAELoader")
    video_node = next(node for node in converted.values() if node["class_type"] == "GetVideoComponents")
    assert vae_loader["inputs"]["vae_name"] == "default.vae"
    assert video_node["inputs"]["video"] == ["20", 0]
