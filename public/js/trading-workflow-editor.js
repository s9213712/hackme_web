    const STORAGE_KEY = "hackme_trading_workflow_json";
    const $ = (id) => document.getElementById(id);
    const CONDITION_TYPES = [
      "price_below", "price_above", "rsi_above", "rsi_below", "kd_above", "kd_below",
      "ma_position", "bb_position", "has_position", "change_percent_up", "change_percent_down",
      "take_profit_percent", "stop_loss_percent"
    ];
    const ACTION_TYPES = ["buy_percent", "buy_amount", "sell_percent", "close_all", "hold"];
    const CONDITION_LABELS = {
      price_below: "價格低於", price_above: "價格高於", rsi_above: "RSI 高於", rsi_below: "RSI 低於",
      kd_above: "KD 高於", kd_below: "KD 低於", ma_position: "均線位置", bb_position: "布林位置",
      has_position: "持倉狀態", change_percent_up: "漲幅達到", change_percent_down: "跌幅達到",
      take_profit_percent: "止盈比例", stop_loss_percent: "止損比例"
    };
    const ACTION_LABELS = {
      buy_percent: "買入百分比", buy_amount: "固定金額買入", sell_percent: "賣出百分比",
      close_all: "全部平倉", hold: "不動作"
    };
    let selected = { branchId: "entry", kind: "branch", index: -1 };
    let dragRef = null;
    let workflow = templateWorkflow();

    function templateWorkflow() {
      return {
        version: 1,
        strategy_kind: "workflow",
        source: "workflow_editor",
        name: "BTC 分批進出場策略",
        description: "以價格、KD、布林中線與 MA50 判斷進場，並保留風控分支。",
        branches: [
          {
            id: "entry",
            name: "進場策略",
            priority: 10,
            logic: "AND",
            cooldown_seconds: 3600,
            max_runs: 100,
            conditions: [
              { type: "price_below", value: 100000 },
              { type: "kd_above", value: 50 },
              { type: "bb_position", position: "above_mid" },
              { type: "ma_position", period: 50, position: "above" }
            ],
            actions: [
              { type: "buy_percent", percent: 10, step: 1, order_type: "market" },
              { type: "buy_percent", percent: 20, step: 2, order_type: "market" }
            ]
          },
          {
            id: "reduce",
            name: "風險減倉",
            priority: 50,
            logic: "AND",
            cooldown_seconds: 300,
            max_runs: 100,
            conditions: [
              { type: "has_position", value: true },
              { type: "price_below", value: 80000 }
            ],
            actions: [
              { type: "sell_percent", percent: 50, step: 1, order_type: "market" },
              { type: "sell_percent", percent: 100, step: 2, order_type: "market" }
            ]
          },
          {
            id: "stop",
            name: "強制止損",
            priority: 100,
            logic: "AND",
            cooldown_seconds: 0,
            max_runs: 100,
            conditions: [{ type: "price_below", value: 50000 }],
            actions: [{ type: "close_all", step: 1, order_type: "market" }]
          }
        ]
      };
    }

    function uid(prefix) {
      return `${prefix}_${Math.random().toString(36).slice(2, 8)}`;
    }

    function html(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "\"":"&quot;", "'":"&#39;" }[ch]));
    }

    function branchById(id) {
      return workflow.branches.find((row) => row.id === id) || workflow.branches[0];
    }

    function clampNumber(value, fallback = 0) {
      const next = Number(value);
      return Number.isFinite(next) ? next : fallback;
    }

    function normalizeWorkflow(input) {
      const base = input && typeof input === "object" ? input : templateWorkflow();
      const fallback = templateWorkflow();
      const branches = Array.isArray(base.branches) && base.branches.length ? base.branches : fallback.branches;
      return {
        version: 1,
        strategy_kind: "workflow",
        source: String(base.source || "workflow_editor").slice(0, 80),
        name: String(base.name || fallback.name).slice(0, 80),
        description: String(base.description || "").slice(0, 160),
        branches: branches.slice(0, 20).map((branch, index) => ({
          id: String(branch.id || uid("branch")).slice(0, 80),
          name: String(branch.name || `策略分支 ${index + 1}`).slice(0, 80),
          priority: clampNumber(branch.priority, 0),
          logic: String(branch.logic || "AND").toUpperCase() === "OR" ? "OR" : "AND",
          cooldown_seconds: Math.max(0, clampNumber(branch.cooldown_seconds, 0)),
          max_runs: Math.max(1, clampNumber(branch.max_runs, 100)),
          conditions: Array.isArray(branch.conditions) && branch.conditions.length ? branch.conditions.slice(0, 20).map(cleanCondition) : [cleanCondition({ type: "price_below", value: 100000 })],
          actions: Array.isArray(branch.actions) && branch.actions.length ? branch.actions.slice(0, 20).map(cleanAction) : [cleanAction({ type: "hold", step: 1, order_type: "market" })]
        }))
      };
    }

    function cleanCondition(node) {
      const type = CONDITION_TYPES.includes(node?.type) ? node.type : "price_below";
      const clean = { type };
      if (["ma_position"].includes(type)) {
        clean.period = Math.max(1, clampNumber(node.period, 50));
        clean.position = ["above", "below"].includes(node.position) ? node.position : "above";
      } else if (type === "bb_position") {
        clean.position = ["above_mid", "below_mid", "above_upper", "below_lower"].includes(node.position) ? node.position : "above_mid";
      } else if (type === "has_position") {
        clean.value = node.value === false ? false : true;
      } else {
        clean.value = clampNumber(node.value, 0);
      }
      return clean;
    }

    function cleanAction(node) {
      const type = ACTION_TYPES.includes(node?.type) ? node.type : "buy_percent";
      const clean = {
        type,
        step: Math.max(1, clampNumber(node.step, 1)),
        order_type: String(node.order_type || "market") === "limit" ? "limit" : "market"
      };
      if (type === "buy_amount") clean.amount_points = Math.max(0, clampNumber(node.amount_points ?? node.value, 100));
      if (type === "buy_percent" || type === "sell_percent") clean.percent = Math.max(0, Math.min(100, clampNumber(node.percent ?? node.value, 10)));
      if (node.limit_price_points != null && clampNumber(node.limit_price_points, 0) > 0) clean.limit_price_points = clampNumber(node.limit_price_points, 0);
      return clean;
    }

    function defaultCondition(type) {
      return cleanCondition({ type, value: type.includes("rsi") || type.includes("kd") ? 50 : 100000 });
    }

    function defaultAction(type) {
      if (type === "buy_amount") return cleanAction({ type, amount_points: 100, step: 1 });
      if (type === "sell_percent") return cleanAction({ type, percent: 50, step: 1 });
      return cleanAction({ type, percent: 10, step: 1 });
    }

    function selectedNodeRef() {
      const branch = branchById(selected.branchId);
      if (!branch || selected.kind === "branch") return { branch, list: null, node: null };
      const list = selected.kind === "condition" ? branch.conditions : branch.actions;
      return { branch, list, node: list?.[selected.index] || null };
    }

    function nodeLabel(node) {
      const label = CONDITION_LABELS[node.type] || ACTION_LABELS[node.type] || node.type || "-";
      if (node.type === "price_below") return `${label} ${node.value || 0}`;
      if (node.type === "price_above") return `${label} ${node.value || 0}`;
      if (node.type === "rsi_above" || node.type === "rsi_below" || node.type === "kd_above" || node.type === "kd_below") return `${label} ${node.value || 0}`;
      if (node.type === "change_percent_up" || node.type === "change_percent_down" || node.type === "take_profit_percent" || node.type === "stop_loss_percent") return `${label} ${node.value || 0}%`;
      if (node.type === "ma_position") return `價格在 MA${node.period || 50} ${node.position === "below" ? "下方" : "上方"}`;
      if (node.type === "bb_position") return `布林 ${bbText(node.position)}`;
      if (node.type === "has_position") return node.value === false ? "沒有持倉" : "持倉存在";
      if (node.type === "buy_percent") return `買入可用資金 ${node.percent || 0}%`;
      if (node.type === "buy_amount") return `買入 ${node.amount_points || 0} 點`;
      if (node.type === "sell_percent") return `賣出持倉 ${node.percent || 0}%`;
      if (node.type === "close_all") return "全部平倉";
      if (node.type === "hold") return "不動作";
      return label;
    }

    function bbText(value) {
      return {
        above_mid: "中線上方",
        below_mid: "中線下方",
        above_upper: "上軌上方",
        below_lower: "下軌下方"
      }[value] || "中線上方";
    }

    function renderSummary() {
      const branches = workflow.branches.length;
      const conditions = workflow.branches.reduce((sum, row) => sum + row.conditions.length, 0);
      const actions = workflow.branches.reduce((sum, row) => sum + row.actions.length, 0);
      $("summaryBadges").innerHTML = `
        <span class="badge ok">${branches} 分支</span>
        <span class="badge">${conditions} 條件</span>
        <span class="badge">${actions} 行為</span>
      `;
    }

    function renderTabs() {
      $("branchTabs").innerHTML = workflow.branches.map((branch) => `
        <button type="button" class="branch-tab ${selected.branchId === branch.id ? "active" : ""}" data-select-branch="${html(branch.id)}">
          ${html(branch.name || branch.id)}
        </button>
      `).join("");
    }

    function nodeCard(branch, kind, node, index) {
      const selectedClass = selected.branchId === branch.id && selected.kind === kind && selected.index === index ? "selected" : "";
      const kindText = kind === "condition" ? "條件" : `行為 step ${node.step || index + 1}`;
      return `
        <article class="node ${kind} ${selectedClass}" draggable="true" data-node-ref="${kind}:${html(branch.id)}:${index}" role="button" tabindex="0">
          <div class="node-top">
            <span class="node-kind">${html(kindText)}</span>
            <span class="node-tools">
              <button type="button" data-move-node="${kind}:${html(branch.id)}:${index}:left" title="往前">‹</button>
              <button type="button" data-move-node="${kind}:${html(branch.id)}:${index}:right" title="往後">›</button>
              <button type="button" data-delete-node="${kind}:${html(branch.id)}:${index}" title="刪除">×</button>
            </span>
          </div>
          <div class="node-label">${html(nodeLabel(node))}</div>
        </article>`;
    }

    function renderCanvas() {
      $("canvas").innerHTML = workflow.branches.map((branch) => `
        <section class="panel branch ${selected.branchId === branch.id ? "selected" : ""}" data-branch="${html(branch.id)}">
          <div class="branch-head">
            <div>
              <div class="branch-name">${html(branch.name)}</div>
              <div class="badges branch-badges">
                <span class="badge">priority ${Number(branch.priority || 0)}</span>
                <span class="badge">${html(branch.logic || "AND")}</span>
                <span class="badge">cooldown ${Number(branch.cooldown_seconds || 0)}s</span>
                <span class="badge">max ${Number(branch.max_runs || 0)}</span>
              </div>
            </div>
            <div class="row-actions">
              <button type="button" data-select-branch="${html(branch.id)}">設定</button>
              <button type="button" data-duplicate-branch="${html(branch.id)}">複製</button>
              <button class="danger" type="button" data-delete-branch="${html(branch.id)}">刪除</button>
            </div>
          </div>
          <div class="flow">
            <div class="lane" data-drop-kind="condition" data-drop-branch="${html(branch.id)}">
              <div class="lane-head"><b>條件</b><span>由上到下判斷</span></div>
              <div class="node-list">
                ${(branch.conditions || []).map((node, index) => nodeCard(branch, "condition", node, index)).join("") || '<div class="empty">從左側加入條件節點</div>'}
              </div>
            </div>
            <button class="logic-node" type="button" data-select-branch="${html(branch.id)}" title="點擊可在右側修改 AND / OR">
              ${html(branch.logic || "AND")}
              <span>邏輯組合</span>
            </button>
            <div class="lane" data-drop-kind="action" data-drop-branch="${html(branch.id)}">
              <div class="lane-head"><b>行為</b><span>依 step 順序執行</span></div>
              <div class="node-list">
                ${(branch.actions || []).map((node, index) => nodeCard(branch, "action", node, index)).join("") || '<div class="empty">從左側加入行為節點</div>'}
              </div>
            </div>
          </div>
        </section>
      `).join("");
    }

    function renderInspector() {
      const { branch, node } = selectedNodeRef();
      if (!branch) return;
      $("selectedBadge").textContent = selected.kind === "branch" || !node ? "分支" : (selected.kind === "condition" ? "條件節點" : "行為節點");
      if (selected.kind === "branch" || !node) {
        $("inspector").innerHTML = `
          <div class="inspector-card">
            <label class="field">分支名稱<input data-bind-branch="name" value="${html(branch.name || "")}"></label>
            <div class="two-col">
              <label class="field">邏輯<select data-bind-branch="logic"><option value="AND">AND：全部成立</option><option value="OR">OR：任一成立</option></select></label>
              <label class="field">優先權<input data-bind-branch="priority" type="number" value="${Number(branch.priority || 0)}"></label>
            </div>
            <div class="two-col">
              <label class="field">冷卻秒數<input data-bind-branch="cooldown_seconds" type="number" min="0" value="${Number(branch.cooldown_seconds || 0)}"></label>
              <label class="field">最大執行次數<input data-bind-branch="max_runs" type="number" min="1" value="${Number(branch.max_runs || 100)}"></label>
            </div>
            <div class="hint">同時符合多個分支時，優先權較高的分支會先執行。冷卻時間可避免短時間重複下單。</div>
          </div>`;
        document.querySelector('[data-bind-branch="logic"]').value = branch.logic || "AND";
        return;
      }
      if (selected.kind === "condition") renderConditionInspector(node);
      else renderActionInspector(node);
    }

    function renderConditionInspector(node) {
      const needsValue = !["ma_position", "bb_position", "has_position"].includes(node.type);
      $("inspector").innerHTML = `
        <div class="inspector-card">
          <label class="field">條件類型
            <select data-bind-node="type">
              ${CONDITION_TYPES.map((item) => `<option value="${item}">${html(CONDITION_LABELS[item] || item)}</option>`).join("")}
            </select>
          </label>
          ${needsValue ? `<label class="field">判斷數值<input data-bind-node="value" type="number" step="0.01" value="${html(node.value ?? "")}"></label>` : ""}
          ${node.type === "ma_position" ? `
            <div class="two-col">
              <label class="field">MA 週期<input data-bind-node="period" type="number" min="1" value="${Number(node.period || 50)}"></label>
              <label class="field">位置<select data-bind-node="position"><option value="above">上方</option><option value="below">下方</option></select></label>
            </div>` : ""}
          ${node.type === "bb_position" ? `
            <label class="field">布林位置<select data-bind-node="position">
              <option value="above_mid">中線上方</option>
              <option value="below_mid">中線下方</option>
              <option value="above_upper">上軌上方</option>
              <option value="below_lower">下軌下方</option>
            </select></label>` : ""}
          ${node.type === "has_position" ? `
            <label class="field">持倉條件<select data-bind-node="value_bool"><option value="true">有持倉</option><option value="false">沒有持倉</option></select></label>` : ""}
        </div>`;
      document.querySelector('[data-bind-node="type"]').value = node.type;
      const position = document.querySelector('[data-bind-node="position"]');
      if (position) position.value = node.position || (node.type === "bb_position" ? "above_mid" : "above");
      const boolField = document.querySelector('[data-bind-node="value_bool"]');
      if (boolField) boolField.value = node.value === false ? "false" : "true";
    }

    function renderActionInspector(node) {
      const percentAction = ["buy_percent", "sell_percent"].includes(node.type);
      const amountAction = node.type === "buy_amount";
      const tradableAction = !["close_all", "hold"].includes(node.type);
      $("inspector").innerHTML = `
        <div class="inspector-card">
          <label class="field">行為類型
            <select data-bind-node="type">
              ${ACTION_TYPES.map((item) => `<option value="${item}">${html(ACTION_LABELS[item] || item)}</option>`).join("")}
            </select>
          </label>
          <div class="two-col">
            <label class="field">Step<input data-bind-node="step" type="number" min="1" value="${Number(node.step || 1)}"></label>
            <label class="field">委託型態<select data-bind-node="order_type"><option value="market">市價</option><option value="limit">限價</option></select></label>
          </div>
          ${percentAction ? `<label class="field">百分比<input data-bind-node="percent" type="number" step="0.01" min="0" max="100" value="${html(node.percent ?? 10)}"></label>` : ""}
          ${amountAction ? `<label class="field">買入點數<input data-bind-node="amount_points" type="number" step="1" min="0" value="${html(node.amount_points ?? 100)}"></label>` : ""}
          ${tradableAction ? `<label class="field">限價價格<input data-bind-node="limit_price_points" type="number" step="0.01" min="0" value="${html(node.limit_price_points ?? "")}" placeholder="市價單可留空"></label>` : ""}
          <div class="hint">相同分支的行為會依 step 由小到大執行；分批買賣請使用不同 step。</div>
        </div>`;
      document.querySelector('[data-bind-node="type"]').value = node.type;
      document.querySelector('[data-bind-node="order_type"]').value = node.order_type || "market";
    }

    function validateWorkflow() {
      const issues = [];
      if (!workflow.branches.length) issues.push({ level: "err", text: "至少需要一個策略分支。" });
      workflow.branches.forEach((branch) => {
        if (!branch.conditions.length) issues.push({ level: "err", text: `${branch.name} 沒有條件節點。` });
        if (!branch.actions.length) issues.push({ level: "err", text: `${branch.name} 沒有行為節點。` });
        branch.actions.forEach((action) => {
          if (["buy_percent", "sell_percent"].includes(action.type) && (action.percent <= 0 || action.percent > 100)) {
            issues.push({ level: "err", text: `${branch.name} 的百分比行為必須在 0 到 100 之間。` });
          }
          if (action.type === "buy_amount" && action.amount_points <= 0) {
            issues.push({ level: "err", text: `${branch.name} 的固定買入點數必須大於 0。` });
          }
        });
        if (!branch.cooldown_seconds) issues.push({ level: "warn", text: `${branch.name} 沒有冷卻時間，可能頻繁觸發。` });
      });
      return issues;
    }

    function renderValidation() {
      const issues = validateWorkflow();
      const badge = $("validationBadge");
      const list = $("validationList");
      if (!issues.length) {
        badge.className = "badge ok";
        badge.textContent = "可儲存";
        list.innerHTML = '<li>目前未偵測到格式問題。</li>';
        return;
      }
      const hasError = issues.some((item) => item.level === "err");
      badge.className = `badge ${hasError ? "err" : "warn"}`;
      badge.textContent = hasError ? "需修正" : "有提醒";
      list.innerHTML = issues.map((item) => `<li class="${item.level}">${html(item.text)}</li>`).join("");
    }

    function syncJson() {
      $("jsonOut").value = JSON.stringify(workflow, null, 2);
    }

    function setStatus(message, good = true) {
      const el = $("status");
      el.textContent = message || "";
      el.style.color = good ? "var(--muted)" : "var(--red)";
    }

    function render() {
      workflow = normalizeWorkflow(workflow);
      if (!branchById(selected.branchId)) selected = { branchId: workflow.branches[0]?.id || "entry", kind: "branch", index: -1 };
      $("strategyName").value = workflow.name || "";
      $("strategyDescription").value = workflow.description || "";
      renderSummary();
      renderTabs();
      renderCanvas();
      renderInspector();
      renderValidation();
      syncJson();
    }

    function addBranch(template) {
      let branch;
      if (template === "breakout") {
        branch = {
          id: uid("branch"), name: "突破追蹤", priority: 30, logic: "AND", cooldown_seconds: 1800, max_runs: 20,
          conditions: [{ type: "price_above", value: 100000 }, { type: "rsi_above", value: 55 }, { type: "ma_position", period: 20, position: "above" }],
          actions: [{ type: "buy_percent", percent: 15, step: 1, order_type: "market" }]
        };
      } else if (template === "risk") {
        branch = {
          id: uid("branch"), name: "風控平倉", priority: 90, logic: "OR", cooldown_seconds: 60, max_runs: 100,
          conditions: [{ type: "stop_loss_percent", value: 8 }, { type: "take_profit_percent", value: 18 }],
          actions: [{ type: "close_all", step: 1, order_type: "market" }]
        };
      } else {
        branch = {
          id: uid("branch"), name: "新策略分支", priority: 0, logic: "AND", cooldown_seconds: 300, max_runs: 100,
          conditions: [defaultCondition("price_below")],
          actions: [defaultAction("buy_percent")]
        };
      }
      workflow.branches.push(branch);
      selected = { branchId: branch.id, kind: "branch", index: -1 };
      render();
    }

    function addNode(kind, type) {
      const branch = branchById(selected.branchId);
      if (!branch) return;
      if (kind === "condition") {
        branch.conditions.push(defaultCondition(type));
        selected = { branchId: branch.id, kind: "condition", index: branch.conditions.length - 1 };
      } else {
        const action = defaultAction(type);
        action.step = branch.actions.length + 1;
        branch.actions.push(action);
        selected = { branchId: branch.id, kind: "action", index: branch.actions.length - 1 };
      }
      render();
    }

    function moveNode(ref, direction) {
      const [kind, branchId, indexText] = ref.split(":");
      const branch = branchById(branchId);
      const list = kind === "condition" ? branch.conditions : branch.actions;
      const index = Number(indexText);
      const target = direction === "left" ? index - 1 : index + 1;
      if (!list || target < 0 || target >= list.length) return;
      const [item] = list.splice(index, 1);
      list.splice(target, 0, item);
      selected = { branchId: branch.id, kind, index: target };
      render();
    }

    function handleClick(event) {
      const branchBtn = event.target.closest("[data-add-branch]");
      if (branchBtn) return addBranch();
      const templateBtn = event.target.closest("[data-template]");
      if (templateBtn) return addBranch(templateBtn.dataset.template);
      const nodeBtn = event.target.closest("[data-add-node]");
      if (nodeBtn) {
        const [kind, type] = nodeBtn.dataset.addNode.split(":");
        return addNode(kind, type);
      }
      const controlBtn = event.target.closest("[data-control]");
      if (controlBtn) {
        const branch = branchById(selected.branchId);
        if (!branch) return;
        if (controlBtn.dataset.control === "cooldown300") branch.cooldown_seconds = 300;
        if (controlBtn.dataset.control === "cooldown3600") branch.cooldown_seconds = 3600;
        if (controlBtn.dataset.control === "once") branch.max_runs = 1;
        selected = { branchId: branch.id, kind: "branch", index: -1 };
        render();
        return;
      }
      const nodeCardEl = event.target.closest("[data-node-ref]");
      if (nodeCardEl && !event.target.closest(".node-tools")) {
        const [kind, branchId, indexText] = nodeCardEl.dataset.nodeRef.split(":");
        selected = { branchId, kind, index: Number(indexText) };
        render();
        return;
      }
      const selectBranch = event.target.closest("[data-select-branch]");
      if (selectBranch) {
        selected = { branchId: selectBranch.dataset.selectBranch, kind: "branch", index: -1 };
        render();
        return;
      }
      const duplicateBranch = event.target.closest("[data-duplicate-branch]");
      if (duplicateBranch) {
        const source = branchById(duplicateBranch.dataset.duplicateBranch);
        const copy = JSON.parse(JSON.stringify(source));
        copy.id = uid("branch");
        copy.name = `${copy.name} 副本`;
        workflow.branches.push(copy);
        selected = { branchId: copy.id, kind: "branch", index: -1 };
        render();
        return;
      }
      const deleteBranch = event.target.closest("[data-delete-branch]");
      if (deleteBranch && workflow.branches.length > 1) {
        workflow.branches = workflow.branches.filter((branch) => branch.id !== deleteBranch.dataset.deleteBranch);
        selected = { branchId: workflow.branches[0].id, kind: "branch", index: -1 };
        render();
        return;
      }
      const deleteNode = event.target.closest("[data-delete-node]");
      if (deleteNode) {
        const [kind, branchId, indexText] = deleteNode.dataset.deleteNode.split(":");
        const branch = branchById(branchId);
        const list = kind === "condition" ? branch.conditions : branch.actions;
        list.splice(Number(indexText), 1);
        selected = { branchId, kind: "branch", index: -1 };
        render();
        return;
      }
      const move = event.target.closest("[data-move-node]");
      if (move) {
        const parts = move.dataset.moveNode.split(":");
        moveNode(parts.slice(0, 3).join(":"), parts[3]);
      }
    }

    function handleInput(event) {
      const branchKey = event.target.dataset.bindBranch;
      const nodeKey = event.target.dataset.bindNode;
      if (event.target.id === "strategyName") {
        workflow.name = event.target.value.slice(0, 80);
        syncJson();
        return renderSummary();
      }
      if (event.target.id === "strategyDescription") {
        workflow.description = event.target.value.slice(0, 160);
        return syncJson();
      }
      if (!branchKey && !nodeKey) return;
      const { branch, node } = selectedNodeRef();
      if (branchKey) {
        branch[branchKey] = ["priority", "cooldown_seconds", "max_runs"].includes(branchKey)
          ? clampNumber(event.target.value, 0)
          : event.target.value;
      }
      if (node && nodeKey) {
        if (nodeKey === "type") {
          const oldStep = node.step || 1;
          const replacement = selected.kind === "condition" ? defaultCondition(event.target.value) : defaultAction(event.target.value);
          if (selected.kind === "action") replacement.step = oldStep;
          Object.keys(node).forEach((key) => delete node[key]);
          Object.assign(node, replacement);
        } else if (nodeKey === "value_bool") {
          node.value = event.target.value === "true";
        } else if (["value", "period", "step", "percent", "amount_points", "limit_price_points"].includes(nodeKey)) {
          const value = clampNumber(event.target.value, 0);
          if (nodeKey === "limit_price_points" && value <= 0) delete node.limit_price_points;
          else node[nodeKey] = value;
        } else {
          node[nodeKey] = event.target.value;
        }
      }
      render();
    }

    function handleDragStart(event) {
      const card = event.target.closest("[data-node-ref]");
      if (!card) return;
      dragRef = card.dataset.nodeRef;
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", dragRef);
    }

    function handleDragOver(event) {
      const lane = event.target.closest("[data-drop-kind]");
      if (!lane || !dragRef) return;
      const [kind] = dragRef.split(":");
      if (kind !== lane.dataset.dropKind) return;
      event.preventDefault();
      lane.classList.add("drag-over");
    }

    function handleDragLeave(event) {
      const lane = event.target.closest("[data-drop-kind]");
      if (lane) lane.classList.remove("drag-over");
    }

    function handleDrop(event) {
      const lane = event.target.closest("[data-drop-kind]");
      if (!lane || !dragRef) return;
      const [kind, fromBranchId, fromIndexText] = dragRef.split(":");
      if (kind !== lane.dataset.dropKind) return;
      event.preventDefault();
      lane.classList.remove("drag-over");
      const toBranch = branchById(lane.dataset.dropBranch);
      const fromBranch = branchById(fromBranchId);
      const fromList = kind === "condition" ? fromBranch.conditions : fromBranch.actions;
      const toList = kind === "condition" ? toBranch.conditions : toBranch.actions;
      const fromIndex = Number(fromIndexText);
      const [node] = fromList.splice(fromIndex, 1);
      let toIndex = toList.length;
      const targetCard = event.target.closest("[data-node-ref]");
      if (targetCard) {
        const [, targetBranchId, targetIndexText] = targetCard.dataset.nodeRef.split(":");
        if (targetBranchId === toBranch.id) toIndex = Number(targetIndexText);
      }
      if (fromList === toList && fromIndex < toIndex) toIndex -= 1;
      toList.splice(Math.max(0, toIndex), 0, node);
      selected = { branchId: toBranch.id, kind, index: Math.max(0, toIndex) };
      dragRef = null;
      render();
    }

    function importJson() {
      try {
        workflow = normalizeWorkflow(JSON.parse($("jsonOut").value || "{}"));
        selected = { branchId: workflow.branches[0].id, kind: "branch", index: -1 };
        render();
        setStatus("已套用 JSON。");
      } catch (error) {
        setStatus(`JSON 格式錯誤：${error.message}`, false);
      }
    }

    function saveWorkflow() {
      workflow = normalizeWorkflow(workflow);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(workflow, null, 2));
      setStatus("已儲存。回交易頁按「載入編輯器結果」即可使用。");
    }

    async function copyWorkflow() {
      const text = JSON.stringify(normalizeWorkflow(workflow), null, 2);
      try {
        await navigator.clipboard.writeText(text);
        setStatus("已複製 JSON。");
      } catch (_) {
        $("jsonOut").focus();
        $("jsonOut").select();
        document.execCommand("copy");
        setStatus("已選取 JSON，可直接複製。");
      }
    }

    function bindEvents() {
      document.addEventListener("click", handleClick);
      document.addEventListener("input", handleInput);
      document.addEventListener("change", handleInput);
      document.addEventListener("dragstart", handleDragStart);
      document.addEventListener("dragover", handleDragOver);
      document.addEventListener("dragleave", handleDragLeave);
      document.addEventListener("drop", handleDrop);
      $("templateBtn").addEventListener("click", () => {
        workflow = templateWorkflow();
        selected = { branchId: "entry", kind: "branch", index: -1 };
        render();
        setStatus("已載入標準範例。");
      });
      $("importBtn").addEventListener("click", importJson);
      $("saveBtn").addEventListener("click", saveWorkflow);
      $("copyBtn").addEventListener("click", copyWorkflow);
      $("jsonOut").addEventListener("input", () => setStatus("JSON 已修改，按「套用 JSON」才會更新畫布。"));
    }

    function boot() {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        try { workflow = normalizeWorkflow(JSON.parse(saved)); } catch (_) { workflow = templateWorkflow(); }
      }
      selected = { branchId: workflow.branches[0]?.id || "entry", kind: "branch", index: -1 };
      bindEvents();
      render();
      window.HackmeTradingWorkflowEditor = {
        getWorkflow: () => normalizeWorkflow(workflow),
        setWorkflow: (value) => { workflow = normalizeWorkflow(value); render(); }
      };
    }

    boot();
