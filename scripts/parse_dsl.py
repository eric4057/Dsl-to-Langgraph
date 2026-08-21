#!/usr/bin/env python3
"""Parse workflow DSL files into a LangGraph-oriented inventory.

Supports:
  - Dify YAML/JSON (kind: app + workflow.graph)
  - Generic nodes+edges YAML/JSON
  - LangFlow-ish / Flowise-ish nodes+edges JSON
  - n8n JSON (nodes + connections)

Usage:
  python3 parse_dsl.py path/to/dsl.yml [-o inventory.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise SystemExit("需要 PyYAML：pip install pyyaml") from exc
        return yaml.safe_load(text)
    if suffix == ".json" or text.lstrip().startswith(("{", "[")):
        return json.loads(text)
    try:
        import yaml

        return yaml.safe_load(text)
    except Exception:
        return json.loads(text)


def _detect(data: Any) -> str:
    if not isinstance(data, dict):
        return "unknown"
    if data.get("kind") == "app" or (
        isinstance(data.get("workflow"), dict) and "graph" in data["workflow"]
    ):
        return "dify"
    if "connections" in data and "nodes" in data:
        return "n8n"
    if "nodes" in data and ("edges" in data or "links" in data):
        sample = data["nodes"][0] if data["nodes"] else {}
        node_data = sample.get("data") if isinstance(sample, dict) else {}
        ntype = ""
        if isinstance(node_data, dict):
            ntype = str(node_data.get("type") or node_data.get("name") or "")
        blob = json.dumps(data).lower()
        if "langflow" in blob:
            return "langflow"
        if "flowise" in blob or "chatprompt" in ntype.lower():
            return "flowise"
        return "generic"
    if isinstance(data.get("data"), dict) and "nodes" in data["data"]:
        return "langflow"
    return "unknown"


def _truncate(value: Any, limit: int = 800) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 1] + "…"
    if isinstance(value, list):
        return [_truncate(item, limit) for item in value[:20]]
    if isinstance(value, dict):
        return {str(k): _truncate(v, min(limit, 400)) for k, v in list(value.items())[:30]}
    return value


def _prompt_excerpt(prompt_template: Any) -> str | list | dict | None:
    if prompt_template is None:
        return None
    if isinstance(prompt_template, str):
        return _truncate(prompt_template, 1200)
    if isinstance(prompt_template, list):
        parts = []
        for item in prompt_template:
            if isinstance(item, dict):
                role = item.get("role") or item.get("id") or ""
                text = item.get("text") or item.get("content") or ""
                if isinstance(text, list):
                    text = " ".join(str(x) for x in text)
                parts.append({"role": role, "text": _truncate(str(text), 600)})
            else:
                parts.append(_truncate(str(item), 600))
        return parts
    if isinstance(prompt_template, dict):
        return _truncate(prompt_template, 1200)
    return _truncate(str(prompt_template), 600)


def _dify_inventory(data: dict) -> dict[str, Any]:
    app = data.get("app") or {}
    graph = (data.get("workflow") or {}).get("graph") or {}
    nodes_raw = graph.get("nodes") or []
    edges_raw = graph.get("edges") or []
    nodes = []
    for node in nodes_raw:
        d = node.get("data") or {}
        nodes.append(
            {
                "id": str(node.get("id", "")),
                "type": d.get("type") or node.get("type"),
                "title": d.get("title") or "",
                "parent_id": node.get("parentId") or d.get("parent_id"),
                "hints": _dify_hints(d),
            }
        )
    edges = []
    for edge in edges_raw:
        edges.append(
            {
                "id": edge.get("id"),
                "source": str(edge.get("source", "")),
                "target": str(edge.get("target", "")),
                "source_handle": edge.get("sourceHandle"),
                "source_type": (edge.get("data") or {}).get("sourceType"),
                "target_type": (edge.get("data") or {}).get("targetType"),
            }
        )
    return {
        "source": "dify",
        "name": app.get("name") or data.get("name") or "",
        "mode": app.get("mode"),
        "nodes": nodes,
        "edges": edges,
        "type_counts": dict(Counter(n["type"] for n in nodes)),
        "external_hints": _collect_external_hints(nodes),
    }


def _dify_hints(d: dict) -> dict[str, Any]:
    """抽出 Dify node.data 遷移必要欄位（對齊 NODE_CONTRACT）。"""
    hints: dict[str, Any] = {}
    ntype = str(d.get("type") or "")

    if "dataset_ids" in d:
        hints["dataset_ids"] = d.get("dataset_ids")
    if "dataset_id" in d:
        hints["dataset_id"] = d.get("dataset_id")
    if "retrieval_mode" in d:
        hints["retrieval_mode"] = d.get("retrieval_mode")
    for key in ("multiple_retrieval_config", "single_retrieval_config"):
        if key in d and isinstance(d.get(key), dict):
            cfg = d[key]
            hints[key] = {
                "top_k": cfg.get("top_k"),
                "reranking_enable": cfg.get("reranking_enable"),
                "reranking_mode": cfg.get("reranking_mode"),
                "reranking_model": _truncate(cfg.get("reranking_model"), 200),
                "weights": cfg.get("weights"),
            }
    if "query_variable_selector" in d:
        hints["query_variable_selector"] = d.get("query_variable_selector")

    if "prompt_template" in d:
        hints["has_prompt"] = True
        hints["prompt_excerpt"] = _prompt_excerpt(d.get("prompt_template"))
    if "code" in d:
        hints["has_code"] = True
        hints["code_language"] = d.get("code_language")
        code = d.get("code")
        if isinstance(code, str):
            hints["code_excerpt"] = _truncate(code, 1000)
            hints["code_looks_like_citation"] = _text_looks_like_citation(code)
        if d.get("outputs") is not None:
            hints["code_outputs"] = _truncate(d.get("outputs"), 400)
        if d.get("variables") is not None:
            hints["code_variables"] = _truncate(d.get("variables"), 400)

    if ntype == "template-transform" and d.get("template") is not None:
        tmpl = str(d.get("template") or "")
        hints["template_excerpt"] = _truncate(tmpl, 800)
        hints["template_looks_like_citation"] = _text_looks_like_citation(tmpl)

    # question-classifier：classes.id 對應 edge.sourceHandle
    if "classes" in d:
        hints["classes"] = [
            {
                "id": str(c.get("id") or ""),
                "name": c.get("name") or c.get("id") or "",
            }
            for c in (d.get("classes") or [])
            if isinstance(c, dict)
        ]

    # if-else：cases.case_id 對應 edge.sourceHandle（含 false / 預設）
    if ntype == "if-else" and isinstance(d.get("cases"), list):
        cases_out = []
        for case in d.get("cases") or []:
            if not isinstance(case, dict):
                continue
            conds = []
            for cond in case.get("conditions") or []:
                if not isinstance(cond, dict):
                    continue
                conds.append(
                    {
                        "comparison_operator": cond.get("comparison_operator"),
                        "value": cond.get("value"),
                        "varType": cond.get("varType"),
                        "variable_selector": cond.get("variable_selector"),
                    }
                )
            cases_out.append(
                {
                    "case_id": str(case.get("case_id") or case.get("id") or ""),
                    "logical_operator": case.get("logical_operator"),
                    "conditions": conds,
                }
            )
        hints["cases"] = cases_out

    if "model" in d:
        model = d.get("model")
        if isinstance(model, dict):
            hints["model"] = model.get("name") or model.get("provider")
            if model.get("completion_params"):
                hints["completion_params"] = _truncate(model.get("completion_params"), 300)

    if ntype == "answer" and d.get("answer"):
        answer_tmpl = str(d.get("answer"))
        hints["answer_template_excerpt"] = _truncate(answer_tmpl, 600)
        hints["answer_looks_like_citation"] = _text_looks_like_citation(answer_tmpl)

    if ntype == "http-request":
        for key in ("method", "url", "headers", "params", "body", "timeout", "authorization"):
            if key in d and d.get(key) is not None:
                hints[key] = _truncate(d.get(key), 500)

    if ntype == "tool":
        for key in (
            "provider_id",
            "provider_name",
            "provider_type",
            "tool_name",
            "tool_label",
            "tool_configurations",
            "tool_parameters",
        ):
            if key in d and d.get(key) is not None:
                hints[key] = _truncate(d.get(key), 500)

    if ntype == "agent":
        for key in ("agent_parameters", "tools", "instruction", "query", "model"):
            if key in d and d.get(key) is not None:
                hints[key] = _truncate(d.get(key), 800)

    if ntype in {"iteration", "loop"}:
        for key in ("iterator_selector", "output_selector", "startNodeType", "is_parallel"):
            if key in d and d.get(key) is not None:
                hints[key] = _truncate(d.get(key), 300)

    if ntype == "parameter-extractor":
        for key in ("parameters", "instruction", "query", "model", "reasoning_mode"):
            if key in d and d.get(key) is not None:
                hints[key] = _truncate(d.get(key), 500)

    if hints.get("prompt_excerpt") is not None:
        hints["prompt_looks_like_citation"] = _text_looks_like_citation(
            _flatten_for_scan(hints.get("prompt_excerpt"))
        )
    return hints


def _flatten_for_scan(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _text_looks_like_citation(text: str) -> bool:
    """偵測引用／來源組裝工項（code／template／prompt／answer）。"""
    if not text:
        return False
    lowered = text.lower()
    markers = (
        "citation",
        "source_url",
        "source_path",
        "citation_map",
        "order_citation",
        "### 來源",
        "[[",
        "retriever_resource",
        "document id",
        "<document",
        "引用",
        "來源",
    )
    return any(
        (marker.lower() in lowered) if marker.isascii() else (marker in text)
        for marker in markers
    )


# 相容舊名稱
_code_looks_like_citation = _text_looks_like_citation


def _generic_inventory(data: dict, source: str) -> dict[str, Any]:
    if source == "langflow" and isinstance(data.get("data"), dict):
        data = data["data"]
    nodes_raw = data.get("nodes") or []
    edges_raw = data.get("edges") or data.get("links") or []
    nodes = []
    for node in nodes_raw:
        if not isinstance(node, dict):
            continue
        d = node.get("data") if isinstance(node.get("data"), dict) else {}
        ntype = (
            d.get("type")
            or d.get("name")
            or node.get("type")
            or (d.get("node") or {}).get("display_name")
            or "unknown"
        )
        title = d.get("title") or d.get("label") or node.get("name") or str(ntype)
        hints: dict[str, Any] = {}
        for key in ("template", "prompt", "system_message", "input_value"):
            if key in d:
                hints[key] = _truncate(d.get(key), 600)
        nodes.append(
            {
                "id": str(node.get("id", "")),
                "type": ntype,
                "title": title,
                "hints": hints,
            }
        )
    edges = []
    for edge in edges_raw:
        if not isinstance(edge, dict):
            continue
        edges.append(
            {
                "id": edge.get("id"),
                "source": str(edge.get("source") or edge.get("from") or ""),
                "target": str(edge.get("target") or edge.get("to") or ""),
                "source_handle": edge.get("sourceHandle") or edge.get("sourceHandleId"),
            }
        )
    return {
        "source": source,
        "name": data.get("name") or data.get("id") or "",
        "mode": data.get("mode"),
        "nodes": nodes,
        "edges": edges,
        "type_counts": dict(Counter(n["type"] for n in nodes)),
        "external_hints": _collect_external_hints(nodes),
    }


def _n8n_inventory(data: dict) -> dict[str, Any]:
    nodes = []
    name_to_id: dict[str, str] = {}
    for node in data.get("nodes") or []:
        node_id = str(node.get("id") or node.get("name") or "")
        name = str(node.get("name") or "")
        if name:
            name_to_id[name] = node_id
        if node_id:
            name_to_id.setdefault(node_id, node_id)
        nodes.append(
            {
                "id": node_id,
                "type": node.get("type"),
                "title": name,
                "hints": {
                    "parameters": _truncate(node.get("parameters"), 800)
                    if node.get("parameters")
                    else None
                },
            }
        )
    edges = []
    connections = data.get("connections") or {}
    for src_name, outputs in connections.items():
        if not isinstance(outputs, dict):
            continue
        source_id = name_to_id.get(str(src_name), str(src_name))
        for _out_name, chains in outputs.items():
            if not isinstance(chains, list):
                continue
            for chain in chains:
                if not isinstance(chain, list):
                    continue
                for link in chain:
                    if not isinstance(link, dict):
                        continue
                    target_name = str(link.get("node", ""))
                    edges.append(
                        {
                            "source": source_id,
                            "target": name_to_id.get(target_name, target_name),
                            "source_handle": link.get("type"),
                            "source_name": str(src_name),
                            "target_name": target_name,
                        }
                    )
    return {
        "source": "n8n",
        "name": data.get("name") or "",
        "mode": "workflow",
        "nodes": nodes,
        "edges": edges,
        "type_counts": dict(Counter(n["type"] for n in nodes)),
        "external_hints": _collect_external_hints(nodes),
    }


def _collect_external_hints(nodes: list[dict[str, Any]]) -> list[str]:
    hints: list[str] = []
    for node in nodes:
        t = str(node.get("type") or "").lower()
        title = str(node.get("title") or "")
        if "knowledge" in t or "retriev" in t or "vector" in t:
            hints.append(f"vector/kb:{title or t}")
        if "http" in t or "webhook" in t or t.endswith("request") or "httprequest" in t:
            hints.append(f"http:{title or t}")
        if t in {"tool", "agent"} or t.endswith(".tool") or t.startswith("n8n-nodes-base.tool"):
            hints.append(f"tool/agent:{title or t}")
        elif "agent" in t:
            hints.append(f"tool/agent:{title or t}")
        # Avoid over-matching bare "chat" in arbitrary type strings.
        if t in {"llm", "openai", "chat"} or t.endswith(".llm") or "llmgateway" in t:
            hints.append(f"llm:{title or t}")
        elif "openai" in t or re.search(r"(^|[.-])llm([.-]|$)", t):
            hints.append(f"llm:{title or t}")
        node_hints = node.get("hints") or {}
        if node_hints.get("reranking_enable") or (
            isinstance(node_hints.get("multiple_retrieval_config"), dict)
            and node_hints["multiple_retrieval_config"].get("reranking_enable")
        ):
            hints.append(f"rerank:{title or t}")
        cfg = node_hints.get("multiple_retrieval_config") or node_hints.get("single_retrieval_config")
        if isinstance(cfg, dict) and cfg.get("reranking_enable"):
            hints.append(f"rerank:{title or t}")
    seen: set[str] = set()
    out: list[str] = []
    for h in hints:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def parse(path: Path) -> dict[str, Any]:
    data = _load(path)
    source = _detect(data)
    if source == "dify":
        inv = _dify_inventory(data)
    elif source == "n8n":
        inv = _n8n_inventory(data)
    elif source in {"generic", "langflow", "flowise"}:
        inv = _generic_inventory(data, source)
    else:
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            inv = _generic_inventory(data, "langflow")
        elif isinstance(data, dict) and "nodes" in data:
            inv = _generic_inventory(data, "generic")
        else:
            inv = {
                "source": "unknown",
                "name": path.stem,
                "nodes": [],
                "edges": [],
                "type_counts": {},
                "external_hints": [],
                "error": "無法辨識 DSL 結構",
            }
    inv["file"] = str(path)
    inv["has_rag"] = _has_rag(inv)
    inv["has_citation"] = _has_citation_work(inv)
    inv["suggested_langgraph_nodes"] = _suggest_nodes(inv)
    # Dify 主軸：逐節點對照表（實作／合併／忽略）
    if inv.get("source") == "dify":
        inv["dify_node_mapping"] = _dify_node_mapping(inv)
        inv["dify_branch_edges"] = _dify_branch_edges(inv)
    return inv


def _has_rag(inv: dict[str, Any]) -> bool:
    counts = inv.get("type_counts") or {}
    for key in counts:
        lowered = str(key).lower()
        if any(token in lowered for token in ("knowledge", "retriev", "vector", "dataset")):
            return True
    for hint in inv.get("external_hints") or []:
        if str(hint).startswith("vector/kb:"):
            return True
    return False


def _slug_title(title: str, fallback: str) -> str:
    """ASCII slug；中文／純數字 title 改用 fallback（避免函式名含 CJK 或只剩數字）。"""
    text = (title or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    if not text or text.isdigit() or re.fullmatch(r"\d+", text):
        return fallback
    return text[:40]


def _dify_node_mapping(inv: dict[str, Any]) -> list[dict[str, Any]]:
    """Dify 節點 → LangGraph 建議（與 NODE_CONTRACT 對齊）。"""
    rows: list[dict[str, Any]] = []
    llm_i = 0
    http_i = 0
    code_i = 0
    for node in inv.get("nodes") or []:
        dtype = str(node.get("type") or "")
        title = str(node.get("title") or "")
        nid = str(node.get("id") or "")
        hints = node.get("hints") or {}
        action = "implement"
        lg_name: str | None = None
        note = ""

        if dtype in {"custom-note"}:
            action, note = "ignore", "文件用，不實作"
        elif dtype in {"template-transform", "assigner", "variable-aggregator"}:
            action, note = "merge", "glue：併入相鄰業務節點"
        elif dtype in {"loop-start", "loop-end", "iteration-start"}:
            action, note = "ignore", "迴圈結構標記"
        elif dtype == "start":
            lg_name = "normalize_input"
        elif dtype == "answer":
            lg_name = "answer"
        elif dtype == "llm":
            llm_i += 1
            lg_name = _slug_title(title, f"llm_{llm_i}")
            if not lg_name.endswith("_node") and "llm" not in lg_name:
                lg_name = f"{lg_name}_llm" if lg_name != f"llm_{llm_i}" else "llm_answer"
            if lg_name == "llm":
                lg_name = "llm_answer"
        elif dtype == "question-classifier":
            lg_name = "classify"
            note = "另需 route_after_classify；edge.sourceHandle=class.id"
        elif dtype == "if-else":
            lg_name = f"route_{_slug_title(title, nid[-4:] or 'cond')}"
            note = "純路由函式；edge.sourceHandle=case_id"
        elif dtype == "knowledge-retrieval":
            lg_name = "retrieve"
            note = "多 dataset → 多 collection 或合併檢索"
        elif dtype == "http-request":
            http_i += 1
            lg_name = _slug_title(title, f"http_{http_i}")
        elif dtype == "tool":
            lg_name = _slug_title(str(hints.get("tool_name") or title), "tool_call")
        elif dtype == "code":
            if hints.get("code_looks_like_citation"):
                action, lg_name = "merge", None
                note = "引用／來源 code → 併入 order_citations／build_context／answer"
            else:
                code_i += 1
                lg_name = _slug_title(title, f"transform_{code_i}")
        elif dtype == "agent":
            lg_name = "agent"
            note = "優先改寫成 structured LLM + 後續 tool／http 節點"
        elif dtype == "parameter-extractor":
            lg_name = f"extract_{_slug_title(title, 'params')}"
            note = "可與上游 agent／llm 合併"
        elif dtype == "document-extractor":
            lg_name = "extract_document"
        elif dtype == "iteration":
            lg_name = "iterate"
        elif dtype == "loop":
            lg_name = "loop_body"
        else:
            lg_name = dtype.replace("-", "_")
            note = "非標準 type：依語意命名"

        row: dict[str, Any] = {
            "dify_id": nid,
            "dify_type": dtype,
            "dify_title": title,
            "action": action,
            "langgraph_node": lg_name,
            "template": _dify_template_for(dtype, hints),
            "note": note,
        }
        rows.append(row)

    if inv.get("has_citation"):
        rows.append(
            {
                "dify_id": "",
                "dify_type": "(derived)",
                "dify_title": "citation chain",
                "action": "implement",
                "langgraph_node": "order_citations",
                "template": "order_citations.py.tmpl",
                "note": "DSL 含引用／來源工項時衍生",
            }
        )
        rows.append(
            {
                "dify_id": "",
                "dify_type": "(derived)",
                "dify_title": "citation chain",
                "action": "implement",
                "langgraph_node": "build_context",
                "template": "build_context.py.tmpl",
                "note": "DSL 含引用／來源工項時衍生",
            }
        )
    return rows


def _dify_template_for(dtype: str, hints: dict[str, Any]) -> str | None:
    table = {
        "start": "normalize_input.py.tmpl",
        "llm": "llm.py.tmpl",
        "answer": "answer_full.py.tmpl",
        "question-classifier": "classify.py.tmpl",
        "if-else": "route.py.tmpl",
        "knowledge-retrieval": "retrieve.py.tmpl",
        "http-request": "http_request.py.tmpl",
        "tool": "tool.py.tmpl",
        "code": "code_transform.py.tmpl",
        "agent": "agent.py.tmpl",
        "parameter-extractor": "parameter_extractor.py.tmpl",
        "document-extractor": "document_extractor.py.tmpl",
        "iteration": "iteration.py.tmpl",
        "loop": "iteration.py.tmpl",
    }
    if dtype == "code" and hints.get("code_looks_like_citation"):
        return None
    return table.get(dtype)


def _dify_branch_edges(inv: dict[str, Any]) -> list[dict[str, Any]]:
    """整理 classifier／if-else 分支邊，方便組 add_conditional_edges。"""
    nodes = {str(n.get("id")): n for n in (inv.get("nodes") or [])}
    out: list[dict[str, Any]] = []
    for edge in inv.get("edges") or []:
        src = str(edge.get("source") or "")
        node = nodes.get(src) or {}
        dtype = str(node.get("type") or "")
        if dtype not in {"if-else", "question-classifier"}:
            continue
        handle = edge.get("source_handle")
        out.append(
            {
                "source_id": src,
                "source_type": dtype,
                "source_title": node.get("title"),
                "source_handle": handle,
                "target_id": str(edge.get("target") or ""),
                "target_type": edge.get("target_type"),
            }
        )
    return out


def _has_citation_work(inv: dict[str, Any]) -> bool:
    """僅當 DSL 含引用／來源組裝工項時為 True（不是有 KB 就 True）。"""
    for node in inv.get("nodes") or []:
        hints = node.get("hints") or {}
        if any(
            hints.get(key)
            for key in (
                "code_looks_like_citation",
                "template_looks_like_citation",
                "answer_looks_like_citation",
                "prompt_looks_like_citation",
            )
        ):
            return True
        title = str(node.get("title") or "")
        if any(token in title for token in ("引用", "citation", "來源區塊", "order_citation")):
            return True
    return False


def _suggest_nodes(inv: dict[str, Any]) -> list[str]:
    """Suggest consolidated LangGraph node names from type counts."""
    counts: dict[str, int] = inv.get("type_counts") or {}
    nodes = inv.get("nodes") or []
    suggested: list[str] = ["normalize_input"]
    # Explicit None => merge into neighbors / ignore (glue or notes).
    mapping: dict[str, str | None] = {
        "question-classifier": "classify",
        "if-else": "route",
        "knowledge-retrieval": "retrieve",
        "llm": "llm_answer",
        "answer": "answer",
        "http-request": "http_call",
        "agent": "agent",
        "document-extractor": "extract",
        "loop": "loop_body",
        "iteration": "iterate",
        "template-transform": None,
        "variable-aggregator": None,
        "assigner": None,
        "custom-note": None,
        "start": None,
        "loop-start": None,
        "loop-end": None,
        # code handled separately
        "code": None,
    }
    seen: set[str] = set()

    def _add(name: str) -> None:
        if name not in seen:
            seen.add(name)
            suggested.append(name)

    for dtype, _count in counts.items():
        key = str(dtype)
        if key == "code":
            continue
        if key in mapping:
            name = mapping[key]
            if name is None:
                continue
        else:
            name = key.replace("-", "_").replace(" ", "_").lower()
            if name in {"unknown", ""}:
                continue
        _add(name)

    # Dify code: citation／來源類併入 citation 鏈；其餘才留 transform
    code_nodes = [n for n in nodes if str(n.get("type")) == "code"]
    if code_nodes and any(
        not (n.get("hints") or {}).get("code_looks_like_citation") for n in code_nodes
    ):
        _add("transform")

    # 有 KB → 只建議 retrieve（不要因 has_rag 強制 citation）
    if inv.get("has_rag"):
        _add("retrieve")

    # 偵測到引用／來源工項才加 citation 鏈
    if inv.get("has_citation") or _has_citation_work(inv):
        _add("order_citations")
        _add("build_context")

    if "answer" not in seen:
        _add("answer")
    return suggested


def _print_summary(inv: dict[str, Any]) -> None:
    print(f"source: {inv.get('source')}")
    print(f"name:   {inv.get('name')}")
    if inv.get("mode"):
        print(f"mode:   {inv.get('mode')}")
    print(f"nodes:  {len(inv.get('nodes') or [])}")
    print(f"edges:  {len(inv.get('edges') or [])}")
    print(f"has_rag:{inv.get('has_rag')}")
    print(f"has_citation:{inv.get('has_citation')}")
    print("type_counts:")
    for key, val in sorted((inv.get("type_counts") or {}).items(), key=lambda x: (-x[1], str(x[0]))):
        print(f"  {key}: {val}")
    if inv.get("external_hints"):
        print("external_hints:")
        for hint in inv["external_hints"]:
            print(f"  - {hint}")
    print("suggested_langgraph_nodes:")
    for name in inv.get("suggested_langgraph_nodes") or []:
        print(f"  - {name}")
    if inv.get("dify_node_mapping"):
        print("dify_node_mapping:")
        for row in inv["dify_node_mapping"]:
            lg = row.get("langgraph_node") or "-"
            print(
                f"  - [{row.get('action')}] {row.get('dify_type')} / {row.get('dify_title')} "
                f"({row.get('dify_id')}) → {lg}"
            )
    if inv.get("dify_branch_edges"):
        print(f"dify_branch_edges: {len(inv['dify_branch_edges'])}")
    if inv.get("error"):
        print(f"error:  {inv['error']}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse workflow DSL into inventory JSON")
    parser.add_argument("dsl_file", type=Path)
    parser.add_argument("-o", "--output", type=Path, help="Write full inventory JSON")
    parser.add_argument("--quiet", action="store_true", help="Only write JSON, no summary")
    args = parser.parse_args()
    if not args.dsl_file.exists():
        raise SystemExit(f"檔案不存在: {args.dsl_file}")
    inv = parse(args.dsl_file)
    if not args.quiet:
        _print_summary(inv)
    if args.output:
        args.output.write_text(
            json.dumps(inv, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if not args.quiet:
            print(f"wrote: {args.output}")
    elif args.quiet:
        json.dump(inv, sys.stdout, ensure_ascii=False, indent=2)
        print()


if __name__ == "__main__":
    main()
