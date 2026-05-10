'use strict';

(function () {
  const STORAGE_KEY = "hackme_comfyui_workflow_visual_builder";
  const RESULT_KEY = "hackme_comfyui_workflow_editor_result";
  const INPUT_KEY = "hackme_comfyui_workflow_editor_input";
  const UNKNOWN_NODE_TYPE = "__UnknownCustomNode__";
  const $ = (id) => document.getElementById(id);

  const NODE_DEFS = {
    CheckpointLoaderSimple: {
      label: "Checkpoint Loader",
      inputs: { ckpt_name: { type: "text", label: "Checkpoint" } },
      outputs: ["MODEL", "CLIP", "VAE"],
    },
    CLIPTextEncode: {
      label: "Prompt Encoder",
      inputs: { clip: { type: "link", label: "CLIP" }, text: { type: "textarea", label: "提示詞" } },
      outputs: ["CONDITIONING"],
    },
    LoraLoader: {
      label: "LoRA Loader",
      inputs: {
        model: { type: "link", label: "MODEL" },
        clip: { type: "link", label: "CLIP" },
        lora_name: { type: "text", label: "LoRA" },
        strength_model: { type: "number", label: "Model 強度", step: "0.05" },
        strength_clip: { type: "number", label: "CLIP 強度", step: "0.05" },
      },
      outputs: ["MODEL", "CLIP"],
    },
    VAELoader: {
      label: "VAE Loader",
      inputs: { vae_name: { type: "text", label: "VAE" } },
      outputs: ["VAE"],
    },
    EmptyLatentImage: {
      label: "Empty Latent",
      inputs: {
        width: { type: "number", label: "寬", step: "8" },
        height: { type: "number", label: "高", step: "8" },
        batch_size: { type: "number", label: "張數", step: "1" },
      },
      outputs: ["LATENT"],
    },
    LoadImage: {
      label: "Load Image",
      inputs: { image: { type: "text", label: "圖片檔名 / image ref" } },
      outputs: ["IMAGE", "MASK"],
    },
    LoadImageMask: {
      label: "Load Mask",
      inputs: {
        image: { type: "text", label: "遮罩檔名 / mask ref" },
        channel: { type: "text", label: "Channel" },
      },
      outputs: ["IMAGE", "MASK"],
    },
    VAEEncode: {
      label: "VAE Encode",
      inputs: { pixels: { type: "link", label: "IMAGE" }, vae: { type: "link", label: "VAE" } },
      outputs: ["LATENT"],
    },
    VAEEncodeForInpaint: {
      label: "VAE Encode Inpaint",
      inputs: {
        pixels: { type: "link", label: "IMAGE" },
        vae: { type: "link", label: "VAE" },
        mask: { type: "link", label: "MASK" },
        grow_mask_by: { type: "number", label: "Mask grow", step: "1" },
      },
      outputs: ["LATENT"],
    },
    KSampler: {
      label: "KSampler",
      inputs: {
        model: { type: "link", label: "MODEL" },
        positive: { type: "link", label: "正向 CONDITIONING" },
        negative: { type: "link", label: "負向 CONDITIONING" },
        latent_image: { type: "link", label: "LATENT" },
        seed: { type: "number", label: "Seed", step: "1" },
        steps: { type: "number", label: "Steps", step: "1" },
        cfg: { type: "number", label: "CFG", step: "0.5" },
        sampler_name: { type: "text", label: "Sampler" },
        scheduler: { type: "text", label: "Scheduler" },
        denoise: { type: "number", label: "Denoise", step: "0.05" },
      },
      outputs: ["LATENT"],
    },
    KSamplerAdvanced: {
      label: "KSampler Advanced",
      inputs: {
        model: { type: "link", label: "MODEL" },
        positive: { type: "link", label: "正向 CONDITIONING" },
        negative: { type: "link", label: "負向 CONDITIONING" },
        latent_image: { type: "link", label: "LATENT" },
        add_noise: { type: "text", label: "Add noise" },
        noise_seed: { type: "number", label: "Noise seed", step: "1" },
        steps: { type: "number", label: "Steps", step: "1" },
        cfg: { type: "number", label: "CFG", step: "0.5" },
        sampler_name: { type: "text", label: "Sampler" },
        scheduler: { type: "text", label: "Scheduler" },
        start_at_step: { type: "number", label: "Start step", step: "1" },
        end_at_step: { type: "number", label: "End step", step: "1" },
        return_with_leftover_noise: { type: "text", label: "Return leftover noise" },
      },
      outputs: ["LATENT"],
    },
    VAEDecode: {
      label: "VAE Decode",
      inputs: { samples: { type: "link", label: "LATENT" }, vae: { type: "link", label: "VAE" } },
      outputs: ["IMAGE"],
    },
    SaveImage: {
      label: "Save Image",
      inputs: { images: { type: "link", label: "IMAGE" }, filename_prefix: { type: "text", label: "檔名前綴" } },
      outputs: [],
    },
    ControlNetLoader: {
      label: "ControlNet Loader",
      inputs: { control_net_name: { type: "text", label: "ControlNet" } },
      outputs: ["CONTROL_NET"],
    },
    ControlNetApplyAdvanced: {
      label: "ControlNet Apply Advanced",
      inputs: {
        positive: { type: "link", label: "正向 CONDITIONING" },
        negative: { type: "link", label: "負向 CONDITIONING" },
        control_net: { type: "link", label: "CONTROL_NET" },
        image: { type: "link", label: "IMAGE" },
        strength: { type: "number", label: "強度", step: "0.05" },
        start_percent: { type: "number", label: "起始比例", step: "0.05" },
        end_percent: { type: "number", label: "結束比例", step: "0.05" },
      },
      outputs: ["positive", "negative"],
    },
    ImagePadForOutpaint: {
      label: "Outpaint Pad",
      inputs: {
        image: { type: "link", label: "IMAGE" },
        left: { type: "number", label: "Left", step: "8" },
        top: { type: "number", label: "Top", step: "8" },
        right: { type: "number", label: "Right", step: "8" },
        bottom: { type: "number", label: "Bottom", step: "8" },
        feathering: { type: "number", label: "Feathering", step: "1" },
      },
      outputs: ["IMAGE"],
    },
    UpscaleModelLoader: {
      label: "Upscale Loader",
      inputs: { model_name: { type: "text", label: "Upscale 模型" } },
      outputs: ["UPSCALE_MODEL"],
    },
    ImageUpscaleWithModel: {
      label: "Image Upscale",
      inputs: { upscale_model: { type: "link", label: "UPSCALE_MODEL" }, image: { type: "link", label: "IMAGE" } },
      outputs: ["IMAGE"],
    },
  };

  let selectedId = null;
  let dragState = null;
  let connectState = null;
  let lastImportWarnings = [];
  let workflow = loadState();

  function isUnknownNode(node) {
    return node?.type === UNKNOWN_NODE_TYPE;
  }

  function nodeDef(nodeOrType) {
    const node = typeof nodeOrType === "object" ? nodeOrType : null;
    const type = node ? node.type : String(nodeOrType || "");
    if (type === UNKNOWN_NODE_TYPE) {
      return {
        label: `Custom: ${node?.originalType || "Unknown"}`,
        inputs: node?.inputSpecs || {},
        outputs: Array.isArray(node?.outputs) && node.outputs.length ? node.outputs : ["OUT0", "OUT1", "OUT2", "OUT3"],
      };
    }
    return NODE_DEFS[type] || null;
  }

  function html(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[ch]));
  }

  function cssIdent(value) {
    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(String(value));
    return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  }

  function uid() {
    return `n_${Math.random().toString(36).slice(2, 9)}`;
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function unknownInputSpecs(rawInputs = {}) {
    const specs = {};
    Object.entries(rawInputs || {}).forEach(([key, value]) => {
      specs[key] = Array.isArray(value)
        ? { type: "link", label: key }
        : { type: typeof value === "number" ? "number" : "text", label: key };
    });
    return specs;
  }

  function unknownOutputs(maxIndex = 3) {
    const count = Math.max(4, Math.min(12, Number(maxIndex || 0) + 1));
    return Array.from({ length: count }, (_item, index) => `OUT${index}`);
  }

  function defaultInputs(type, node = null) {
    if (type === UNKNOWN_NODE_TYPE) return { ...(node?.inputs || {}) };
    const inputs = {};
    Object.entries(NODE_DEFS[type]?.inputs || {}).forEach(([key, spec]) => {
      if (spec.type === "link") return;
      if (key === "text") inputs[key] = "";
      else if (key === "width" || key === "height") inputs[key] = 1024;
      else if (key === "batch_size") inputs[key] = 1;
      else if (key === "steps") inputs[key] = 20;
      else if (key === "cfg") inputs[key] = 7;
      else if (key === "seed") inputs[key] = 0;
      else if (key === "noise_seed") inputs[key] = 0;
      else if (key === "start_at_step") inputs[key] = 0;
      else if (key === "end_at_step") inputs[key] = 20;
      else if (key === "denoise") inputs[key] = 1;
      else if (key === "strength" || key === "strength_model" || key === "strength_clip" || key === "end_percent") inputs[key] = 1;
      else if (key === "start_percent") inputs[key] = 0;
      else if (key === "grow_mask_by") inputs[key] = 6;
      else if (key === "left" || key === "top" || key === "right" || key === "bottom") inputs[key] = 0;
      else if (key === "feathering") inputs[key] = 40;
      else if (key === "add_noise" || key === "return_with_leftover_noise") inputs[key] = "enable";
      else if (key === "channel") inputs[key] = "alpha";
      else if (key === "sampler_name") inputs[key] = "euler";
      else if (key === "scheduler") inputs[key] = "normal";
      else if (key === "filename_prefix") inputs[key] = "hackme_web";
      else inputs[key] = "";
    });
    return inputs;
  }

  function emptyState() {
    return { name: "", description: "", project_version: "", comfyui_version: "", workflow_schema_version: "1", nodes: [], edges: [], warnings: [] };
  }

  function normalizeState(raw) {
    const safe = raw && typeof raw === "object" ? raw : {};
    const normalizedNodes = Array.isArray(safe.nodes) ? safe.nodes.filter((node) => node && (NODE_DEFS[node.type] || node.type === UNKNOWN_NODE_TYPE)).map((node) => {
      const type = String(node.type);
      const def = nodeDef(node);
      const normalized = {
        id: String(node.id || uid()),
        type,
        label: String(node.label || def?.label || type),
        x: Number.isFinite(Number(node.x)) ? Number(node.x) : 80,
        y: Number.isFinite(Number(node.y)) ? Number(node.y) : 80,
        inputs: { ...defaultInputs(type, node), ...(node.inputs || {}) },
      };
      if (type === UNKNOWN_NODE_TYPE) {
        normalized.originalType = String(node.originalType || "UnknownCustomNode");
        normalized.inputSpecs = node.inputSpecs && typeof node.inputSpecs === "object" ? node.inputSpecs : unknownInputSpecs(node.inputs || {});
        normalized.outputs = Array.isArray(node.outputs) ? node.outputs.map((item) => String(item || "")).filter(Boolean) : unknownOutputs(3);
      }
      return normalized;
    }) : [];
    return {
      name: String(safe.name || ""),
      description: String(safe.description || ""),
      project_version: String(safe.project_version || ""),
      comfyui_version: String(safe.comfyui_version || ""),
      workflow_schema_version: String(safe.workflow_schema_version || "1"),
      nodes: normalizedNodes,
      edges: Array.isArray(safe.edges) ? safe.edges.map((edge) => ({
        id: String(edge.id || uid()),
        from: String(edge.from || ""),
        output: String(edge.output || ""),
        to: String(edge.to || ""),
        input: String(edge.input || ""),
        warning: String(edge.warning || ""),
      })).filter((edge) => edge.from && edge.to && edge.input) : [],
      warnings: Array.isArray(safe.warnings) ? safe.warnings.map((item) => String(item || "")).filter(Boolean).slice(0, 50) : [],
    };
  }

  function loadState() {
    try {
      return normalizeState(JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"));
    } catch (_) {
      return emptyState();
    }
  }

  function saveState() {
    workflow.name = $("workflowName")?.value || workflow.name || "";
    workflow.description = $("workflowDescription")?.value || workflow.description || "";
    localStorage.setItem(STORAGE_KEY, JSON.stringify(workflow));
  }

  function takePendingInput() {
    let payload = null;
    try {
      payload = JSON.parse(localStorage.getItem(INPUT_KEY) || "null");
    } catch (_) {
      payload = null;
    }
    if (!payload || typeof payload !== "object") return false;
    localStorage.removeItem(INPUT_KEY);
    const imported = stateFromPackage(payload);
    workflow = normalizeState(imported.state);
    selectedId = workflow.nodes[0]?.id || null;
    lastImportWarnings = imported.warnings;
    render();
    setStatus(imported.warnings.length ? `已載入 workflow，但有 ${imported.warnings.length} 個提醒。` : "已載入既有 workflow，可直接編輯節點與線路。", !imported.warnings.length);
    return true;
  }

  function addNode(type, x, y, label) {
    const def = NODE_DEFS[type];
    if (!def) return;
    const node = {
      id: uid(),
      type,
      label: label || def.label,
      x: Number.isFinite(x) ? x : 100 + (workflow.nodes.length % 4) * 260,
      y: Number.isFinite(y) ? y : 100 + Math.floor(workflow.nodes.length / 4) * 170,
      inputs: defaultInputs(type),
    };
    workflow.nodes.push(node);
    selectedId = node.id;
    render();
  }

  function nodeById(id) {
    return workflow.nodes.find((node) => node.id === id) || null;
  }

  function outputIndex(node, outputName) {
    const outputs = nodeDef(node)?.outputs || [];
    if (isUnknownNode(node) && /^OUT\d+$/i.test(String(outputName || ""))) {
      return Number(String(outputName).replace(/\D/g, "")) || 0;
    }
    return Math.max(0, outputs.indexOf(outputName));
  }

  function outputNameForIndex(node, index) {
    const outputs = nodeDef(node)?.outputs || [];
    return outputs[Number(index) || 0] || outputs[0] || "OUTPUT";
  }

  function layoutPosition(layout, id, index) {
    const raw = layout?.node_positions?.[id] || layout?.node_positions?.[String(id)];
    if (Array.isArray(raw) && raw.length >= 2 && Number.isFinite(Number(raw[0])) && Number.isFinite(Number(raw[1]))) {
      return [Number(raw[0]), Number(raw[1])];
    }
    return [70 + (index % 4) * 290, 80 + Math.floor(index / 4) * 190];
  }

  function nodeLabelFromLayout(nodeId, node, layout) {
    return String(
      node?._meta?.title ||
      layout?.field_overrides?.[nodeId]?.label ||
      NODE_DEFS[node?.class_type]?.label ||
      node?.class_type ||
      `Node ${nodeId}`
    );
  }

  function stateFromPackage(payload) {
    const source = payload && typeof payload === "object" ? payload : {};
    const prompt = source.workflow_json || source.prompt || source.workflow || source;
    const layout = source.layout_json || source.ui_layout_json || {};
    const warnings = [];
    if (!prompt || typeof prompt !== "object" || Array.isArray(prompt)) {
      return { state: emptyState(), warnings: ["Workflow JSON 必須是物件格式。"] };
    }
    const ids = Object.keys(prompt);
    const layoutOrder = Array.isArray(layout.node_order) ? layout.node_order.map((item) => String(item)) : [];
    const orderedIds = layoutOrder.filter((id) => prompt[id]).concat(ids.filter((id) => !layoutOrder.includes(id)));
    const nodes = [];
    const idSet = new Set();
    orderedIds.forEach((id, index) => {
      const raw = prompt[id] || {};
      const rawType = String(raw.class_type || "");
      const known = !!NODE_DEFS[rawType];
      const type = known ? rawType : UNKNOWN_NODE_TYPE;
      let maxOutputIndex = 3;
      const [x, y] = layoutPosition(layout, id, index);
      const inputs = known ? defaultInputs(type) : {};
      const inputSpecs = known ? null : unknownInputSpecs(raw.inputs || {});
      Object.entries(raw.inputs || {}).forEach(([key, value]) => {
        if (Array.isArray(value)) {
          if (!known) inputSpecs[key] = { type: "link", label: key };
          return;
        }
        if (Object.prototype.hasOwnProperty.call(inputs, key)) inputs[key] = value;
        else if (!known) inputs[key] = value;
      });
      Object.values(raw.inputs || {}).forEach((value) => {
        if (Array.isArray(value) && Number.isFinite(Number(value[1]))) maxOutputIndex = Math.max(maxOutputIndex, Number(value[1]));
      });
      const parsedNode = {
        id: String(id),
        type,
        label: known ? nodeLabelFromLayout(id, raw, layout) : nodeLabelFromLayout(id, { ...raw, class_type: rawType || "UnknownCustomNode" }, layout),
        x,
        y,
        inputs,
      };
      if (!known) {
        parsedNode.originalType = rawType || "UnknownCustomNode";
        parsedNode.inputSpecs = inputSpecs;
        parsedNode.outputs = unknownOutputs(maxOutputIndex);
        warnings.push(`未知/custom node ${id}: ${parsedNode.originalType}，已保留為 placeholder。`);
      }
      nodes.push(parsedNode);
      idSet.add(String(id));
    });
    const edges = [];
    orderedIds.forEach((id) => {
      const raw = prompt[id] || {};
      const target = nodes.find((node) => node.id === String(id));
      if (!target) return;
      Object.entries(raw.inputs || {}).forEach(([key, value]) => {
        if (!Array.isArray(value) || value.length < 1) return;
        const sourceId = String(value[0]);
        const source = nodes.find((node) => node.id === sourceId);
        if (!source || !idSet.has(sourceId)) {
          warnings.push(`連線 ${sourceId} -> ${id}.${key} 找不到來源節點，已略過。`);
          return;
        }
        const inputSpec = nodeDef(target)?.inputs?.[key];
        if (!inputSpec || inputSpec.type !== "link") {
          warnings.push(`連線 ${sourceId} -> ${id}.${key} 指向非連線欄位，已略過。`);
          return;
        }
        const output = outputNameForIndex(source, value[1]);
        edges.push({ id: uid(), from: sourceId, output, to: String(id), input: key, warning: connectionWarningForNodes(source, output, target, key) });
      });
    });
    const state = {
      name: String(source.name || source.title || "匯入的 ComfyUI 工作流"),
      description: String(source.description || ""),
      project_version: String(source.project_version || ""),
      comfyui_version: String(source.comfyui_version || ""),
      workflow_schema_version: String(source.workflow_schema_version || layout.workflow_schema_version || "1"),
      nodes,
      edges,
      warnings,
    };
    return { state, warnings };
  }

  function exportPackage() {
    const idMap = Object.fromEntries(workflow.nodes.map((node, index) => [node.id, String(index + 1)]));
    const layout = {
      layout_schema_version: "1",
      visual_builder_version: "1",
      node_order: workflow.nodes.map((node) => idMap[node.id]),
      node_positions: Object.fromEntries(workflow.nodes.map((node) => [idMap[node.id], [Math.round(node.x), Math.round(node.y)]])),
      field_overrides: Object.fromEntries(workflow.nodes.map((node) => [idMap[node.id], { label: node.label }])),
      edges: workflow.edges
        .filter((edge) => idMap[edge.from] && idMap[edge.to])
        .map((edge) => ({ from: idMap[edge.from], output: edge.output, to: idMap[edge.to], input: edge.input })),
    };
    const prompt = {};
    workflow.nodes.forEach((node) => {
      const promptInputs = clone(node.inputs || {});
      workflow.edges.filter((edge) => edge.to === node.id).forEach((edge) => {
        const source = nodeById(edge.from);
        if (source) promptInputs[edge.input] = [idMap[source.id], outputIndex(source, edge.output)];
      });
      prompt[idMap[node.id]] = {
        class_type: isUnknownNode(node) ? (node.originalType || "UnknownCustomNode") : node.type,
        inputs: promptInputs,
        _meta: { title: node.label || NODE_DEFS[node.type].label },
      };
    });
    return {
      name: workflow.name || "ComfyUI 視覺工作流",
      description: workflow.description || "",
      purpose: inferPurpose(),
      project_version: workflow.project_version || "",
      comfyui_version: workflow.comfyui_version || "",
      workflow_schema_version: workflow.workflow_schema_version || "1",
      workflow_json: prompt,
      layout_json: layout,
      required_models: collectRequiredModels(),
      required_custom_nodes: [],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
  }

  function normalizedPortKind(name) {
    const raw = String(name || "").toUpperCase();
    if (raw === "POSITIVE" || raw === "NEGATIVE") return "CONDITIONING";
    if (raw.includes("CONDITIONING")) return "CONDITIONING";
    if (raw.includes("CONTROL_NET")) return "CONTROL_NET";
    if (raw.includes("UPSCALE_MODEL")) return "UPSCALE_MODEL";
    if (raw.includes("MODEL")) return "MODEL";
    if (raw.includes("CLIP")) return "CLIP";
    if (raw.includes("VAE")) return "VAE";
    if (raw.includes("LATENT")) return "LATENT";
    if (raw.includes("MASK")) return "MASK";
    if (raw.includes("IMAGE") || raw === "PIXELS") return "IMAGE";
    return raw;
  }

  function connectionWarning(from, output, to, input) {
    return connectionWarningForNodes(nodeById(from), output, nodeById(to), input);
  }

  function connectionWarningForNodes(source, output, target, input) {
    const inputLabel = nodeDef(target)?.inputs?.[input]?.label || input;
    const outKind = normalizedPortKind(output);
    const inKind = normalizedPortKind(inputLabel);
    if (!outKind || !inKind || outKind === inKind) return "";
    return `${output} 連到 ${input} 型別可能不相容`;
  }

  function inferPurpose() {
    if (workflow.nodes.some((node) => node.type === "ControlNetApplyAdvanced")) return "controlnet";
    if (workflow.nodes.some((node) => node.type === "ImageUpscaleWithModel")) return "upscale";
    if (workflow.nodes.some((node) => node.type === "ImagePadForOutpaint")) return "outpaint";
    if (workflow.nodes.some((node) => node.type === "VAEEncodeForInpaint" || node.type === "LoadImageMask")) return "inpaint";
    if (workflow.nodes.some((node) => node.type === "LoadImage")) return "img2img";
    return "txt2img";
  }

  function collectRequiredModels() {
    const models = [];
    workflow.nodes.forEach((node) => {
      if (node.type === "CheckpointLoaderSimple" && node.inputs.ckpt_name) models.push({ kind: "checkpoint", name: node.inputs.ckpt_name });
      if (node.type === "LoraLoader" && node.inputs.lora_name) models.push({ kind: "lora", name: node.inputs.lora_name });
      if (node.type === "ControlNetLoader" && node.inputs.control_net_name) models.push({ kind: "controlnet", name: node.inputs.control_net_name });
      if (node.type === "UpscaleModelLoader" && node.inputs.model_name) models.push({ kind: "upscale", name: node.inputs.model_name });
      if (node.type === "VAELoader" && node.inputs.vae_name) models.push({ kind: "vae", name: node.inputs.vae_name });
    });
    return models;
  }

  function setStatus(message, good = true) {
    const el = $("status");
    if (!el) return;
    el.textContent = message || "";
    el.style.color = good ? "var(--muted)" : "var(--red)";
  }

  function render() {
    saveState();
    if ($("workflowName")) $("workflowName").value = workflow.name || "";
    if ($("workflowDescription")) $("workflowDescription").value = workflow.description || "";
    renderNodes();
    renderEdges();
    renderInspector();
    renderConnectionPanel();
    renderJson();
    const badges = $("summaryBadges");
    if (badges) {
      const warnings = workflowWarnings();
      badges.innerHTML = `
        <span class="badge">${workflow.nodes.length} nodes</span>
        <span class="badge">${workflow.edges.length} edges</span>
        <span class="badge">${html(inferPurpose())}</span>
        ${workflow.project_version ? `<span class="badge">project ${html(workflow.project_version)}</span>` : ""}
        ${workflow.comfyui_version ? `<span class="badge">ComfyUI ${html(workflow.comfyui_version)}</span>` : ""}
        ${warnings.length ? `<span class="badge warn">${warnings.length} warnings</span>` : '<span class="badge ok">ready</span>'}
      `;
    }
  }

  function workflowWarnings() {
    return []
      .concat(workflow.warnings || [])
      .concat(workflow.edges.map((edge) => edge.warning || "").filter(Boolean))
      .filter(Boolean);
  }

  function renderNodes() {
    const layer = $("nodeLayer");
    if (!layer) return;
    layer.innerHTML = workflow.nodes.map((node) => {
      const def = nodeDef(node);
      const inputRows = Object.entries(def.inputs || {});
      const linkInputs = inputRows.filter(([, spec]) => spec.type === "link");
      const valueInputs = inputRows.filter(([, spec]) => spec.type !== "link");
      return `
        <div class="wf-node ${node.id === selectedId ? "selected" : ""} ${isUnknownNode(node) ? "unknown" : ""}" data-node-id="${html(node.id)}" data-drag-node="${html(node.id)}" style="left:${Math.round(node.x)}px;top:${Math.round(node.y)}px;">
          <div class="wf-node-head" data-drag-node="${html(node.id)}">
            <strong>${html(node.label || def.label)}</strong>
            <span class="wf-node-kind">${html(isUnknownNode(node) ? node.originalType : node.type)}</span>
          </div>
          <div class="wf-node-body">
            <div class="port-row input-row">
              ${linkInputs.map(([key, spec]) => `<span class="port input" role="button" tabindex="0" title="input: ${html(spec.label || key)}" data-port-node="${html(node.id)}" data-port-kind="input" data-port-name="${html(key)}">${html(key)}</span>`).join("") || '<span class="port muted">no link input</span>'}
            </div>
            ${valueInputs.length ? `<div class="port-row value-row">${valueInputs.slice(0, 4).map(([key]) => `<span class="port value">${html(key)}</span>`).join("")}</div>` : ""}
            <div class="port-row output-row">
              ${(def.outputs || []).map((key) => `<span class="port output" role="button" tabindex="0" title="output: ${html(key)}" data-port-node="${html(node.id)}" data-port-kind="output" data-port-name="${html(key)}">${html(key)}</span>`).join("") || '<span class="port muted">final</span>'}
            </div>
          </div>
          <div class="node-actions">
            <button type="button" data-select-node="${html(node.id)}">設定</button>
            <button class="danger" type="button" data-delete-node="${html(node.id)}">刪除</button>
          </div>
        </div>
      `;
    }).join("");
    layer.querySelectorAll("[data-select-node]").forEach((button) => {
      button.addEventListener("click", () => {
        selectedId = button.getAttribute("data-select-node");
        render();
      });
    });
    layer.querySelectorAll("[data-delete-node]").forEach((button) => {
      button.addEventListener("click", () => deleteNode(button.getAttribute("data-delete-node")));
    });
    layer.querySelectorAll("[data-drag-node]").forEach((head) => {
      head.addEventListener("pointerdown", startDrag);
      head.addEventListener("mousedown", startDrag);
    });
    layer.querySelectorAll('.port.output[data-port-node]').forEach((port) => {
      port.addEventListener("pointerdown", startConnection);
      port.addEventListener("mousedown", startConnection);
      port.addEventListener("keydown", startConnectionFromKeyboard);
    });
    layer.querySelectorAll('.port.input[data-port-node]').forEach((port) => {
      port.addEventListener("pointerup", completeConnection);
      port.addEventListener("mouseup", completeConnection);
      port.addEventListener("keydown", completeConnectionFromKeyboard);
    });
  }

  function deleteNode(id) {
    workflow.nodes = workflow.nodes.filter((node) => node.id !== id);
    workflow.edges = workflow.edges.filter((edge) => edge.from !== id && edge.to !== id);
    if (selectedId === id) selectedId = workflow.nodes[0]?.id || null;
    render();
  }

  function startDrag(event) {
    if (dragState) return;
    if (event.target && event.target.closest && event.target.closest("button, input, select, textarea, a, .port")) return;
    const id = event.currentTarget.getAttribute("data-drag-node");
    const node = nodeById(id);
    if (!node) return;
    selectedId = id;
    document.querySelectorAll(".wf-node.selected").forEach((item) => item.classList.remove("selected"));
    const nodeEl = document.querySelector(`[data-node-id="${cssIdent(id)}"]`);
    nodeEl?.classList.add("selected");
    nodeEl?.classList.add("dragging");
    renderInspector();
    renderConnectionPanel();
    renderJson();
    dragState = { id, startX: event.clientX, startY: event.clientY, nodeX: node.x, nodeY: node.y };
    event.preventDefault();
    try {
      if (event.pointerId !== undefined && event.currentTarget.setPointerCapture) {
        event.currentTarget.setPointerCapture(event.pointerId);
      }
    } catch (_) {
      // Mouse fallback below keeps dragging available when pointer capture is unavailable.
    }
    window.addEventListener("pointermove", onDrag);
    window.addEventListener("mousemove", onDrag);
    window.addEventListener("pointerup", endDrag, { once: true });
    window.addEventListener("mouseup", endDrag, { once: true });
    window.addEventListener("blur", endDrag, { once: true });
  }

  function onDrag(event) {
    if (!dragState) return;
    const node = nodeById(dragState.id);
    if (!node) return;
    node.x = Math.max(0, dragState.nodeX + event.clientX - dragState.startX);
    node.y = Math.max(0, dragState.nodeY + event.clientY - dragState.startY);
    const el = document.querySelector(`[data-node-id="${cssIdent(node.id)}"]`);
    if (el) {
      el.style.left = `${Math.round(node.x)}px`;
      el.style.top = `${Math.round(node.y)}px`;
    }
    renderEdges();
  }

  function endDrag() {
    const id = dragState?.id;
    dragState = null;
    window.removeEventListener("pointermove", onDrag);
    window.removeEventListener("mousemove", onDrag);
    window.removeEventListener("blur", endDrag);
    if (id) document.querySelector(`[data-node-id="${cssIdent(id)}"]`)?.classList.remove("dragging");
    render();
  }

  function autoLayoutNodes() {
    if (!workflow.nodes.length) return;
    const order = workflow.nodes.slice().sort((a, b) => {
      const aIncoming = workflow.edges.filter((edge) => edge.to === a.id).length;
      const bIncoming = workflow.edges.filter((edge) => edge.to === b.id).length;
      return aIncoming - bIncoming || workflow.nodes.indexOf(a) - workflow.nodes.indexOf(b);
    });
    order.forEach((node, index) => {
      node.x = 70 + (index % 4) * 290;
      node.y = 80 + Math.floor(index / 4) * 190;
    });
    render();
    setStatus("已重新排列節點，連線會重新貼齊節點。");
  }

  function canvasPoint(event) {
    const canvas = $("canvas");
    const rect = canvas?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  function portPoint(nodeId, kind, name) {
    const canvas = $("canvas");
    const selector = `.port[data-port-node="${cssIdent(nodeId)}"][data-port-kind="${cssIdent(kind)}"][data-port-name="${cssIdent(name)}"]`;
    const port = document.querySelector(selector);
    const canvasRect = canvas?.getBoundingClientRect();
    if (port && canvasRect) {
      const rect = port.getBoundingClientRect();
      return {
        x: rect.left - canvasRect.left + (kind === "output" ? rect.width : 0),
        y: rect.top - canvasRect.top + rect.height / 2,
      };
    }
    const node = nodeById(nodeId);
    const nodeEl = node ? document.querySelector(`[data-node-id="${cssIdent(node.id)}"]`) : null;
    const width = nodeEl?.offsetWidth || 220;
    const height = nodeEl?.offsetHeight || 116;
    return {
      x: (node?.x || 0) + (kind === "output" ? width : 0),
      y: (node?.y || 0) + height / 2,
    };
  }

  function edgePath(start, end) {
    const mid = Math.max(70, Math.abs(end.x - start.x) / 2);
    return `M ${start.x} ${start.y} C ${start.x + mid} ${start.y}, ${end.x - mid} ${end.y}, ${end.x} ${end.y}`;
  }

  function renderEdges() {
    const svg = $("edgeLayer");
    if (!svg) return;
    const parts = [];
    workflow.edges.forEach((edge) => {
      const from = nodeById(edge.from);
      const to = nodeById(edge.to);
      if (!from || !to) return;
      const start = portPoint(edge.from, "output", edge.output);
      const end = portPoint(edge.to, "input", edge.input);
      const path = edgePath(start, end);
      parts.push(`<path class="edge-path ${edge.warning ? "warn" : ""}" data-edge-id="${html(edge.id)}" d="${path}"></path>`);
      parts.push(`<circle class="edge-dot output" cx="${start.x}" cy="${start.y}" r="4"></circle>`);
      parts.push(`<circle class="edge-dot input" cx="${end.x}" cy="${end.y}" r="4"></circle>`);
      parts.push(`<text class="edge-label ${edge.warning ? "warn" : ""}" x="${(start.x + end.x) / 2}" y="${(start.y + end.y) / 2 - 7}">${html(edge.output)} → ${html(edge.input)}</text>`);
    });
    if (connectState) {
      const start = portPoint(connectState.from, "output", connectState.output);
      const end = connectState.current || start;
      parts.push(`<path class="edge-path temp" d="${edgePath(start, end)}"></path>`);
    }
    svg.innerHTML = parts.join("");
  }

  function markConnectionPorts() {
    document.querySelectorAll(".port.connecting, .port.compatible").forEach((port) => {
      port.classList.remove("connecting", "compatible");
    });
    if (!connectState) return;
    document.querySelector(`.port.output[data-port-node="${cssIdent(connectState.from)}"][data-port-name="${cssIdent(connectState.output)}"]`)?.classList.add("connecting");
    document.querySelectorAll('.port.input[data-port-node]').forEach((port) => {
      if (port.getAttribute("data-port-node") !== connectState.from) port.classList.add("compatible");
    });
  }

  function startConnection(event) {
    if (event.button !== undefined && event.button !== 0) return;
    const port = event.currentTarget?.closest?.(".port.output");
    if (!port) return;
    const from = port.getAttribute("data-port-node") || "";
    const output = port.getAttribute("data-port-name") || "";
    if (!from || !output) return;
    selectedId = from;
    connectState = { from, output, current: portPoint(from, "output", output) };
    markConnectionPorts();
    renderInspector();
    renderConnectionPanel();
    renderEdges();
    setStatus(`正在連線：${output}。拉到紫色 input 放開即可建立連線。`);
    event.preventDefault();
    event.stopPropagation();
    window.addEventListener("pointermove", onConnectionMove);
    window.addEventListener("mousemove", onConnectionMove);
    window.addEventListener("pointerup", onConnectionPointerUp, { once: true });
    window.addEventListener("mouseup", onConnectionPointerUp, { once: true });
    window.addEventListener("keydown", cancelConnectionOnEscape);
  }

  function startConnectionFromKeyboard(event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    const port = event.currentTarget?.closest?.(".port.output");
    if (!port) return;
    const from = port.getAttribute("data-port-node") || "";
    const output = port.getAttribute("data-port-name") || "";
    if (!from || !output) return;
    selectedId = from;
    connectState = { from, output, current: portPoint(from, "output", output) };
    markConnectionPorts();
    renderInspector();
    renderConnectionPanel();
    renderEdges();
    setStatus(`已選取 output：${output}。移到紫色 input 按 Enter 建立連線。`);
    event.preventDefault();
    event.stopPropagation();
    window.addEventListener("keydown", cancelConnectionOnEscape);
  }

  function onConnectionMove(event) {
    if (!connectState) return;
    connectState.current = canvasPoint(event);
    renderEdges();
  }

  function onConnectionPointerUp(event) {
    const input = event.target?.closest?.(".port.input[data-port-node]");
    if (input) {
      completeConnection({ currentTarget: input, preventDefault: () => event.preventDefault(), stopPropagation: () => event.stopPropagation() });
      return;
    }
    cancelConnection("連線已取消。");
  }

  function cancelConnectionOnEscape(event) {
    if (event.key === "Escape") cancelConnection("連線已取消。");
  }

  function cancelConnection(message = "") {
    connectState = null;
    window.removeEventListener("pointermove", onConnectionMove);
    window.removeEventListener("mousemove", onConnectionMove);
    window.removeEventListener("keydown", cancelConnectionOnEscape);
    markConnectionPorts();
    renderEdges();
    if (message) setStatus(message);
  }

  function completeConnection(event) {
    if (!connectState) return;
    const port = event.currentTarget?.closest?.(".port.input");
    const to = port?.getAttribute("data-port-node") || "";
    const input = port?.getAttribute("data-port-name") || "";
    const output = connectState.output;
    if (!to || !input || to === connectState.from) {
      cancelConnection("不能把節點連到自己。");
      return;
    }
    const ok = addEdge({ from: connectState.from, output: connectState.output, to, input });
    event.preventDefault();
    event.stopPropagation();
    cancelConnection();
    if (!ok) {
      setStatus("這條連線無效，請確認目標是可連接的 input。", false);
      return;
    }
    selectedId = to;
    render();
    setStatus(`已連線：${output} → ${input}`);
  }

  function completeConnectionFromKeyboard(event) {
    if (!connectState || (event.key !== "Enter" && event.key !== " ")) return;
    completeConnection({ currentTarget: event.currentTarget, preventDefault: () => event.preventDefault(), stopPropagation: () => event.stopPropagation() });
  }

  function renderInspector() {
    const node = nodeById(selectedId);
    const badge = $("selectedBadge");
    const box = $("inspector");
    if (badge) badge.textContent = node ? node.type : "未選取";
    if (!box) return;
    if (!node) {
      box.innerHTML = '<div class="empty">先從左側新增節點，再選取節點調整屬性。</div>';
      return;
    }
    const def = nodeDef(node);
    if (isUnknownNode(node)) {
      box.innerHTML = `
        <div class="warning-list">
          <div>這是未知/custom node placeholder。會保留原始 class_type 與 inputs；input/output schema 需等連上 ComfyUI object_info 才能嚴格驗證。</div>
        </div>
        <div class="field">
          <label>節點名稱</label>
          <input id="nodeLabelInput" value="${html(node.label || def.label)}" maxlength="80">
        </div>
        <div class="field">
          <label>原始 class_type</label>
          <input id="unknownClassInput" value="${html(node.originalType || "")}" maxlength="160">
        </div>
        <div class="field">
          <label>原始 inputs JSON</label>
          <textarea id="unknownInputsInput" rows="10" spellcheck="false">${html(JSON.stringify(node.inputs || {}, null, 2))}</textarea>
        </div>
      `;
      $("nodeLabelInput")?.addEventListener("input", () => {
        node.label = $("nodeLabelInput").value;
        render();
      });
      $("unknownClassInput")?.addEventListener("input", () => {
        node.originalType = $("unknownClassInput").value.trim() || "UnknownCustomNode";
        renderJson();
      });
      $("unknownInputsInput")?.addEventListener("input", () => {
        try {
          const parsed = JSON.parse($("unknownInputsInput").value || "{}");
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
            node.inputs = parsed;
            node.inputSpecs = unknownInputSpecs(parsed);
            renderJson();
            setStatus("Custom node inputs 已更新。");
          }
        } catch (err) {
          setStatus(`Custom node inputs JSON 格式錯誤：${err.message || err}`, false);
        }
      });
      return;
    }
    const fields = Object.entries(def.inputs || {}).filter(([, spec]) => spec.type !== "link");
    box.innerHTML = `
      <div class="field">
        <label>節點名稱</label>
        <input id="nodeLabelInput" value="${html(node.label || def.label)}" maxlength="80">
      </div>
      <div class="inspector-grid">
        ${fields.map(([key, spec]) => inspectorInputMarkup(node, key, spec)).join("") || '<div class="empty">這個節點沒有可直接編輯的值；請用下方連線面板接 input。</div>'}
      </div>
    `;
    const labelInput = $("nodeLabelInput");
    if (labelInput) labelInput.addEventListener("input", () => {
      node.label = labelInput.value;
      render();
    });
    fields.forEach(([key]) => {
      const input = $(`nodeInput-${key}`);
      if (!input) return;
      input.addEventListener("input", () => {
        node.inputs[key] = input.type === "number" ? Number(input.value) : input.value;
        renderJson();
      });
    });
  }

  function inspectorInputMarkup(node, key, spec) {
    const value = node.inputs?.[key] ?? "";
    if (spec.type === "textarea") {
      return `<div class="field"><label>${html(spec.label || key)}</label><textarea id="nodeInput-${html(key)}" rows="4">${html(value)}</textarea></div>`;
    }
    return `<div class="field"><label>${html(spec.label || key)}</label><input id="nodeInput-${html(key)}" type="${spec.type === "number" ? "number" : "text"}" step="${html(spec.step || "1")}" value="${html(String(value))}"></div>`;
  }

  function renderConnectionPanel() {
    const panel = $("connectionPanel");
    const badge = $("connectionBadge");
    const source = nodeById(selectedId);
    if (badge) badge.textContent = source ? "可連線" : "-";
    if (!panel) return;
    if (!source) {
      panel.innerHTML = '<div class="empty">選取來源節點後，可把它的 output 連到其他節點 input。</div>';
      return;
    }
    const outputs = nodeDef(source)?.outputs || [];
    const targets = workflow.nodes.filter((node) => node.id !== source.id);
    const target = targets[0] || null;
    const selectedEdges = workflow.edges.filter((edge) => edge.from === source.id || edge.to === source.id);
    const allWarnings = workflowWarnings();
    panel.innerHTML = `
      ${allWarnings.length ? `
        <div class="warning-list">
          ${allWarnings.slice(0, 6).map((warning) => `<div>${html(warning)}</div>`).join("")}
          ${allWarnings.length > 6 ? `<div>另 ${html(String(allWarnings.length - 6))} 個提醒</div>` : ""}
        </div>
      ` : '<div class="empty">從綠色 output 拉到紫色 input 可建立線路；同一個 input 只會保留最新一條線。</div>'}
      <div class="field">
        <label>來源 output</label>
        <select id="edgeOutput">${outputs.map((name) => `<option value="${html(name)}">${html(name)}</option>`).join("")}</select>
      </div>
      <div class="field">
        <label>目標節點</label>
        <select id="edgeTarget">${targets.map((node) => `<option value="${html(node.id)}">${html(node.label || nodeDef(node)?.label || node.type)}</option>`).join("")}</select>
      </div>
      <div class="field">
        <label>目標 input</label>
        <select id="edgeInput">${targetInputOptions(target).join("")}</select>
      </div>
      <div class="row-actions">
        <button class="primary" id="addEdgeBtn" type="button" ${!outputs.length || !targets.length ? "disabled" : ""}>建立連線</button>
        <button id="removeSelectedEdgesBtn" type="button">移除此節點連線</button>
      </div>
      <div class="edge-list">
        ${selectedEdges.length ? selectedEdges.map((edge) => edgeRow(edge)).join("") : '<div class="empty">目前選取節點沒有連線。</div>'}
      </div>
    `;
    const targetSelect = $("edgeTarget");
    if (targetSelect) targetSelect.addEventListener("change", () => {
      const inputSelect = $("edgeInput");
      if (inputSelect) inputSelect.innerHTML = targetInputOptions(nodeById(targetSelect.value)).join("");
    });
    $("addEdgeBtn")?.addEventListener("click", addEdgeFromPanel);
    $("removeSelectedEdgesBtn")?.addEventListener("click", () => {
      workflow.edges = workflow.edges.filter((edge) => edge.from !== source.id && edge.to !== source.id);
      render();
    });
    panel.querySelectorAll("[data-delete-edge]").forEach((button) => {
      button.addEventListener("click", () => {
        deleteEdge(button.getAttribute("data-delete-edge"));
      });
    });
  }

  function edgeRow(edge) {
    const from = nodeById(edge.from);
    const to = nodeById(edge.to);
    return `
      <div class="edge-list-row ${edge.warning ? "warn" : ""}">
        <div>
          <strong>${html(from?.label || edge.from)}</strong>
          <span>${html(edge.output)} → ${html(to?.label || edge.to)}.${html(edge.input)}</span>
          ${edge.warning ? `<small>${html(edge.warning)}</small>` : ""}
        </div>
        <button class="danger" type="button" data-delete-edge="${html(edge.id)}">刪除線</button>
      </div>
    `;
  }

  function deleteEdge(id) {
    workflow.edges = workflow.edges.filter((edge) => edge.id !== id);
    render();
    setStatus("已刪除線路。");
  }

  function targetInputOptions(node) {
    if (!node) return [];
    return Object.entries(nodeDef(node)?.inputs || {})
      .filter(([, spec]) => spec.type === "link")
      .map(([key, spec]) => `<option value="${html(key)}">${html(spec.label || key)}</option>`);
  }

  function addEdgeFromPanel() {
    const from = nodeById(selectedId);
    const to = nodeById($("edgeTarget")?.value || "");
    const output = $("edgeOutput")?.value || "";
    const input = $("edgeInput")?.value || "";
    if (!from || !to || !output || !input) return;
    addEdge({ from: from.id, output, to: to.id, input });
    render();
  }

  function addEdge({ from, output, to, input }) {
    const source = nodeById(from);
    const target = nodeById(to);
    if (!source || !target || source.id === target.id || !output || !input) return false;
    const targetInput = nodeDef(target)?.inputs?.[input];
    if (!targetInput || targetInput.type !== "link") return false;
    workflow.edges = workflow.edges.filter((edge) => !(edge.to === target.id && edge.input === input));
    workflow.edges.push({ id: uid(), from: source.id, output, to: target.id, input, warning: connectionWarning(source.id, output, target.id, input) });
    return true;
  }

  function renderJson() {
    const out = $("jsonOut");
    if (out) out.value = JSON.stringify(exportPackage(), null, 2);
  }

  function createTxt2ImgStarter() {
    workflow = emptyState();
    workflow.name = $("workflowName")?.value || "txt2img 起始工作流";
    workflow.description = $("workflowDescription")?.value || "視覺編輯器建立的 txt2img 基礎 workflow";
    const specs = [
      ["CheckpointLoaderSimple", 70, 80, "主模型", { ckpt_name: "" }],
      ["CLIPTextEncode", 350, 35, "正向提示詞", { text: "masterpiece, best quality" }],
      ["CLIPTextEncode", 350, 205, "負向提示詞", { text: "low quality, blurry" }],
      ["EmptyLatentImage", 350, 375, "畫布尺寸", { width: 1024, height: 1024, batch_size: 1 }],
      ["KSampler", 660, 190, "採樣器", { seed: 0, steps: 20, cfg: 7, sampler_name: "euler", scheduler: "normal", denoise: 1 }],
      ["VAEDecode", 950, 190, "VAE 解碼", {}],
      ["SaveImage", 1220, 190, "儲存圖片", { filename_prefix: "hackme_web" }],
    ];
    specs.forEach(([type, x, y, label, inputs]) => {
      const node = { id: uid(), type, label, x, y, inputs: { ...defaultInputs(type), ...(inputs || {}) } };
      workflow.nodes.push(node);
    });
    const [ckpt, pos, neg, latent, sampler, decode, save] = workflow.nodes;
    workflow.edges = [
      { id: uid(), from: ckpt.id, output: "CLIP", to: pos.id, input: "clip" },
      { id: uid(), from: ckpt.id, output: "CLIP", to: neg.id, input: "clip" },
      { id: uid(), from: ckpt.id, output: "MODEL", to: sampler.id, input: "model" },
      { id: uid(), from: pos.id, output: "CONDITIONING", to: sampler.id, input: "positive" },
      { id: uid(), from: neg.id, output: "CONDITIONING", to: sampler.id, input: "negative" },
      { id: uid(), from: latent.id, output: "LATENT", to: sampler.id, input: "latent_image" },
      { id: uid(), from: sampler.id, output: "LATENT", to: decode.id, input: "samples" },
      { id: uid(), from: ckpt.id, output: "VAE", to: decode.id, input: "vae" },
      { id: uid(), from: decode.id, output: "IMAGE", to: save.id, input: "images" },
    ];
    selectedId = ckpt.id;
    render();
    setStatus("已建立 txt2img 節點圖，可拖曳節點、調整屬性或新增連線。");
  }

  function sendBackToMainPage() {
    const payload = exportPackage();
    localStorage.setItem(RESULT_KEY, JSON.stringify(payload));
    setStatus("已送回主頁。回到 ComfyUI 頁按「載入視覺編輯器結果」即可保存。");
  }

  async function copyJson() {
    const text = JSON.stringify(exportPackage(), null, 2);
    try {
      await navigator.clipboard.writeText(text);
      setStatus("已複製 workflow preset JSON。");
    } catch (_) {
      $("jsonOut").value = text;
      $("jsonOut").select();
      setStatus("無法直接寫入剪貼簿，已選取 JSON。", false);
    }
  }

  async function importJsonFile(event) {
    const file = event.target?.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const payload = JSON.parse(text);
      const imported = stateFromPackage(payload);
      if (!imported.state.nodes.length) {
        setStatus("匯入失敗：沒有可視覺化的 allowlist 節點。", false);
        return;
      }
      workflow = normalizeState(imported.state);
      selectedId = workflow.nodes[0]?.id || null;
      lastImportWarnings = imported.warnings;
      render();
      setStatus(imported.warnings.length ? `已匯入 JSON，但有 ${imported.warnings.length} 個提醒。` : "已匯入 JSON 並轉成節點圖。", !imported.warnings.length);
    } catch (err) {
      setStatus(`匯入失敗：${err.message || err}`, false);
    } finally {
      if (event.target) event.target.value = "";
    }
  }

  function clearAll() {
    if (!confirm("清空目前畫布？")) return;
    workflow = emptyState();
    selectedId = null;
    render();
  }

  function bind() {
    document.querySelectorAll("[data-add-node]").forEach((button) => {
      button.addEventListener("click", () => addNode(button.getAttribute("data-add-node")));
    });
    $("starterTxt2ImgBtn")?.addEventListener("click", createTxt2ImgStarter);
    $("autoLayoutBtn")?.addEventListener("click", autoLayoutNodes);
    $("importJsonFile")?.addEventListener("change", (event) => importJsonFile(event));
    $("clearBtn")?.addEventListener("click", clearAll);
    $("sendBackBtn")?.addEventListener("click", sendBackToMainPage);
    $("copyJsonBtn")?.addEventListener("click", copyJson);
    $("workflowName")?.addEventListener("input", () => { workflow.name = $("workflowName").value; renderJson(); saveState(); });
    $("workflowDescription")?.addEventListener("input", () => { workflow.description = $("workflowDescription").value; renderJson(); saveState(); });
  }

  bind();
  if (takePendingInput()) {
    // Loaded from main page or saved preset handoff.
  } else if (!workflow.nodes.length) createTxt2ImgStarter();
  else {
    selectedId = workflow.nodes[0]?.id || null;
    render();
  }
})();
