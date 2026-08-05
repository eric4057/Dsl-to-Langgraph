# dsl-to-langgraph

Agent Skill for converting workflow DSLs (Dify, LangFlow, Flowise, n8n, or generic nodes/edges) into a standalone LangGraph Python service with an OpenAI-compatible HTTP API.

Compatible with Cursor, OpenClaw, ChatGPT Custom GPT, Codex / GPT Skills, and plain CLI usage.

## Included programs

| Program | Path | Role |
|---|---|---|
| DSL slimmer | [`scripts/slim_dsl.py`](scripts/slim_dsl.py) | Strip UI/layout noise and redact obvious secrets from large exports before parsing or prompting an agent |
| DSL parser | [`scripts/parse_dsl.py`](scripts/parse_dsl.py) | Emit an inventory (source type, nodes/edges, external deps, suggested LangGraph nodes) |
| Project scaffolder | [`scripts/scaffold_project.py`](scripts/scaffold_project.py) | Generate a runnable LangGraph project skeleton (`api.py`, `graph.py`, `state.py`, `nodes/`, …) |

Supporting materials: [`SKILL.md`](SKILL.md) (agent procedure), [`references/`](references/) (mappings / examples / checklist), [`assets/templates/`](assets/templates/) (scaffold templates), [`agents/openai.yaml`](agents/openai.yaml), [`gpt/CUSTOM_GPT_INSTRUCTIONS.md`](gpt/CUSTOM_GPT_INSTRUCTIONS.md).

### `scripts/slim_dsl.py`

Preprocess oversized DSL exports (e.g. multi-thousand-line Dify YAML) so they fit agent / Discord context limits.

- **Removes:** canvas metadata (`position`, `selected`, `viewport`, …), icons, tool `paramSchemas`, and other non-semantic UI fields  
- **Keeps:** graph topology, node `type` / `title`, prompts, code, HTTP/KB config, branch conditions, model identifiers  
- **Redacts:** obvious secrets → `{{REDACTED}}`  
- **Output:** still valid for `parse_dsl.py`

```bash
python3 scripts/slim_dsl.py path/to/flow.yml -o /tmp/flow.slim.yml
python3 scripts/slim_dsl.py path/to/flow.yml -o /tmp/flow.slim.json --format json
```

Requires `pyyaml` for YAML input: `pip install pyyaml`.

### `scripts/parse_dsl.py`

Detect DSL dialect and summarize the graph for migration planning.

```bash
python3 scripts/parse_dsl.py /tmp/flow.slim.yml -o /tmp/inventory.json
```

Typical fields: `source`, `has_rag`, `type_counts`, `external_hints`, `suggested_langgraph_nodes`.

### `scripts/scaffold_project.py`

Create a minimal OpenAI-compatible LangGraph service. For non-ASCII project names, pass `--model-name` explicitly.

```bash
python3 scripts/scaffold_project.py \
  --name "my-app" \
  --out ./my-app \
  --model-name my-app \
  --port 8030
```

Scaffolded `nodes/answer.py` is a stub; replace it with DSL logic before treating the project as done.

## End-to-end CLI flow

```bash
cd /path/to/dsl-to-langgraph
python3 -m venv .venv && source .venv/bin/activate
pip install pyyaml

python3 scripts/slim_dsl.py your-flow.yml -o /tmp/your-flow.slim.yml
python3 scripts/parse_dsl.py /tmp/your-flow.slim.yml -o /tmp/inventory.json
python3 scripts/scaffold_project.py \
  --name "my-app" --out ./my-app --model-name my-app --port 8030
```

Then follow [`SKILL.md`](SKILL.md) to implement real nodes from the inventory (semantic migration, not a 1:1 dump of every glue node).

## Repository layout

```text
.
├── SKILL.md
├── agents/openai.yaml
├── gpt/CUSTOM_GPT_INSTRUCTIONS.md
├── references/
├── scripts/
│   ├── slim_dsl.py
│   ├── parse_dsl.py
│   └── scaffold_project.py
└── assets/templates/
```

## Install

### Cursor

```bash
git clone https://github.com/eric4057/dsl-to-langgraph.git
mkdir -p ~/.cursor/skills
ln -sfn "$(pwd)/dsl-to-langgraph" ~/.cursor/skills/dsl-to-langgraph
```

Or open this repository in Cursor (project skill link under `.cursor/skills/`).

### OpenClaw

Place or copy this directory under `workspace/skills/dsl-to-langgraph` (container path is often `/home/node/.openclaw/workspace/skills/dsl-to-langgraph`). Invoke scripts via **`exec`**; do not call a non-existent `dsl-to-langgraph` tool.

```bash
python3 /home/node/.openclaw/workspace/skills/dsl-to-langgraph/scripts/slim_dsl.py \
  /path/to/flow.yml -o /tmp/flow.slim.yml
```

### ChatGPT Custom GPT

1. Paste [`gpt/CUSTOM_GPT_INSTRUCTIONS.md`](gpt/CUSTOM_GPT_INSTRUCTIONS.md) into Instructions  
2. Upload `SKILL.md`, `references/`, and `assets/templates/` as Knowledge  

### Codex / OpenAI skill bundle

Install or upload the skill root (`SKILL.md` + `agents/` + `scripts/` + `references/` + `assets/`).

## Agent prompt (example)

```text
Use the dsl-to-langgraph skill.
1. slim_dsl.py → /tmp/flow.slim.yml
2. parse_dsl.py → inventory.json
3. scaffold_project.py → /tmp/my-langgraph (--model-name …)
4. Complete semantic migration per SKILL.md, including OpenAI-compatible api.py
```

## Further reading

- [`SKILL.md`](SKILL.md) — migration procedure  
- [`references/REFERENCE.md`](references/REFERENCE.md) — node mapping & citation rules  
- [`references/EXAMPLES.md`](references/EXAMPLES.md)  
- [`references/CHECKLIST.md`](references/CHECKLIST.md)  

## License

Private / internal use. Do not commit secrets from DSL exports.
