"""Pure workflow validation and decision helpers."""

import json
from datetime import datetime


def condition_label(cond):
    if not isinstance(cond, dict):
        return str(cond)
    if "AND" in cond:
        parts = cond["AND"] if isinstance(cond["AND"], list) else []
        return "AND(" + ", ".join(condition_label(p) for p in parts) + ")"
    if "OR" in cond:
        parts = cond["OR"] if isinstance(cond["OR"], list) else []
        return "OR(" + ", ".join(condition_label(p) for p in parts) + ")"
    if "NOT" in cond:
        return "NOT(" + condition_label(cond["NOT"]) + ")"
    ctype = str(cond.get("type") or "always")
    value = cond.get("value")
    period = cond.get("period")
    position = cond.get("position")
    labels = {
        "always": "無條件",
        "price_above": f"價格≥{value}",
        "price_below": f"價格≤{value}",
        "rsi_above": f"RSI≥{value}",
        "rsi_below": f"RSI≤{value}",
        "kd_above": f"KD≥{value}",
        "kd_below": f"KD≤{value}",
        "ma_position": f"MA{period}{' 上方' if position == 'above' else ' 下方'}",
        "bb_position": f"BB {position}",
        "has_position": f"持倉={'是' if value else '否'}",
        "stop_loss_percent": f"止損≤-{value}%",
        "take_profit_percent": f"止盈≥{value}%",
    }
    return labels.get(ctype, ctype)


def validate_workflow(
    value,
    *,
    validate_workflow_graph_func,
    to_int,
    condition_types,
    action_types,
):
    if not value:
        return None
    if isinstance(value, str):
        try:
            workflow = json.loads(value)
        except Exception as exc:
            raise ValueError("workflow_json must be valid JSON") from exc
    elif isinstance(value, dict):
        workflow = value
    else:
        raise ValueError("workflow_json must be an object")
    nodes = workflow.get("nodes")
    edges = workflow.get("edges")
    if isinstance(nodes, list) or isinstance(edges, list):
        return validate_workflow_graph_func(workflow)
    branches = workflow.get("branches")
    if not isinstance(branches, list) or not branches:
        raise ValueError("workflow must contain at least one branch")
    clean_branches = []
    for index, branch in enumerate(branches[:20], start=1):
        if not isinstance(branch, dict):
            raise ValueError("workflow branch must be an object")
        logic = str(branch.get("logic") or "AND").upper()
        if logic not in {"AND", "OR"}:
            raise ValueError("workflow branch logic must be AND or OR")
        conditions = branch.get("conditions") or [{"type": "always"}]
        actions = branch.get("actions") or [{"type": "hold", "step": 1}]
        if not isinstance(conditions, list) or not isinstance(actions, list):
            raise ValueError("workflow branch conditions/actions must be arrays")
        clean_conditions = []
        for condition in conditions[:20]:
            if not isinstance(condition, dict):
                raise ValueError("workflow condition must be an object")
            ctype = str(condition.get("type") or "always").strip()
            if ctype != "always" and ctype not in condition_types:
                raise ValueError(f"unsupported workflow condition: {ctype}")
            clean = {"type": ctype}
            for key in ("value", "period", "position", "operator"):
                if key in condition:
                    clean[key] = condition.get(key)
            clean_conditions.append(clean)
        clean_actions = []
        for action in actions[:20]:
            if not isinstance(action, dict):
                raise ValueError("workflow action must be an object")
            atype = str(action.get("type") or "hold").strip()
            if atype not in action_types:
                raise ValueError(f"unsupported workflow action: {atype}")
            clean = {
                "type": atype,
                "step": to_int(action.get("step", len(clean_actions) + 1), name="workflow action step", minimum=1, maximum=1000),
                "order_type": str(action.get("order_type") or "market").strip().lower(),
            }
            if clean["order_type"] not in {"market", "limit"}:
                raise ValueError("workflow action order_type must be market or limit")
            for key in ("percent", "amount_points", "limit_price_points"):
                if key in action and action.get(key) not in (None, ""):
                    clean[key] = float(action.get(key))
            clean_actions.append(clean)
        clean_branches.append(
            {
                "id": str(branch.get("id") or f"branch_{index}")[:80],
                "name": str(branch.get("name") or f"策略分支 {index}")[:80],
                "priority": to_int(branch.get("priority", 0), name="workflow priority", minimum=-1000, maximum=1000),
                "logic": logic,
                "cooldown_seconds": to_int(branch.get("cooldown_seconds", 0), name="workflow cooldown_seconds", minimum=0, maximum=86400),
                "max_runs": to_int(branch.get("max_runs", 1000), name="workflow max_runs", minimum=1, maximum=1000),
                "conditions": clean_conditions,
                "actions": clean_actions,
            }
        )
    clean = {"version": 1, "strategy_kind": "workflow", "branches": clean_branches}
    if workflow.get("source"):
        clean["source"] = str(workflow.get("source"))[:80]
    return clean


def validate_workflow_graph(
    workflow,
    *,
    to_int,
    condition_types,
    action_types,
    node_types,
    ports,
):
    nodes = workflow.get("nodes")
    edges = workflow.get("edges")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("workflow graph must contain nodes")
    if not isinstance(edges, list):
        raise ValueError("workflow graph edges must be an array")
    clean_nodes = []
    node_ids = set()
    start_count = 0
    for index, node in enumerate(nodes[:100], start=1):
        if not isinstance(node, dict):
            raise ValueError("workflow graph node must be an object")
        node_id = str(node.get("id") or f"node_{index}")[:80]
        if not node_id or node_id in node_ids:
            raise ValueError("workflow graph node ids must be unique")
        node_ids.add(node_id)
        node_type = str(node.get("type") or "condition").strip().lower()
        if node_type not in node_types:
            raise ValueError(f"unsupported workflow node type: {node_type}")
        clean = {
            "id": node_id,
            "type": node_type,
            "label": str(node.get("label") or node.get("name") or node_id)[:80],
            "x": to_int(node.get("x", index * 120), name="node x", minimum=-100000, maximum=100000),
            "y": to_int(node.get("y", 120), name="node y", minimum=-100000, maximum=100000),
            "inputs": [str(port)[:24] for port in (node.get("inputs") or ["in"]) if str(port) in ports],
            "outputs": [str(port)[:24] for port in (node.get("outputs") or ["out"]) if str(port) in ports],
            "priority": to_int(node.get("priority", 0), name="node priority", minimum=-1000, maximum=1000),
        }
        if node_type == "start":
            start_count += 1
            clean["inputs"] = []
            clean["outputs"] = ["out"]
        elif node_type == "condition":
            condition = node.get("condition") if isinstance(node.get("condition"), dict) else node
            ctype = str(condition.get("type") or "always").strip()
            if ctype != "always" and ctype not in condition_types and not any(key in condition for key in ("AND", "OR", "NOT")):
                raise ValueError(f"unsupported workflow condition: {ctype}")
            clean["condition"] = condition
            clean["outputs"] = ["true", "false"]
        elif node_type == "logic":
            operator = str(node.get("operator") or node.get("logic") or "AND").strip().upper()
            if operator not in {"AND", "OR", "NOT"}:
                raise ValueError("workflow logic node must be AND, OR, or NOT")
            clean["operator"] = operator
            clean["outputs"] = ["true", "false"]
        elif node_type == "action":
            action = node.get("action") if isinstance(node.get("action"), dict) else node
            atype = str(action.get("type") or "hold").strip()
            if atype not in action_types:
                raise ValueError(f"unsupported workflow action: {atype}")
            clean_action = {
                "type": atype,
                "step": to_int(action.get("step", 1), name="workflow action step", minimum=1, maximum=1000),
                "order_type": str(action.get("order_type") or "market").strip().lower(),
            }
            if clean_action["order_type"] not in {"market", "limit"}:
                raise ValueError("workflow action order_type must be market or limit")
            for key in ("percent", "amount_points", "limit_price_points"):
                if key in action and action.get(key) not in (None, ""):
                    clean_action[key] = float(action.get(key))
            clean["action"] = clean_action
            clean["outputs"] = ["out"]
        elif node_type == "control":
            clean["cooldown_seconds"] = to_int(node.get("cooldown_seconds", 0), name="node cooldown_seconds", minimum=0, maximum=86400)
            clean["max_runs"] = to_int(node.get("max_runs", 1000), name="node max_runs", minimum=1, maximum=1000)
            clean["outputs"] = ["then", "wait"]
        clean_nodes.append(clean)
    if start_count > 1:
        raise ValueError("workflow graph can contain at most one start node")
    clean_edges = []
    seen_edges = set()
    for index, edge in enumerate(edges[:200], start=1):
        if not isinstance(edge, dict):
            raise ValueError("workflow graph edge must be an object")
        source = str(edge.get("from") or edge.get("source") or "")[:80]
        target = str(edge.get("to") or edge.get("target") or "")[:80]
        if source not in node_ids or target not in node_ids:
            raise ValueError("workflow graph edge references unknown node")
        from_port = str(edge.get("from_port") or edge.get("source_port") or "out").strip().lower()
        to_port = str(edge.get("to_port") or edge.get("target_port") or "in").strip().lower()
        if from_port not in ports or to_port not in ports:
            raise ValueError("workflow graph edge port is invalid")
        source_node = next((node for node in clean_nodes if node["id"] == source), None)
        target_node = next((node for node in clean_nodes if node["id"] == target), None)
        if source_node and from_port not in set(source_node.get("outputs") or []):
            raise ValueError("workflow graph edge uses unavailable source port")
        if target_node and to_port not in set(target_node.get("inputs") or ["in"]):
            raise ValueError("workflow graph edge uses unavailable target port")
        edge_id = str(edge.get("id") or f"edge_{index}")[:80]
        edge_key = (source, from_port, target, to_port)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        clean_edges.append({"id": edge_id, "from": source, "from_port": from_port, "to": target, "to_port": to_port})
    action_ids = {node["id"] for node in clean_nodes if node["type"] == "action"}
    if not action_ids:
        raise ValueError("workflow graph must contain at least one action node")
    start_node_id = str(workflow.get("start_node_id") or next((node["id"] for node in clean_nodes if node["type"] == "start"), clean_nodes[0]["id"]))[:80]
    if start_node_id not in node_ids:
        raise ValueError("workflow graph start_node_id references unknown node")
    outgoing = {}
    for edge in clean_edges:
        outgoing.setdefault(edge["from"], []).append(edge["to"])
    reachable = set()
    stack = [start_node_id]
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        stack.extend(outgoing.get(node_id, []))
    if not action_ids & reachable:
        raise ValueError("workflow graph action nodes must be reachable from start")
    return {
        "version": 2,
        "strategy_kind": "workflow_graph",
        "source": str(workflow.get("source") or "workflow_editor")[:80],
        "name": str(workflow.get("name") or "Workflow Strategy")[:80],
        "description": str(workflow.get("description") or "")[:160],
        "start_node_id": start_node_id,
        "nodes": clean_nodes,
        "edges": clean_edges,
    }


def workflow_condition_hit(condition, context):
    if not isinstance(condition, dict):
        return False
    if "AND" in condition:
        items = condition.get("AND") if isinstance(condition.get("AND"), list) else []
        return bool(items) and all(workflow_condition_hit(item, context) for item in items)
    if "OR" in condition:
        items = condition.get("OR") if isinstance(condition.get("OR"), list) else []
        return bool(items) and any(workflow_condition_hit(item, context) for item in items)
    if "NOT" in condition:
        target = condition.get("NOT")
        return not workflow_condition_hit(target if isinstance(target, dict) else {"type": str(target)}, context)
    ctype = str(condition.get("type") or "always")
    price = float(context.get("price") or 0)
    low_price = float(context.get("window_low_price") or price or 0)
    high_price = float(context.get("window_high_price") or price or 0)
    value = float(condition.get("value") or 0)
    if ctype == "always":
        return True
    if ctype == "price_below":
        return low_price > 0 and low_price <= value
    if ctype == "price_above":
        return high_price > 0 and high_price >= value
    if ctype == "has_position":
        return bool(context.get("has_position")) == bool(condition.get("value", True))
    if ctype == "rsi_above":
        return context.get("rsi") is not None and float(context["rsi"]) >= value
    if ctype == "rsi_below":
        return context.get("rsi") is not None and float(context["rsi"]) <= value
    if ctype == "kd_above":
        return context.get("kd") is not None and float(context["kd"]) >= value
    if ctype == "kd_below":
        return context.get("kd") is not None and float(context["kd"]) <= value
    if ctype == "ma_position":
        period = int(condition.get("period") or 50)
        ma_value = context.get(f"ma{period}")
        position = str(condition.get("position") or "above")
        return ma_value is not None and ((price >= ma_value) if position == "above" else (price <= ma_value))
    if ctype == "bb_position":
        position = str(condition.get("position") or "above_mid")
        if position == "above_mid":
            return context.get("bb_mid") is not None and price >= float(context["bb_mid"])
        if position == "below_mid":
            return context.get("bb_mid") is not None and price <= float(context["bb_mid"])
        if position == "above_upper":
            return (
                context.get("bb_upper") is not None
                and float(context.get("bb_std") or 0) > 0
                and price > float(context["bb_upper"])
            )
        if position == "below_lower":
            return (
                context.get("bb_lower") is not None
                and float(context.get("bb_std") or 0) > 0
                and price < float(context["bb_lower"])
            )
    if ctype == "stop_loss_percent":
        pnl = context.get("pnl_low_percent")
        if pnl is None:
            pnl = context.get("pnl_percent")
        return pnl is not None and bool(context.get("has_position")) and pnl <= -abs(value)
    if ctype == "take_profit_percent":
        pnl = context.get("pnl_high_percent")
        if pnl is None:
            pnl = context.get("pnl_percent")
        return pnl is not None and bool(context.get("has_position")) and pnl >= abs(value)
    return False


def workflow_graph_decision(
    workflow,
    *,
    context,
    run_count=0,
    last_run_at=None,
    execution_state=None,
    workflow_condition_hit_func=workflow_condition_hit,
):
    nodes = {node["id"]: node for node in workflow.get("nodes") or []}
    incoming = {}
    for edge in workflow.get("edges") or []:
        incoming.setdefault(edge["to"], []).append(edge)
    memo = {}
    visiting = set()

    def node_value(node_id):
        if node_id in memo:
            return memo[node_id]
        if node_id in visiting:
            raise ValueError("workflow graph contains a cycle")
        node = nodes.get(node_id)
        if not node:
            return False
        visiting.add(node_id)
        ntype = node.get("type")
        if ntype == "start":
            result = True
        elif ntype == "condition":
            result = workflow_condition_hit_func(node.get("condition") or {}, context)
        elif ntype == "logic":
            values = [edge_value(edge) for edge in incoming.get(node_id, [])]
            operator = str(node.get("operator") or "AND").upper()
            if operator == "OR":
                result = any(values)
            elif operator == "NOT":
                result = not (values[0] if values else False)
            else:
                result = bool(values) and all(values)
        elif ntype == "control":
            cooldown = int(node.get("cooldown_seconds") or 0)
            max_runs = int(node.get("max_runs") or 1000)
            result = int(run_count or 0) < max_runs
            if result and cooldown and last_run_at:
                try:
                    result = (datetime.now() - datetime.fromisoformat(str(last_run_at))).total_seconds() >= cooldown
                except Exception:
                    result = True
            if result:
                result = all(edge_value(edge) for edge in incoming.get(node_id, [])) if incoming.get(node_id) else True
        else:
            result = all(edge_value(edge) for edge in incoming.get(node_id, [])) if incoming.get(node_id) else False
        visiting.remove(node_id)
        memo[node_id] = bool(result)
        return memo[node_id]

    def edge_value(edge):
        value = node_value(edge["from"])
        if edge.get("from_port") == "false":
            return not value
        if edge.get("from_port") in {"true", "then", "out"}:
            return value
        return value

    executed = set((execution_state or {}).get("executed_action_ids") or [])
    branch_counts = (execution_state or {}).get("branch_step_counts") or {}
    actions = sorted(
        (node for node in nodes.values() if node.get("type") == "action"),
        key=lambda node: (-int(node.get("priority") or 0), int((node.get("action") or {}).get("step") or 1)),
    )
    for node in actions:
        action = node.get("action") or {"type": "hold", "step": 1}
        action_id = node["id"]
        if action.get("type") != "close_all" and action_id in executed:
            continue
        if action.get("type") != "close_all" and int(action.get("step") or 1) <= int(branch_counts.get(action_id, 0)):
            continue
        gates = incoming.get(action_id) or []
        matched = all(edge_value(edge) for edge in gates) if gates else False
        if matched:
            return {"branch": node, "action": action, "reason": node.get("label") or action_id, "action_id": action_id}
    return None


def workflow_decision(
    workflow,
    *,
    context,
    run_count=0,
    last_run_at=None,
    execution_state=None,
    validate_workflow_func,
    workflow_graph_decision_func,
    workflow_condition_hit_func=workflow_condition_hit,
):
    workflow = validate_workflow_func(workflow)
    if workflow.get("strategy_kind") == "workflow_graph":
        return workflow_graph_decision_func(
            workflow,
            context=context,
            run_count=run_count,
            last_run_at=last_run_at,
            execution_state=execution_state,
        )
    branches = sorted(workflow["branches"], key=lambda row: int(row.get("priority") or 0), reverse=True)
    now_dt = datetime.now()
    branch_counts = (execution_state or {}).get("branch_step_counts") or {}
    for branch in branches:
        cooldown = int(branch.get("cooldown_seconds") or 0)
        if cooldown and last_run_at:
            try:
                if (now_dt - datetime.fromisoformat(str(last_run_at))).total_seconds() < cooldown:
                    continue
            except Exception:
                pass
        conditions = branch.get("conditions") or [{"type": "always"}]
        hits = [workflow_condition_hit_func(condition, context) for condition in conditions]
        matched = all(hits) if branch.get("logic") == "AND" else any(hits)
        if not matched:
            continue
        fallback_count = int(run_count or 0) if workflow.get("source") == "legacy_condition" else 0
        step = int(branch_counts.get(branch.get("id"), fallback_count)) + 1
        actions = sorted(branch.get("actions") or [], key=lambda row: int(row.get("step") or 1))
        action = next((row for row in actions if int(row.get("step") or 1) >= step), None)
        if not action:
            continue
        return {"branch": branch, "action": action, "reason": branch.get("name") or branch.get("id") or "workflow"}
    return None
