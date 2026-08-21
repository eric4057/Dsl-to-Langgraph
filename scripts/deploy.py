#!/usr/bin/env python3
"""One-click deploy: DSL → parse → generate → install → start → health check.

Usage:
  python3 scripts/deploy.py flow.yml --name my-bot --model-name my-bot --port 8030 --out ./my-bot

After deploy, fill .env with real LLM credentials then restart:
  cd ./my-bot && source .venv/bin/activate && python api.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_DIR / "scripts"


def _run(cmd: list[str], *, cwd: str | Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def _line_count(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
    except Exception:
        return 0


def deploy(
    dsl_path: Path,
    *,
    out: Path,
    name: str,
    model_name: str,
    port: int,
    slim: bool | None = None,
    no_start: bool = False,
    with_pgvector: bool = False,
) -> dict:
    dsl_path = dsl_path.resolve()
    out = out.resolve()
    if not dsl_path.is_file():
        raise SystemExit(f"DSL 檔案不存在: {dsl_path}")

    python = sys.executable

    # ── Step 0: slim (auto if >500 lines) ──
    work_dsl = dsl_path
    if slim is None:
        slim = _line_count(dsl_path) > 500
    if slim:
        print("[0/6] Slim DSL ...")
        slim_out = out.parent / f"{out.name}_slim.yml"
        r = _run([python, str(SCRIPTS / "slim_dsl.py"), str(dsl_path), "-o", str(slim_out)], check=False)
        if r.returncode == 0 and slim_out.is_file():
            work_dsl = slim_out
            print(f"  slimmed → {slim_out}")
        else:
            print(f"  slim skipped (exit={r.returncode})")

    # ── Step 1: parse ──
    print("[1/6] Parse DSL → inventory.json ...")
    inv_path = out.parent / f"{out.name}_inventory.json"
    r = _run([python, str(SCRIPTS / "parse_dsl.py"), str(work_dsl), "-o", str(inv_path)])
    if r.stdout:
        for line in r.stdout.strip().splitlines():
            print(f"  {line}")

    # ── Step 2: generate + scaffold ──
    print("[2/6] Generate LangGraph project ...")
    if out.exists():
        shutil.rmtree(out)
    gen_cmd = [
        python, str(SCRIPTS / "generate_from_inventory.py"),
        "--inventory", str(inv_path),
        "--dsl", str(dsl_path),
        "--out", str(out),
        "--scaffold",
        "--name", name,
        "--model-name", model_name or name,
        "--port", str(port),
        "--force",
    ]
    if with_pgvector:
        gen_cmd.append("--with-pgvector")
    r = _run(gen_cmd)
    if r.stdout:
        for line in r.stdout.strip().splitlines():
            print(f"  {line}")

    # ── Step 3: venv + pip install ──
    print("[3/6] Install dependencies ...")
    venv_dir = out / ".venv"
    _run([python, "-m", "venv", str(venv_dir)])
    pip = str(venv_dir / "bin" / "pip")
    req = out / "requirements.txt"
    r = _run([pip, "install", "-q", "-r", str(req)], check=False)
    if r.returncode != 0:
        # retry without pgvector deps
        lines = req.read_text().splitlines()
        lines = [l for l in lines if "psycopg" not in l]
        req.write_text("\n".join(lines) + "\n")
        _run([pip, "install", "-q", "-r", str(req)])

    # ── Step 4: .env ──
    print("[4/6] Prepare .env ...")
    env_example = out / ".env.example"
    env_file = out / ".env"
    if env_example.is_file() and not env_file.is_file():
        shutil.copy2(env_example, env_file)
    print(f"  .env created at {env_file}")
    print("  ⚠ 請填入真實 LLM 連線資訊 (OPENAI_BASE_URL, OPENAI_API_KEY, CHAT_MODEL)")

    # ── Step 5: compile check ──
    print("[5/6] Compile check ...")
    venv_python = str(venv_dir / "bin" / "python")
    py_files = list(out.glob("*.py")) + list((out / "nodes").glob("*.py"))
    fail_count = 0
    for f in py_files:
        r = _run([venv_python, "-m", "py_compile", str(f)], check=False)
        if r.returncode != 0:
            print(f"  FAIL: {f.name}: {r.stderr.strip()}")
            fail_count += 1
    if fail_count:
        print(f"  {fail_count} file(s) failed compile")
    else:
        print(f"  {len(py_files)} files OK")

    result = {
        "project": str(out),
        "port": port,
        "model": model_name or name,
        "compile_ok": fail_count == 0,
    }

    if no_start:
        print("\n--no-start: 跳過啟動")
        _print_summary(result)
        return result

    # ── Step 6: start + health check ──
    print(f"[6/6] Start server on port {port} ...")
    proc = subprocess.Popen(
        [venv_python, "api.py"],
        cwd=str(out),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    result["pid"] = proc.pid

    healthy = False
    import urllib.request
    import urllib.error

    for i in range(30):
        time.sleep(1)
        if proc.poll() is not None:
            out_text = proc.stdout.read() if proc.stdout else ""
            print(f"  Server exited (code={proc.returncode})")
            if out_text:
                for line in out_text.strip().splitlines()[-10:]:
                    print(f"    {line}")
            break
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2)
            if resp.status == 200:
                healthy = True
                break
        except (urllib.error.URLError, OSError):
            pass

    result["healthy"] = healthy
    if healthy:
        print(f"  /health → OK (pid={proc.pid})")
    else:
        print("  /health → FAILED")
        if proc.poll() is None:
            proc.terminate()

    _print_summary(result)
    return result


def _print_summary(result: dict) -> None:
    port = result["port"]
    model = result["model"]
    proj = result["project"]
    print(textwrap.dedent(f"""
    ════════════════════════════════════════
    Deploy {'OK' if result.get('healthy') else 'DONE (no-start)' if 'healthy' not in result else 'FAILED'}
    Project : {proj}
    Model   : {model}
    Port    : {port}
    {'PID     : ' + str(result['pid']) if result.get('pid') else ''}
    ════════════════════════════════════════

    Test:
      curl http://localhost:{port}/health
      curl http://localhost:{port}/v1/chat/completions \\
        -H "Content-Type: application/json" \\
        -d '{{"model":"{model}","messages":[{{"role":"user","content":"你好"}}]}}'

    Stop:
      kill {result.get('pid', '<PID>')}

    .env (fill LLM credentials):
      {proj}/.env
    """))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-click deploy: DSL → LangGraph service"
    )
    parser.add_argument("dsl", type=Path, help="Dify DSL YAML file")
    parser.add_argument("--name", default="", help="Project name")
    parser.add_argument("--model-name", default="", help="API model name")
    parser.add_argument("--port", type=int, default=8000, help="API port (default: 8000)")
    parser.add_argument("--out", type=Path, default=None, help="Output directory (default: ./<name>)")
    parser.add_argument("--no-start", action="store_true", help="Only codegen, skip server start")
    parser.add_argument("--slim", action="store_true", default=None, help="Force slim DSL (auto if >500 lines)")
    parser.add_argument("--with-pgvector", action="store_true")
    args = parser.parse_args()

    name = args.name
    if not name:
        name = args.dsl.stem
        if len(name) > 40:
            name = name[:40]

    out = args.out or Path(f"./{name}")

    deploy(
        args.dsl,
        out=out,
        name=name,
        model_name=args.model_name or name,
        port=args.port,
        slim=args.slim,
        no_start=args.no_start,
        with_pgvector=args.with_pgvector,
    )


if __name__ == "__main__":
    main()
