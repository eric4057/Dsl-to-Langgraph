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
    hints: dict[str, Any] = {}
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
            hints["code_looks_like_citation"] = _code_looks_like_citation(code)
    if "classes" in d:
        hints["classes"] = [
            c.get("name") or c.get("id") for c in (d.get("classes") or []) if isinstance(c, dict)
        ]
    if "model" in d:
        model = d.get("model")
        if isinstance(model, dict):
            hints["model"] = model.get("name") or model.get("provider")
            if model.get("completion_params"):
                hints["completion_params"] = _truncate(model.get("completion_params"), 300)
    if d.get("type") == "answer" and d.get("answer"):
        hints["answer_template_excerpt"] = _truncate(str(d.get("answer")), 600)
    return hints


def _code_looks_like_citation(code: str) -> bool:
    lowered = code.lower()
    markers = (
        "citation",
        "source_url",
        "### 來源",
        "[[",
        "retriever_resource",
        "document id",
        "引用",
        "來源",
    )
    return any(marker.lower() in lowered if marker.isascii() else marker in code for marker in markers)


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
    inv["suggested_langgraph_nodes"] = _suggest_nodes(inv)
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

    # Dify code: citation/context glue → merge; other code → transform
    code_nodes = [n for n in nodes if str(n.get("type")) == "code"]
    if code_nodes:
        if any((n.get("hints") or {}).get("code_looks_like_citation") for n in code_nodes):
            if inv.get("has_rag"):
                _add("order_citations")
                _add("build_context")
            else:
                _add("build_context")
        if any(not (n.get("hints") or {}).get("code_looks_like_citation") for n in code_nodes):
            _add("transform")

    if inv.get("has_rag"):
        _add("retrieve")
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
