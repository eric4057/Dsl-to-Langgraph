#!/usr/bin/env python3
"""Scaffold a standalone LangGraph + OpenAI-compatible API project."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = SKILL_ROOT / "templates"


def _slug(name: str) -> str:
    value = name.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "langgraph-app"


def _render(text: str, mapping: dict[str, str]) -> str:
    out = text
    for key, val in mapping.items():
        out = out.replace("{{" + key + "}}", val)
    return out


def scaffold(out: Path, name: str, model_name: str, port: int) -> None:
    slug = _slug(name)
    mapping = {
        "PROJECT_NAME": name,
        "PROJECT_SLUG": slug,
        "API_MODEL": model_name or slug,
        "API_PORT": str(port),
        "GRAPH_EXPORT": slug.replace("-", "_"),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "nodes").mkdir(exist_ok=True)
    (out / "tests").mkdir(exist_ok=True)

    files = {
        "api.py": TEMPLATES / "api.py.tmpl",
        "graph.py": TEMPLATES / "graph.py.tmpl",
        "state.py": TEMPLATES / "state.py.tmpl",
        "config.py": TEMPLATES / "config.py.tmpl",
        "langgraph.json": TEMPLATES / "langgraph.json.tmpl",
        "requirements.txt": TEMPLATES / "requirements.txt.tmpl",
        ".env.example": TEMPLATES / "env.example.tmpl",
        ".gitignore": TEMPLATES / "gitignore.tmpl",
        "README.md": TEMPLATES / "README.md.tmpl",
        "nodes/__init__.py": TEMPLATES / "nodes" / "__init__.py.tmpl",
        "nodes/start.py": TEMPLATES / "nodes" / "start.py.tmpl",
        "nodes/answer.py": TEMPLATES / "nodes" / "answer.py.tmpl",
        "tests/test_graph.py": TEMPLATES / "tests_test_graph.py.tmpl",
    }
    for rel, src in files.items():
        if not src.exists():
            raise SystemExit(f"缺少模板: {src}")
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_render(src.read_text(encoding="utf-8"), mapping), encoding="utf-8")
    print(f"scaffolded: {out}")
    print(f"  model={mapping['API_MODEL']} port={mapping['API_PORT']}")
    print("下一步：依 DSL inventory 實作 nodes/ 與 graph 邊，並填 .env")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="專案顯示名稱或 slug")
    parser.add_argument("--out", type=Path, required=True, help="輸出目錄")
    parser.add_argument("--model-name", default="", help="OpenAI-compatible 模型名")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise SystemExit(f"目標目錄非空: {args.out}")
    scaffold(args.out, args.name, args.model_name, args.port)


if __name__ == "__main__":
    main()
