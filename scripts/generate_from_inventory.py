#!/usr/bin/env python3
"""依 inventory.json（+ 可選原始 DSL）自動產生 nodes／graph／logic／prompts。

目標：把「逐列 mapping → 複製模板、填 META、接 has_rag／has_citation／merge」自動化到可編譯骨架。
Agent 仍需驗收 selector／環境／行為，但不再從零手填。

用法：
  # 先 scaffold，再 generate
  python3 scripts/scaffold_project.py --name demo --out ./demo --model-name demo
  python3 scripts/parse_dsl.py flow.yml -o ./demo/inventory.json
  python3 scripts/generate_from_inventory.py \\
    --inventory ./demo/inventory.json --dsl flow.yml --out ./demo

  # 或一次：空目錄時可 --scaffold
  python3 scripts/generate_from_inventory.py \\
    --inventory inv.json --dsl flow.yml --out ./demo \\
    --scaffold --name demo --model-name demo --port 8010
"""

from __future__ import annotations

import argparse
import json
import re
import textwrap
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = SKILL_ROOT / "assets" / "templates"
NODE_TEMPLATES = TEMPLATES / "nodes"


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("需要 PyYAML：pip install pyyaml") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"DSL 不是 mapping: {path}")
    return data


def _dify_nodes_by_id(dsl: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not dsl:
        return {}
    graph = (dsl.get("workflow") or {}).get("graph") or {}
    out: dict[str, dict[str, Any]] = {}
    for node in graph.get("nodes") or []:
        nid = str(node.get("id") or "")
        if nid:
            out[nid] = node
    return out


def _safe_ident(name: str, fallback: str = "node") -> str:
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", (name or "").strip())
    text = text.strip("_").lower() or fallback
    if text[0].isdigit():
        text = f"n_{text}"
    return text[:60]


def _render(tmpl: str, mapping: dict[str, str]) -> str:
    out = tmpl
    for key, val in mapping.items():
        out = out.replace("{{" + key + "}}", val)
    return out


def _read_tmpl(name: str) -> str:
    path = NODE_TEMPLATES / name
    if not path.is_file():
        # derived templates live under nodes/
        alt = TEMPLATES / name
        if alt.is_file():
            return alt.read_text(encoding="utf-8")
        raise SystemExit(f"缺少模板: {path}")
    return path.read_text(encoding="utf-8")


def _py_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _selector_to_state_key(
    selector: list[Any],
    id_to_lg: dict[str, str],
    http_body_fields: dict[str, str],
) -> str:
    if not selector:
        return "query"
    if selector[0] == "sys":
        field = str(selector[1]) if len(selector) > 1 else "query"
        return {
            "query": "query",
            "files": "video_path",
            "dialogue_count": "dialogue_count",
        }.get(field, field)
    if selector[0] == "env":
        return f"env_{selector[1]}" if len(selector) > 1 else "env"
    nid = str(selector[0])
    field = str(selector[1]) if len(selector) > 1 else ""
    lg = id_to_lg.get(nid, _safe_ident(nid))
    if field in {"body", "text", "result"}:
        if field == "body":
            return http_body_fields.get(nid, f"{lg}_body")
        if field == "text":
            return f"{lg}_text" if lg != "llm_answer" else "llm_text"
        return f"{lg}_{field}"
    if field in {"status_code", "status"}:
        return f"{lg}_http_status"
    # code outputs usually use the output variable name directly in state
    if field:
        return field
    return lg


def _topo_order(inv: dict[str, Any], id_to_lg: dict[str, str]) -> list[str]:
    """依 edges 排出 implement 節點順序（langgraph 名）；結尾接 citation／answer。"""
    nodes = {str(n.get("id")): n for n in (inv.get("nodes") or [])}
    edges = inv.get("edges") or []
    indeg: dict[str, int] = {nid: 0 for nid in nodes}
    adj: dict[str, list[str]] = {nid: [] for nid in nodes}
    for e in edges:
        s, t = str(e.get("source") or ""), str(e.get("target") or "")
        if s in nodes and t in nodes:
            adj[s].append(t)
            indeg[t] = indeg.get(t, 0) + 1
    # Kahn
    queue = [nid for nid, d in indeg.items() if d == 0]
    order_ids: list[str] = []
    while queue:
        nid = queue.pop(0)
        order_ids.append(nid)
        for t in adj.get(nid, []):
            indeg[t] -= 1
            if indeg[t] == 0:
                queue.append(t)

    mapping_by_id = {
        str(r.get("dify_id") or ""): r
        for r in (inv.get("dify_node_mapping") or [])
        if r.get("dify_id")
    }
    lg_order: list[str] = []
    seen: set[str] = set()
    for nid in order_ids:
        row = mapping_by_id.get(nid) or {}
        if row.get("action") != "implement":
            continue
        name = row.get("langgraph_node")
        if name and name not in seen:
            lg_order.append(str(name))
            seen.add(str(name))

    # derived citation：放在最後一個業務 LLM 之前（若有），否則 answer 前
    derived = [
        str(r.get("langgraph_node"))
        for r in (inv.get("dify_node_mapping") or [])
        if r.get("dify_type") == "(derived)" and r.get("action") == "implement"
    ]
    if derived:
        if "llm_answer" in lg_order:
            idx = lg_order.index("llm_answer")
            for d in derived:
                if d not in seen:
                    lg_order.insert(idx, d)
                    seen.add(d)
                    idx += 1
        else:
            # before answer if present
            insert_at = lg_order.index("answer") if "answer" in lg_order else len(lg_order)
            for d in derived:
                if d not in seen:
                    lg_order.insert(insert_at, d)
                    seen.add(d)
                    insert_at += 1
    return lg_order


def _find_merge_targets(inv: dict[str, Any]) -> dict[str, str]:
    """merge dify_id → 併入的 implement langgraph_node（優先前一個 http／code）。"""
    edges = inv.get("edges") or []
    preds: dict[str, list[str]] = {}
    succs: dict[str, list[str]] = {}
    for e in edges:
        s, t = str(e.get("source") or ""), str(e.get("target") or "")
        preds.setdefault(t, []).append(s)
        succs.setdefault(s, []).append(t)

    id_to_row = {
        str(r.get("dify_id") or ""): r for r in (inv.get("dify_node_mapping") or []) if r.get("dify_id")
    }
    out: dict[str, str] = {}
    for row in inv.get("dify_node_mapping") or []:
        if row.get("action") != "merge":
            continue
        mid = str(row.get("dify_id") or "")
        if not mid:
            continue
        candidates: list[str] = []
        for pid in preds.get(mid, []):
            prow = id_to_row.get(pid) or {}
            if prow.get("action") == "implement" and prow.get("langgraph_node"):
                candidates.append(str(prow["langgraph_node"]))
        if not candidates:
            for tid in succs.get(mid, []):
                trow = id_to_row.get(tid) or {}
                if trow.get("action") == "implement" and trow.get("langgraph_node"):
                    candidates.append(str(trow["langgraph_node"]))
        if candidates:
            out[mid] = candidates[0]
    return out


def _extract_env_defaults(dsl: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    """回傳 [(NAME, value, description)]."""
    if not dsl:
        return []
    rows = []
    for item in (dsl.get("workflow") or {}).get("environment_variables") or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        rows.append(
            (
                name,
                str(item.get("value") or ""),
                str(item.get("description") or ""),
            )
        )
    return rows


def generate(
    *,
    inventory: dict[str, Any],
    out: Path,
    dsl: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    out = out.resolve()
    if not out.is_dir():
        raise SystemExit(f"輸出目錄不存在（請先 scaffold）: {out}")

    mapping_rows = inventory.get("dify_node_mapping") or []
    if not mapping_rows:
        raise SystemExit("inventory 缺少 dify_node_mapping（請用 parse_dsl 對 Dify DSL 產出）")

    dsl_nodes = _dify_nodes_by_id(dsl)
    id_to_lg: dict[str, str] = {}
    http_body_fields: dict[str, str] = {}
    for row in mapping_rows:
        nid = str(row.get("dify_id") or "")
        lg = row.get("langgraph_node")
        if nid and lg:
            id_to_lg[nid] = str(lg)
            if row.get("dify_type") == "http-request":
                http_body_fields[nid] = f"{lg}_body"

    merge_into = _find_merge_targets(inventory)
    merges_by_target: dict[str, list[dict[str, Any]]] = {}
    for mid, target_lg in merge_into.items():
        row = next(
            (r for r in mapping_rows if str(r.get("dify_id") or "") == mid),
            {"dify_id": mid},
        )
        merges_by_target.setdefault(target_lg, []).append(row)

    nodes_dir = out / "nodes"
    nodes_dir.mkdir(exist_ok=True)

    # remove scaffold stubs that conflict
    for stub in ("start.py", "answer.py"):
        p = nodes_dir / stub
        # answer.py may be regenerated; delete stub first always when force or generating answer
        if p.exists() and (force or stub == "start.py"):
            # always replace generated set
            pass

    generated_files: list[str] = []
    logic_chunks: list[str] = [
        '"""Auto-generated from Dify code nodes. Review before production."""',
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
    ]
    prompt_chunks: list[str] = [
        '"""Auto-generated from Dify LLM prompt_template."""',
        "from __future__ import annotations",
        "",
    ]
    state_fields: set[str] = {
        "query",
        "history",
        "answer",
        "meta",
        "trace",
        "error",
        "documents",
        "context",
        "citation_map",
        "llm_text",
        "video_path",
        "video_url",
    }
    export_names: list[str] = []
    node_func_by_lg: dict[str, str] = {}

    implement_rows = [r for r in mapping_rows if r.get("action") == "implement"]

    for row in implement_rows:
        dtype = str(row.get("dify_type") or "")
        lg = str(row.get("langgraph_node") or "")
        tmpl_name = row.get("template")
        nid = str(row.get("dify_id") or "")
        title = str(row.get("dify_title") or "")
        if not lg or not tmpl_name:
            continue

        dsl_node = dsl_nodes.get(nid) or {}
        data = (dsl_node.get("data") or {}) if dsl_node else {}
        hints = {}
        inv_node = next(
            (n for n in (inventory.get("nodes") or []) if str(n.get("id")) == nid),
            {},
        )
        hints = inv_node.get("hints") or {}

        merge_notes = merges_by_target.get(lg) or []
        merge_doc = ""
        if merge_notes:
            parts = [
                f"merged from {m.get('dify_id')} ({m.get('dify_title')})"
                for m in merge_notes
            ]
            merge_doc = "；".join(parts)

        func_base = _safe_ident(lg)
        if dtype == "if-else":
            func_name = func_base if func_base.startswith("route_") else f"route_{func_base}"
        else:
            func_name = func_base

        # --- type-specific generation ---
        if dtype == "code":
            code_src = str(data.get("code") or "")
            if not code_src:
                code_src = str(hints.get("code_excerpt") or "")
                if code_src.endswith("…"):
                    code_src = (
                        "# WARNING: inventory 只有截斷 code_excerpt；請加 --dsl 以嵌入完整 code\n"
                        + code_src
                    )
            logic_fn = f"logic_{func_name}"
            # rename main -> logic_fn
            code_body = code_src
            if re.search(r"^def\s+main\s*\(", code_body, re.M):
                code_body = re.sub(r"^def\s+main\s*\(", f"def {logic_fn}(", code_body, count=1, flags=re.M)
            else:
                code_body = code_body + f"\n\ndef {logic_fn}(**kwargs):\n    raise NotImplementedError('DSL code 無 main()')\n"
            logic_chunks.append(f"# --- from DSL code / {title} ({nid}) ---")
            logic_chunks.append(code_body.rstrip() + "\n")

            outputs = list((hints.get("code_outputs") or data.get("outputs") or {}).keys())
            variables = hints.get("code_variables") or data.get("variables") or []
            read_keys: list[str] = []
            call_args: list[str] = []
            for var in variables:
                vname = str(var.get("variable") or "arg")
                sel = var.get("value_selector") or []
                sk = _selector_to_state_key(list(sel), id_to_lg, http_body_fields)
                read_keys.append(sk)
                call_args.append(f"{vname}=state.get({_py_str(sk)})")
                state_fields.add(sk)
            for o in outputs:
                state_fields.add(str(o))

            reads_tuple = ", ".join(_py_str(k) for k in (read_keys or ["query"]))
            if len(read_keys) == 1:
                reads_tuple += ","
            writes_tuple = ", ".join(_py_str(o) for o in (outputs or ["result"]))
            if len(outputs) == 1:
                writes_tuple += ","

            node_src = textwrap.dedent(
                f'''\
                """節點：{title}

                DSL: code / {title}
                DSL_ID: {nid}
                讀取: {", ".join(read_keys) or "query"}
                寫入: {", ".join(outputs) or "result"}
                {f"merge note: {merge_doc}" if merge_doc else ""}
                """

                from __future__ import annotations

                from logic import {logic_fn}
                from node_debug import NodeDebug
                from state import WorkflowState

                # --- META（DEBUG 定位；勿刪）---
                NODE_KEY = "{func_name}"
                DSL_TYPE = "code"
                DSL_TITLE = {_py_str(title)}
                DSL_ID = {_py_str(nid)}
                READS = ({reads_tuple})
                WRITES = ({writes_tuple})


                def {func_name}_node(state: WorkflowState) -> dict:
                    dbg = NodeDebug(NODE_KEY, DSL_TYPE, DSL_TITLE, DSL_ID, state, READS)
                    try:
                        # --- READ + CALL ---
                        result = {logic_fn}({", ".join(call_args)})
                        # --- WRITE ---
                        if isinstance(result, dict):
                            return dbg.ok(result)
                        return dbg.ok({{"{outputs[0] if outputs else "result"}": result}})
                    except Exception as exc:
                        return dbg.fail(
                            exc,
                            fallback={{{", ".join(f"{_py_str(o)}: None" for o in (outputs or ["result"]))}}},
                            error_field="{func_name}_error",
                        )
                '''
            )
            target = nodes_dir / f"{func_name}.py"
            target.write_text(node_src, encoding="utf-8")
            generated_files.append(str(target.relative_to(out)))
            export_names.append(f"{func_name}_node")
            node_func_by_lg[lg] = f"{func_name}_node"
            continue

        if dtype == "llm":
            prompts = data.get("prompt_template") or []
            system_text = ""
            user_text = ""
            if isinstance(prompts, list):
                for item in prompts:
                    if not isinstance(item, dict):
                        continue
                    role = item.get("role")
                    text = str(item.get("text") or "")
                    if role == "system" and not system_text:
                        system_text = text
                    elif role == "user" and not user_text:
                        user_text = text
            if not system_text:
                # fallback excerpt
                pe = hints.get("prompt_excerpt")
                if isinstance(pe, list) and pe:
                    system_text = str(pe[0].get("text") if isinstance(pe[0], dict) else pe[0])
                else:
                    system_text = "你是助理，請用繁體中文回答。"
            const_name = f"SYSTEM_{func_name.upper()}"
            prompt_chunks.append(f"{const_name} = {_py_str(system_text)}")
            prompt_chunks.append("")
            # user template kept as raw for agent to wire; also emit builder stub
            builder = f"build_user_prompt_{func_name}"
            prompt_chunks.append(f"USER_TEMPLATE_{func_name.upper()} = {_py_str(user_text)}")
            prompt_chunks.append("")
            builder_src = (
                f"def {builder}(state: dict) -> str:\n"
                f'    """Replace simple Dify selectors with state values; verify before prod."""\n'
                f"    import re\n"
                f"    text = USER_TEMPLATE_{func_name.upper()}\n"
                f'    text = text.replace("{{{{#sys.query#}}}}", str(state.get("query") or ""))\n'
                f"    for key, val in state.items():\n"
                f'        if key in ("trace", "history", "meta"):\n'
                f"            continue\n"
                f'        text = text.replace("{{{{#" + key + "#}}}}", str(val if val is not None else ""))\n'
                f"    def _id_sel(match: re.Match) -> str:\n"
                f"        field = match.group(1)\n"
                f"        if field in state and state.get(field) is not None:\n"
                f"            return str(state.get(field))\n"
                f"        return match.group(0)\n"
                f'    text = re.sub(r"{{{{#\\d+\\.(\\w+)#}}}}", _id_sel, text)\n'
                f"    return text\n"
            )
            prompt_chunks.append(builder_src)
            out_field = "llm_text" if func_name in {"llm_answer", "llm"} else f"{func_name}_text"
            state_fields.add(out_field)

            node_src = _render(
                _read_tmpl("llm.py.tmpl"),
                {
                    "NODE_PURPOSE": title or "LLM",
                    "DSL_TITLE": title,
                    "DSL_ID": nid,
                    "READ_FIELDS": "query, context, report, web_summary",
                    "WRITE_FIELDS": out_field,
                    "FUNC_NAME": func_name,
                    "PROMPT_CONSTANT": const_name,
                    "OUTPUT_FIELD": out_field,
                },
            )
            # patch messages to use builder
            node_src = node_src.replace(
                "from prompts import {{PROMPT_CONSTANT}}".replace("{{PROMPT_CONSTANT}}", const_name),
                f"from prompts import {const_name}, {builder}",
            )
            # if template already rendered without that line:
            if f"from prompts import {const_name}" in node_src and builder not in node_src:
                node_src = node_src.replace(
                    f"from prompts import {const_name}",
                    f"from prompts import {const_name}, {builder}",
                )
            node_src = node_src.replace(
                '{"role": "user", "content": query},',
                f'{{"role": "user", "content": {builder}(dict(state))}},',
            )
            if merge_doc:
                node_src = node_src.replace(
                    f'DSL_ID: {nid}',
                    f"DSL_ID: {nid}\n{merge_doc}",
                )
            target = nodes_dir / f"{func_name}.py"
            target.write_text(node_src, encoding="utf-8")
            generated_files.append(str(target.relative_to(out)))
            export_names.append(f"{func_name}_node")
            node_func_by_lg[lg] = f"{func_name}_node"
            continue

        if dtype == "http-request":
            method = str((hints.get("method") or data.get("method") or "get")).upper()
            url = str(hints.get("url") or data.get("url") or "https://example.com")
            body_field = f"{func_name}_body"
            status_field = f"{func_name}_http_status"
            err_field = f"{func_name}_error"
            http_body_fields[nid] = body_field
            state_fields.update({body_field, status_field, err_field, "video_path", "video_url", "search_query"})

            body = hints.get("body") or data.get("body") or {}
            is_file = False
            if isinstance(body, dict) and body.get("type") == "form-data":
                for item in body.get("data") or []:
                    if isinstance(item, dict) and item.get("type") == "file":
                        is_file = True
                        break
            params_hint = str(hints.get("params") or data.get("params") or "")

            env_m = re.search(r"\{\{#env\.([A-Za-z0-9_]+)#\}\}", url)
            if env_m:
                env_name = env_m.group(1).lower()
                suffix = url.split("#}}")[-1] if "#}}" in url else ""
                url_line = (
                    f'url = str(getattr(settings, "{env_name}", "") or "").rstrip("/") + {_py_str(suffix)}'
                )
            else:
                url_line = f"url = getattr(settings, 'searxng_url', None) or {_py_str(url)}"
                if "searx" not in url.lower():
                    url_line = f"url = {_py_str(url)}"

            merge_lines = ""
            if merge_notes:
                for m in merge_notes:
                    merge_lines += (
                        f"        # merged from {m.get('dify_id')} / {m.get('dify_title')}\n"
                        f"        # TODO: 將該 code 整理邏輯接到 HTTP 成功之後（見 logic.py）\n"
                    )

            if is_file:
                call_block = f"""        # --- READ ---
        filename, content, content_type = load_video_bytes(
            state.get("video_path") or "",
            state.get("video_url") or "",
        )
        {url_line}

        # --- CALL ---
        status, body = http_upload_file(
            url=url,
            field_name="file",
            filename=filename,
            content=content,
            content_type=content_type,
        )
"""
                imports = (
                    "from config import settings\n"
                    "from node_debug import NodeDebug\n"
                    "from services import http_upload_file, load_video_bytes\n"
                    "from state import WorkflowState\n"
                )
                reads = '("video_path", "video_url")'
            else:
                params_code = "None"
                headers_code = "None"
                if method == "GET" and "q:" in params_hint:
                    params_code = '{"q": state.get("search_query") or "", "format": "json"}'
                    headers_code = '{"Accept": "application/json"}'
                call_block = f"""        # --- READ ---
        {url_line}
        query = state.get("search_query") or state.get("query") or ""

        # --- CALL ---
        status, body = http_request(
            method={_py_str(method)},
            url=url,
            params={params_code},
            headers={headers_code},
        )
"""
                imports = (
                    "from config import settings\n"
                    "from node_debug import NodeDebug\n"
                    "from services import http_request\n"
                    "from state import WorkflowState\n"
                )
                reads = '("query", "search_query")'

            node_src = f'''"""節點：{title}

DSL: http-request / {title}
DSL_ID: {nid}
讀取: {reads}
寫入: {body_field}, {status_field}, {err_field}
{merge_doc}
"""

from __future__ import annotations

{imports}

# --- META（DEBUG 定位；勿刪）---
NODE_KEY = "{func_name}"
DSL_TYPE = "http-request"
DSL_TITLE = {_py_str(title)}
DSL_ID = {_py_str(nid)}
READS = {reads}
WRITES = ("{body_field}", "{status_field}", "{err_field}")


def {func_name}_node(state: WorkflowState) -> dict:
    dbg = NodeDebug(NODE_KEY, DSL_TYPE, DSL_TITLE, DSL_ID, state, READS)
    try:
{call_block}
{merge_lines}        # --- WRITE ---
        return dbg.ok(
            {{
                "{status_field}": status,
                "{body_field}": body,
                "{err_field}": None,
            }}
        )
    except Exception as exc:
        return dbg.fail(
            exc,
            fallback={{
                "{status_field}": 0,
                "{body_field}": None,
            }},
            error_field="{err_field}",
        )
'''
            target = nodes_dir / f"{func_name}.py"
            target.write_text(node_src, encoding="utf-8")
            generated_files.append(str(target.relative_to(out)))
            export_names.append(f"{func_name}_node")
            node_func_by_lg[lg] = f"{func_name}_node"
            continue

        # generic template fill
        mapping = {
            "DSL_TITLE": title,
            "DSL_ID": nid or "",
            "READ_FIELDS": "query",
            "WRITE_FIELDS": "answer" if dtype == "answer" else "result",
            "FUNC_NAME": func_name if dtype != "answer" else "answer",
            "NODE_PURPOSE": title or dtype,
            "PROMPT_CONSTANT": "SYSTEM_PROMPT",
            "OUTPUT_FIELD": "llm_text" if dtype == "llm" else "result",
            "BODY_FIELD": f"{func_name}_body",
            "ERROR_FIELD": f"{func_name}_error",
            "METHOD": "GET",
            "URL_OR_FROM_STATE": "https://example.com",
            "LOGIC_FUNC": f"logic_{func_name}",
            "OUTPUT_FIELD": "result",
        }
        if dtype == "answer":
            mapping["FUNC_NAME"] = "answer"
            mapping["WRITE_FIELDS"] = "answer"
            mapping["READ_FIELDS"] = "llm_text, final_answer, answer"
        if dtype == "start":
            mapping["FUNC_NAME"] = "normalize_input"
            func_name = "normalize_input"
            lg = "normalize_input"

        raw = _read_tmpl(str(tmpl_name))
        node_src = _render(raw, mapping)
        if merge_doc:
            node_src = node_src.replace(
                f"DSL_ID: {mapping['DSL_ID']}\n" if mapping["DSL_ID"] else "DSL_ID: \n",
                f"DSL_ID: {mapping['DSL_ID']}\n{merge_doc}\n",
            )

        # citation templates don't use FUNC_NAME file naming the same way
        file_stem = {
            "order_citations": "order_citations",
            "build_context": "build_context",
            "normalize_input": "normalize_input",
            "answer": "answer",
            "retrieve": "retrieve",
        }.get(lg, func_name)

        # ensure NodeDebug META on citation if missing — templates are fine
        if dtype == "answer":
            # prefer llm_text
            node_src = node_src.replace(
                "state.get(\"final_answer\")\n            or state.get(\"direct_answer\")\n            or state.get(\"answer\")",
                "state.get(\"llm_text\")\n            or state.get(\"final_answer\")\n            or state.get(\"direct_answer\")\n            or state.get(\"answer\")",
            )
            if inventory.get("has_citation"):
                if "link_citations" not in node_src:
                    node_src = node_src.replace(
                        "from node_debug import NodeDebug",
                        "from logic import link_citations\nfrom node_debug import NodeDebug",
                    )
                node_src = node_src.replace(
                    "# text = link_citations(text, state.get(\"citation_map\") or {})",
                    "text = link_citations(text, state.get(\"citation_map\") or {})",
                )

        if file_stem in {"order_citations", "build_context"}:
            # add stub helpers in logic if not present
            if "def order_documents_for_citations" not in "\n".join(logic_chunks):
                logic_chunks.append(
                    textwrap.dedent(
                        '''\
                        def order_documents_for_citations(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
                            ordered: list[dict[str, Any]] = []
                            seen: set[str] = set()
                            for doc in docs or []:
                                meta = dict((doc or {}).get("metadata") or {})
                                key = str(meta.get("url") or meta.get("source_key") or meta.get("path") or "").strip()
                                if not key:
                                    key = str((doc or {}).get("content") or "")[:80]
                                if key in seen:
                                    continue
                                seen.add(key)
                                ordered.append(doc)
                            return ordered


                        def build_citation_context(docs: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
                            citation_map: dict[str, Any] = {}
                            lines: list[str] = []
                            for i, doc in enumerate(docs or [], 1):
                                meta = dict((doc or {}).get("metadata") or {})
                                title = str(meta.get("title") or f"來源{i}")
                                url = str(meta.get("url") or meta.get("path") or "")
                                content = str((doc or {}).get("content") or "").strip()
                                citation_map[str(i)] = {"title": title, "url": url, "source_key": meta.get("source_key") or url or title}
                                lines.append(f"[{i}] {title}" + (f" ({url})" if url else ""))
                                if content:
                                    lines.append(content)
                                lines.append("")
                            return "\\n".join(lines).strip(), citation_map


                        def link_citations(text: str, citation_map: dict[str, Any] | None = None) -> str:
                            _ = citation_map
                            return str(text or "").strip()
                        '''
                    )
                )

        target = nodes_dir / f"{file_stem}.py"
        target.write_text(node_src, encoding="utf-8")
        generated_files.append(str(target.relative_to(out)))
        export_fn = {
            "normalize_input": "normalize_input_node",
            "answer": "answer_node",
            "order_citations": "order_citations_node",
            "build_context": "build_context_node",
            "retrieve": "retrieve_node",
        }.get(file_stem, f"{func_name}_node")
        export_names.append(export_fn)
        node_func_by_lg[lg] = export_fn

    # remove obsolete scaffold start.py if normalize_input exists
    start_stub = nodes_dir / "start.py"
    if (nodes_dir / "normalize_input.py").exists() and start_stub.exists():
        start_stub.unlink()

    # --- logic.py / prompts.py ---
    if "def link_citations" not in "\n".join(logic_chunks) and inventory.get("has_citation"):
        logic_chunks.append(
            "\ndef link_citations(text: str, citation_map: dict[str, Any] | None = None) -> str:\n"
            "    _ = citation_map\n"
            "    return str(text or '').strip()\n"
        )
    (out / "logic.py").write_text("\n".join(logic_chunks).rstrip() + "\n", encoding="utf-8")
    generated_files.append("logic.py")
    (out / "prompts.py").write_text("\n".join(prompt_chunks).rstrip() + "\n", encoding="utf-8")
    generated_files.append("prompts.py")

    # --- nodes/__init__.py ---
    # unique preserve order
    seen_exp: set[str] = set()
    uniq_exports: list[str] = []
    for name in export_names:
        if name not in seen_exp:
            uniq_exports.append(name)
            seen_exp.add(name)

    init_lines = ['"""Node exports (auto-generated)."""', ""]
    for name in uniq_exports:
        mod = name[: -len("_node")] if name.endswith("_node") else name
        # route_ special
        if name.startswith("route_"):
            mod = name  # function lives in route_*.py named route_x — file stem = name without worrying
            # our files for if-else are route_*.py with def route_* 
            file_mod = name  # actually file is route_foo.py with def route_foo — export route_foo not route_foo_node
        file_mod = {
            "normalize_input_node": "normalize_input",
            "answer_node": "answer",
            "order_citations_node": "order_citations",
            "build_context_node": "build_context",
            "retrieve_node": "retrieve",
        }.get(name, name[: -5] if name.endswith("_node") else name)
        init_lines.append(f"from nodes.{file_mod} import {name}")
    init_lines.append("")
    init_lines.append(f"__all__ = {uniq_exports!r}")
    init_lines.append("")
    (nodes_dir / "__init__.py").write_text("\n".join(init_lines), encoding="utf-8")
    generated_files.append("nodes/__init__.py")

    # --- graph.py ---
    order = _topo_order(inventory, id_to_lg)
    # ensure all implement lg present
    for row in implement_rows:
        lg = row.get("langgraph_node")
        if lg and lg not in order and row.get("action") == "implement":
            order.append(str(lg))

    import_names = []
    for lg in order:
        fn = node_func_by_lg.get(lg)
        if fn and fn not in import_names:
            import_names.append(fn)

    graph_lines = [
        '"""LangGraph workflow (auto-generated from dify_node_mapping / edges)."""',
        "",
        "from __future__ import annotations",
        "",
        "from langgraph.graph import END, START, StateGraph",
        "",
        "from nodes import (",
    ]
    for fn in import_names:
        graph_lines.append(f"    {fn},")
    graph_lines += [
        ")",
        "from state import WorkflowState",
        "",
        "",
        "def build_graph():",
        "    workflow = StateGraph(WorkflowState)",
    ]
    for lg in order:
        fn = node_func_by_lg.get(lg)
        if not fn:
            continue
        graph_lines.append(f'    workflow.add_node("{lg}", {fn})')
    if order:
        graph_lines.append(f'    workflow.add_edge(START, "{order[0]}")')
        for a, b in zip(order, order[1:]):
            graph_lines.append(f'    workflow.add_edge("{a}", "{b}")')
        graph_lines.append(f'    workflow.add_edge("{order[-1]}", END)')
    graph_lines += ["    return workflow.compile()", "", "", "graph = build_graph()", ""]
    # note branch edges
    if inventory.get("dify_branch_edges"):
        graph_lines.insert(
            2,
            f"# TODO: conditional edges from dify_branch_edges ({len(inventory['dify_branch_edges'])} rules)",
        )
    (out / "graph.py").write_text("\n".join(graph_lines), encoding="utf-8")
    generated_files.append("graph.py")

    # --- state.py patch: rewrite with collected fields ---
    state_lines = [
        '"""Shared workflow state (auto-extended from inventory)."""',
        "",
        "from __future__ import annotations",
        "",
        "import operator",
        "from typing import Annotated, Any, TypedDict",
        "",
        "",
        "class WorkflowState(TypedDict, total=False):",
    ]
    for field in sorted(state_fields):
        if field == "trace":
            state_lines.append("    trace: Annotated[list[dict[str, Any]], operator.add]")
        elif field == "history":
            state_lines.append("    history: list[dict[str, str]]")
        elif field == "documents":
            state_lines.append("    documents: list[dict[str, Any]]")
        elif field == "citation_map":
            state_lines.append("    citation_map: dict[str, Any]")
        elif field == "meta":
            state_lines.append("    meta: dict[str, Any]")
        else:
            state_lines.append(f"    {field}: Any")
    state_lines.append("")
    (out / "state.py").write_text("\n".join(state_lines), encoding="utf-8")
    generated_files.append("state.py")

    # --- config / env hints from DSL env vars ---
    env_rows = _extract_env_defaults(dsl)
    env_example = out / ".env.example"
    if env_example.exists() and env_rows:
        extra = ["", "# --- from Dify environment_variables ---"]
        for name, value, desc in env_rows:
            if desc:
                extra.append(f"# {desc}")
            extra.append(f"{name}={value}")
        text = env_example.read_text(encoding="utf-8")
        if "UAS_BASE_URL" not in text and any(n == "UAS_BASE_URL" for n, _, _ in env_rows):
            env_example.write_text(text.rstrip() + "\n" + "\n".join(extra) + "\n", encoding="utf-8")
            generated_files.append(".env.example")

    # append settings attrs for known env names
    config_path = out / "config.py"
    if config_path.exists() and env_rows:
        cfg = config_path.read_text(encoding="utf-8")
        additions = []
        for name, value, _desc in env_rows:
            attr = name.lower()
            if f"{attr}:" in cfg or f"{attr} =" in cfg:
                continue
            additions.append(f'    {attr}: str = "{value}"')
        # searxng common
        if "searxng_url" not in cfg:
            additions.append(
                '    searxng_url: str = "https://searxng.dev.td.nchc.org.tw/search"'
            )
        if additions and "class Settings" in cfg:
            cfg = cfg.replace(
                "\n\nsettings = Settings()",
                "\n" + "\n".join(additions) + "\n\n\nsettings = Settings()",
            )
            config_path.write_text(cfg, encoding="utf-8")
            generated_files.append("config.py")

    # ensure services has upload helpers (append if missing)
    services = out / "services.py"
    if services.exists():
        stext = services.read_text(encoding="utf-8")
        if "def http_upload_file" not in stext:
            stext = stext.rstrip() + "\n\n" + textwrap.dedent(
                '''\
                def http_upload_file(
                    *,
                    url: str,
                    field_name: str,
                    filename: str,
                    content: bytes,
                    content_type: str,
                    timeout: float = 60.0,
                ) -> tuple[int, Any]:
                    with httpx.Client(timeout=timeout) as client:
                        response = client.post(
                            url,
                            files={field_name: (filename, content, content_type)},
                        )
                        try:
                            body: Any = response.json()
                        except Exception:
                            body = response.text
                        return response.status_code, body


                def load_video_bytes(video_path: str = "", video_url: str = "") -> tuple[str, bytes, str]:
                    import mimetypes
                    from pathlib import Path
                    from urllib.parse import urlparse

                    if video_path:
                        path = Path(video_path)
                        return (
                            path.name,
                            path.read_bytes(),
                            mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                        )
                    if not video_url:
                        raise ValueError("缺少影片附件")
                    response = httpx.get(video_url, follow_redirects=True, timeout=60.0)
                    response.raise_for_status()
                    filename = Path(urlparse(video_url).path).name or "video.mp4"
                    content_type = response.headers.get("content-type", "application/octet-stream")
                    return filename, response.content, content_type
                '''
            )
            services.write_text(stext + "\n", encoding="utf-8")
            generated_files.append("services.py")

    report = {
        "out": str(out),
        "has_rag": inventory.get("has_rag"),
        "has_citation": inventory.get("has_citation"),
        "implement": len(implement_rows),
        "merge": sum(1 for r in mapping_rows if r.get("action") == "merge"),
        "ignore": sum(1 for r in mapping_rows if r.get("action") == "ignore"),
        "graph_order": order,
        "merge_into": merge_into,
        "files": generated_files,
        "warnings": [],
    }
    if inventory.get("has_rag"):
        report["warnings"].append("has_rag=true：確認 scaffold 有 --with-pgvector，並實作 retrieve")
    if inventory.get("dify_branch_edges"):
        report["warnings"].append("存在 dify_branch_edges：graph 僅線性接線，請補 conditional edges")
    if not dsl:
        report["warnings"].append("未提供 --dsl：code／prompt 可能只有截斷 excerpt")
    (out / "GENERATE_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate LangGraph nodes/graph/logic/prompts from inventory.json"
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="已 scaffold 的專案目錄")
    parser.add_argument("--dsl", type=Path, default=None, help="原始 Dify YAML（建議，可嵌入完整 code／prompt）")
    parser.add_argument("--force", action="store_true", help="覆寫已存在的 nodes")
    parser.add_argument("--scaffold", action="store_true", help="若 out 不存在或為空則先 scaffold")
    parser.add_argument("--name", default="", help="配合 --scaffold")
    parser.add_argument("--model-name", default="", help="配合 --scaffold")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--with-pgvector", action="store_true")
    args = parser.parse_args()

    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    out = args.out

    if args.scaffold:
        from scaffold_project import scaffold

        if out.exists() and any(out.iterdir()):
            raise SystemExit(f"--scaffold 要求空目錄: {out}")
        name = args.name or inventory.get("name") or "langgraph-app"
        with_pg = args.with_pgvector or bool(inventory.get("has_rag"))
        scaffold(
            out,
            name,
            args.model_name or "app",
            args.port,
            with_pgvector=with_pg,
        )

    dsl = _load_yaml(args.dsl) if args.dsl else None
    # copy inventory into project
    out.mkdir(parents=True, exist_ok=True)
    (out / "inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.dsl:
        target_dsl = out / "source.yml"
        target_dsl.write_bytes(args.dsl.read_bytes())

    report = generate(inventory=inventory, out=out, dsl=dsl, force=args.force)
    print("generated:", report["out"])
    print("  graph_order:", " → ".join(report["graph_order"]))
    print(f"  implement={report['implement']} merge={report['merge']} ignore={report['ignore']}")
    print(f"  has_rag={report['has_rag']} has_citation={report['has_citation']}")
    if report["merge_into"]:
        print("  merge_into:", report["merge_into"])
    for w in report["warnings"]:
        print("  warning:", w)
    print("  report:", out / "GENERATE_REPORT.json")
    print("下一步: 校對 selector／.env，跑 pytest／手動驗收；有分支則補 conditional edges")


if __name__ == "__main__":
    main()
