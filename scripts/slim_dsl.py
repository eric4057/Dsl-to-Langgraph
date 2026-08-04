#!/usr/bin/env python3
"""Slim workflow DSL：刪 UI／佈局／工具 schema 雜訊，只留轉換 LangGraph 必要欄位。

用途：大 DSL 貼進 agent／Discord 前先壓縮，避免 system+tools+附件逼近 context 上限。

Usage:
  python3 slim_dsl.py path/to/dsl.yml [-o path/to/dsl.slim.yml]
  python3 slim_dsl.py path/to/dsl.json --format json

Supports: Dify / n8n / LangFlow / Flowise / generic nodes+edges
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

NODE_DROP = {
    "position",
    "positionAbsolute",
    "selected",
    "width",
    "height",
    "sourcePosition",
    "targetPosition",
    "zIndex",
    "draggable",
    "selectable",
    "style",
    "className",
    "dragging",
    "resizing",
    "extent",
    "expandParent",
}

EDGE_DROP = {
    "selected",
    "zIndex",
    "style",
    "animated",
    "markerEnd",
    "markerStart",
    "labelStyle",
    "labelBgStyle",
    "interactionWidth",
}

DATA_DROP_ALWAYS = {
    "selected",
    "provider_icon",
    "paramSchemas",
    "tool_description",
    "is_team_authorization",
    "tool_node_version",
    "plugin_unique_identifier",
    "meta",
    "output_schema",
}

DATA_DROP_IF_ITERATION_UI = {"height", "width"}

APP_KEEP = {"name", "mode", "description"}

MODEL_KEEP = {
    "provider",
    "name",
    "mode",
    "completion_params",
    "model",
    "model_id",
}


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
    if isinstance(data.get("data"), dict) and "nodes" in data["data"]:
        return "langflow"
    if "nodes" in data and ("edges" in data or "links" in data):
        blob = json.dumps(data).lower()
        sample = data["nodes"][0] if data["nodes"] else {}
        node_data = sample.get("data") if isinstance(sample, dict) else {}
        ntype = ""
        if isinstance(node_data, dict):
            ntype = str(node_data.get("type") or node_data.get("name") or "")
        if "langflow" in blob:
            return "langflow"
        if "flowise" in blob or "chatprompt" in ntype.lower():
            return "flowise"
        return "generic"
    return "unknown"


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if value == "" or value == [] or value == {}:
        return True
    return False


def _prune_empty(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            pruned = _prune_empty(item)
            if _is_empty(pruned):
                continue
            out[key] = pruned
        return out
    if isinstance(value, list):
        return [p for p in (_prune_empty(item) for item in value) if not _is_empty(p)]
    return value


def _redact_secrets(value: Any, key: str = "") -> Any:
    secret_key = bool(
        re.search(r"(api[_-]?key|token|password|secret|authorization|bearer)", key, re.I)
    )
    if isinstance(value, dict):
        return {k: _redact_secrets(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_secrets(v, key) for v in value]
    if secret_key and isinstance(value, str) and value and not value.startswith("{{"):
        if value.lower() in {"bearer", "no-auth", "none", "null"}:
            return value
        return "{{REDACTED}}"
    return value


def _slim_i18n(value: Any) -> Any:
    if isinstance(value, dict) and any(k in value for k in ("zh_Hans", "en_US", "ja_JP", "pt_BR")):
        return value.get("zh_Hans") or value.get("en_US") or next(iter(value.values()), "")
    return value


def _slim_model(model: Any) -> Any:
    if not isinstance(model, dict):
        return model
    # nested {type,value:{...}}
    if "value" in model and isinstance(model.get("value"), dict) and "provider" in model["value"]:
        return {
            "type": model.get("type"),
            "value": _slim_model(model["value"]),
        }
    out = {k: v for k, v in model.items() if k in MODEL_KEEP}
    if not out and model:
        for k in ("name", "provider", "model"):
            if k in model:
                out[k] = model[k]
    return out


def _slim_agent_tools(tools_value: Any) -> Any:
    if not isinstance(tools_value, list):
        return tools_value
    out = []
    for tool in tools_value:
        if not isinstance(tool, dict):
            out.append(tool)
            continue
        slim = {
            k: tool[k]
            for k in (
                "enabled",
                "tool_name",
                "tool_label",
                "provider_name",
                "type",
                "parameters",
                "settings",
            )
            if k in tool
        }
        desc = None
        if isinstance(tool.get("extra"), dict):
            desc = tool["extra"].get("description")
        if not desc:
            desc = tool.get("tool_description")
        if isinstance(desc, str) and desc:
            slim["description"] = desc[:240]
        out.append(slim)
    return out


def _slim_agent_parameters(params: Any) -> Any:
    if not isinstance(params, dict):
        return params
    out: dict[str, Any] = {}
    for key, value in params.items():
        if not isinstance(value, dict):
            out[key] = value
            continue
        entry: dict[str, Any] = {}
        if "type" in value:
            entry["type"] = value["type"]
        raw_val = value.get("value")
        if key == "tools":
            entry["value"] = _slim_agent_tools(raw_val)
        elif key == "model":
            entry["value"] = _slim_model(raw_val)
        else:
            entry["value"] = raw_val
        out[key] = {k: v for k, v in entry.items() if v is not None}
    return out


def _slim_structured_output(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k in {"icon", "ui:widget"}:
                    continue
                if k in {"title", "description", "label"}:
                    out[k] = _slim_i18n(v)
                else:
                    out[k] = walk(v)
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)


def _slim_node_data(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    ntype = str(data.get("type") or "")
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key in DATA_DROP_ALWAYS:
            continue
        if ntype == "iteration" and key in DATA_DROP_IF_ITERATION_UI:
            continue
        if key == "model":
            out[key] = _slim_model(value)
            continue
        if key == "agent_parameters":
            out[key] = _slim_agent_parameters(value)
            continue
        if key == "structured_output":
            out[key] = _slim_structured_output(value)
            continue
        if key == "vision" and isinstance(value, dict) and not value.get("enabled"):
            continue
        if key == "memory" and isinstance(value, dict):
            out[key] = {
                k: value[k] for k in ("enabled", "window", "query_prompt_template") if k in value
            }
            continue
        if key in {"retry_config", "ssl_verify"} and ntype == "http-request":
            continue
        if key == "timeout" and ntype == "http-request" and isinstance(value, dict):
            nums = [v for v in value.values() if isinstance(v, (int, float))]
            if nums:
                out[key] = max(nums)
            continue
        out[key] = value
    return out


def _slim_dify_node(node: dict[str, Any]) -> dict[str, Any]:
    slim: dict[str, Any] = {"id": str(node.get("id", ""))}
    if node.get("type"):
        slim["type"] = node["type"]
    if node.get("parentId"):
        slim["parentId"] = node["parentId"]
    data = _slim_node_data(node.get("data") or {})
    if data:
        slim["data"] = data
    return slim


def _slim_dify_edge(edge: dict[str, Any]) -> dict[str, Any]:
    slim: dict[str, Any] = {
        "id": edge.get("id"),
        "source": str(edge.get("source", "")),
        "target": str(edge.get("target", "")),
    }
    if edge.get("sourceHandle") is not None:
        slim["sourceHandle"] = edge.get("sourceHandle")
    if edge.get("targetHandle") is not None:
        slim["targetHandle"] = edge.get("targetHandle")
    edata = edge.get("data")
    if isinstance(edata, dict):
        keep = {
            k: edata[k]
            for k in ("sourceType", "targetType", "isInIteration", "isInLoop", "iteration_id")
            if k in edata
        }
        if keep:
            slim["data"] = keep
    return {k: v for k, v in slim.items() if v is not None and v != ""}


def _slim_variables(items: Any) -> Any:
    if not isinstance(items, list):
        return items
    out = []
    for item in items:
        if not isinstance(item, dict):
            out.append(item)
            continue
        keep_keys = (
            "id",
            "name",
            "value_type",
            "value",
            "description",
            "selector",
            "variable",
            "label",
            "type",
            "required",
            "max_length",
            "options",
        )
        slim = {k: item[k] for k in keep_keys if k in item}
        out.append(_redact_secrets(slim))
    return out


def slim_dify(data: dict[str, Any]) -> dict[str, Any]:
    app_in = data.get("app") or {}
    app = {k: app_in[k] for k in APP_KEEP if k in app_in and not _is_empty(app_in[k])}

    wf_in = data.get("workflow") or {}
    graph_in = wf_in.get("graph") or {}
    nodes = [_slim_dify_node(n) for n in (graph_in.get("nodes") or []) if isinstance(n, dict)]
    edges = [_slim_dify_edge(e) for e in (graph_in.get("edges") or []) if isinstance(e, dict)]

    workflow: dict[str, Any] = {"graph": {"nodes": nodes, "edges": edges}}
    for key in ("conversation_variables", "environment_variables", "rag_pipeline_variables"):
        if key in wf_in and not _is_empty(wf_in[key]):
            workflow[key] = _slim_variables(wf_in[key])

    out: dict[str, Any] = {
        "kind": data.get("kind") or "app",
        "version": data.get("version"),
        "app": app,
        "workflow": workflow,
        "_slim_meta": {
            "source": "dify",
            "note": "UI/layout/tool-schema/secrets-stripped for LangGraph migration",
        },
    }
    deps = data.get("dependencies")
    if isinstance(deps, list) and deps:
        names = []
        for dep in deps:
            if isinstance(dep, dict):
                names.append(dep.get("name") or dep.get("package") or dep.get("type") or str(dep))
            else:
                names.append(str(dep))
        out["dependencies"] = names
    return _prune_empty(_redact_secrets(out))


def _slim_generic_node(node: dict[str, Any]) -> dict[str, Any]:
    slim = {k: v for k, v in node.items() if k not in NODE_DROP}
    if isinstance(slim.get("data"), dict):
        data = dict(slim["data"])
        for key in list(data.keys()):
            if key in DATA_DROP_ALWAYS or key in {"position", "positionAbsolute"}:
                data.pop(key, None)
        node_obj = data.get("node")
        if isinstance(node_obj, dict) and isinstance(node_obj.get("template"), dict):
            tmpl = {}
            for tkey, tval in node_obj["template"].items():
                if isinstance(tval, dict):
                    keep = {
                        sk: tval[sk]
                        for sk in (
                            "value",
                            "type",
                            "required",
                            "placeholder",
                            "name",
                            "display_name",
                            "info",
                            "options",
                        )
                        if sk in tval
                    }
                    if keep:
                        tmpl[tkey] = keep
                else:
                    tmpl[tkey] = tval
            node_obj = {**node_obj, "template": tmpl}
            for ui in ("icon", "documentation"):
                node_obj.pop(ui, None)
            data["node"] = node_obj
        slim["data"] = data
    return slim


def _slim_generic_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in edge.items() if k not in EDGE_DROP}


def slim_generic_graph(data: dict[str, Any], source: str) -> dict[str, Any]:
    root = data
    nested = False
    if source == "langflow" and isinstance(data.get("data"), dict) and "nodes" in data["data"]:
        root = data["data"]
        nested = True

    nodes_key = "nodes"
    edges_key = "edges" if "edges" in root else "links"
    nodes = [_slim_generic_node(n) for n in (root.get(nodes_key) or []) if isinstance(n, dict)]
    edges = [_slim_generic_edge(e) for e in (root.get(edges_key) or []) if isinstance(e, dict)]
    graph = {"nodes": nodes, edges_key: edges}

    if nested:
        out = {
            "name": data.get("name") or data.get("title") or "",
            "data": graph,
            "_slim_meta": {"source": source, "note": "UI/layout-stripped for LangGraph migration"},
        }
        if data.get("description"):
            out["description"] = data["description"]
        return _prune_empty(out)

    out = {
        **{k: v for k, v in data.items() if k not in {nodes_key, edges_key, "viewport"}},
        **graph,
    }
    out["_slim_meta"] = {"source": source, "note": "UI/layout-stripped for LangGraph migration"}
    return _prune_empty(out)


def slim_n8n(data: dict[str, Any]) -> dict[str, Any]:
    nodes = []
    for node in data.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        slim: dict[str, Any] = {
            "id": node.get("id"),
            "name": node.get("name"),
            "type": node.get("type"),
            "typeVersion": node.get("typeVersion"),
            "parameters": node.get("parameters") or {},
        }
        if node.get("credentials") and isinstance(node["credentials"], dict):
            slim["credentials"] = {
                k: {"name": (v or {}).get("name", k)}
                for k, v in node["credentials"].items()
                if isinstance(v, dict)
            }
        nodes.append(_prune_empty(slim))
    out = {
        "name": data.get("name") or "",
        "nodes": nodes,
        "connections": data.get("connections") or {},
        "_slim_meta": {"source": "n8n", "note": "UI/credentials-stripped for LangGraph migration"},
    }
    return _prune_empty(out)


def slim_dsl(data: Any) -> tuple[Any, str]:
    source = _detect(data)
    if source == "dify":
        return slim_dify(data), source
    if source == "n8n":
        return slim_n8n(data), source
    if source in {"langflow", "flowise", "generic"}:
        return slim_generic_graph(data, source), source
    if isinstance(data, dict):
        cleaned = _redact_secrets(_prune_empty(data))
        if isinstance(cleaned, dict):
            cleaned["_slim_meta"] = {
                "source": "unknown",
                "note": "best-effort prune only; structure unrecognized",
            }
        return cleaned, source
    return data, source


def _dump(path: Path, data: Any, fmt: str) -> None:
    if fmt == "json" or path.suffix.lower() == ".json":
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("需要 PyYAML：pip install pyyaml") from exc

    class _Dumper(yaml.SafeDumper):
        pass

    def _str_representer(dumper, value: str):  # type: ignore[no-untyped-def]
        style = "|" if ("\n" in value and len(value) > 80) else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)

    _Dumper.add_representer(str, _str_representer)
    path.write_text(
        yaml.dump(data, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )


def _default_out(src: Path, fmt: str) -> Path:
    suffix = ".slim.json" if fmt == "json" or src.suffix.lower() == ".json" else ".slim.yml"
    return src.with_name(src.stem + suffix)


def main() -> None:
    parser = argparse.ArgumentParser(description="Slim workflow DSL for LangGraph migration")
    parser.add_argument("dsl_file", type=Path, help="原始 DSL 檔（yml/json）")
    parser.add_argument("-o", "--out", type=Path, default=None, help="輸出路徑")
    parser.add_argument(
        "--format",
        choices=("auto", "yaml", "json"),
        default="auto",
        help="輸出格式（預設依副檔名）",
    )
    args = parser.parse_args()

    src: Path = args.dsl_file
    if not src.is_file():
        raise SystemExit(f"找不到檔案：{src}")

    raw = _load(src)
    before = len(json.dumps(raw, ensure_ascii=False))
    slimmed, source = slim_dsl(raw)

    fmt = args.format
    if fmt == "auto":
        fmt = "json" if src.suffix.lower() == ".json" else "yaml"
    out = args.out or _default_out(src, fmt)
    _dump(out, slimmed, fmt)

    after_chars = len(out.read_text(encoding="utf-8"))
    ratio = (1 - after_chars / max(before, 1)) * 100
    print(f"source: {source}")
    print(f"input:  {src} ({before:,} chars serialized)")
    print(f"output: {out} ({after_chars:,} chars)")
    print(f"saved:  {ratio:.1f}%")
    if isinstance(slimmed, dict):
        graph = (slimmed.get("workflow") or {}).get("graph") or slimmed
        if isinstance(graph, dict):
            nodes = graph.get("nodes")
            edges = graph.get("edges") or graph.get("links") or graph.get("connections")
            if isinstance(nodes, list):
                print(f"nodes:  {len(nodes)}")
            if isinstance(edges, (list, dict)):
                print(f"edges:  {len(edges)}")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
