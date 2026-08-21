#!/usr/bin/env python3
"""Scaffold a standalone LangGraph + OpenAI-compatible API project."""

from __future__ import annotations

import argparse
import hashlib
import re
import unicodedata
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
# Prefer Agent Skills layout (assets/templates); keep legacy fallback.
TEMPLATES = SKILL_ROOT / "assets" / "templates"
if not TEMPLATES.is_dir():
    TEMPLATES = SKILL_ROOT / "templates"


def _slug(name: str) -> str:
    """Build a filesystem-/API-safe slug; keep CJK via unicode slug + short hash."""
    value = unicodedata.normalize("NFKC", name.strip())
    ascii_part = value.lower()
    ascii_part = re.sub(r"[^a-z0-9]+", "-", ascii_part).strip("-")
    if ascii_part and re.search(r"[a-z0-9]", ascii_part):
        return ascii_part[:48].strip("-") or "langgraph-app"

    # Non-ASCII names (e.g. 智慧客服): use stable hash suffix for GRAPH_EXPORT / defaults.
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"app-{digest}"


def _render(text: str, mapping: dict[str, str]) -> str:
    out = text
    for key, val in mapping.items():
        out = out.replace("{{" + key + "}}", val)
    return out


def _write(rel: str, src: Path, out: Path, mapping: dict[str, str]) -> None:
    if not src.exists():
        raise SystemExit(f"缺少模板: {src}")
    target = out / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_render(src.read_text(encoding="utf-8"), mapping), encoding="utf-8")


def scaffold(
    out: Path,
    name: str,
    model_name: str,
    port: int,
    *,
    with_pgvector: bool = False,
    pgvector_port: int = 5433,
    embedding_dim: int = 1024,
) -> None:
    slug = _slug(name)
    api_model = (model_name or "").strip() or slug
    mapping = {
        "PROJECT_NAME": name,
        "PROJECT_SLUG": slug,
        "API_MODEL": api_model,
        "API_PORT": str(port),
        "GRAPH_EXPORT": slug.replace("-", "_"),
        "PGVECTOR_PORT": str(pgvector_port),
        "EMBEDDING_DIM": str(embedding_dim),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "nodes").mkdir(exist_ok=True)
    (out / "tests").mkdir(exist_ok=True)

    files = {
        "api.py": TEMPLATES / "api.py.tmpl",
        "graph.py": TEMPLATES / "graph.py.tmpl",
        "state.py": TEMPLATES / "state.py.tmpl",
        "config.py": TEMPLATES / "config.py.tmpl",
        "services.py": TEMPLATES / "services.py.tmpl",
        "node_debug.py": TEMPLATES / "node_debug.py.tmpl",
        "run_node.py": TEMPLATES / "run_node.py.tmpl",
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
        _write(rel, src, out, mapping)

    if with_pgvector:
        rag_files = {
            "docker-compose.pgvector.yml": TEMPLATES / "rag" / "docker-compose.pgvector.yml.tmpl",
            "rag/schema.sql": TEMPLATES / "rag" / "schema.sql.tmpl",
            "rag/ingest_pgvector.py": TEMPLATES / "rag" / "ingest_pgvector.py.tmpl",
            "rag/README.md": TEMPLATES / "rag" / "README.md.tmpl",
        }
        for rel, src in rag_files.items():
            _write(rel, src, out, mapping)
        # 預設把 DATABASE_URL 寫進 .env.example 註解已存在；提示實際連線
        print("  pgvector: docker-compose.pgvector.yml + rag/ 已產出")
        print(
            f"  DATABASE_URL=postgresql://rag:ragpass@127.0.0.1:{pgvector_port}/rag "
            f"(EMBEDDING_DIM={embedding_dim})"
        )

    print(f"scaffolded: {out}")
    print(f"  project_name={name!r}")
    print(f"  slug={mapping['PROJECT_SLUG']} model={mapping['API_MODEL']} port={mapping['API_PORT']}")
    if not (model_name or "").strip() and mapping["PROJECT_SLUG"].startswith("app-"):
        print("提示: 專案名無 ASCII，已用 hash slug；建議加 --model-name 指定對外模型名")
    print("下一步: 依 DSL inventory 實作 nodes/ 與 graph 邊，並填 .env")
    print("注意: nodes/answer.py 為骨架佔位；交付前必須換成 DSL 真實邏輯（不可留 TODO）")
    if with_pgvector:
        print("RAG: docker compose -f docker-compose.pgvector.yml up -d")
        print("     再 python rag/ingest_pgvector.py --dir ./docs --collection default")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="專案顯示名稱或 slug")
    parser.add_argument("--out", type=Path, required=True, help="輸出目錄")
    parser.add_argument(
        "--model-name",
        default="",
        help="OpenAI-compatible 模型名（中文專案名強烈建議指定）",
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--with-pgvector",
        action="store_true",
        help="DSL has_rag 時加上：產出 pgvector docker／schema／ingest",
    )
    parser.add_argument("--pgvector-port", type=int, default=5433)
    parser.add_argument(
        "--embedding-dim",
        type=int,
        default=1024,
        help="向量維度（須與 embedding 模型一致）",
    )
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise SystemExit(f"目標目錄非空: {args.out}")
    scaffold(
        args.out,
        args.name,
        args.model_name,
        args.port,
        with_pgvector=args.with_pgvector,
        pgvector_port=args.pgvector_port,
        embedding_dim=args.embedding_dim,
    )


if __name__ == "__main__":
    main()
