# dsl-to-langgraph

Cursor Agent Skill：把工作流 DSL 轉成獨立 **LangGraph** 專案（含 OpenAI-compatible API）。

支援：

- **Dify** YAML/JSON
- **LangFlow** / **Flowise** JSON
- **n8n** JSON
- **Generic** nodes + edges YAML/JSON

產出固定包含：`graph.py`、`state.py`、`nodes/`、`api.py`（`/v1/chat/completions`）。

風格基準：[`nchc_qa_langgraph`](https://github.com/eric4057/nchc_qa_langgraph)、[`gba_langgraph`](https://github.com/eric4057/gba_langgraph)、[`gba_dual_langgraph`](https://github.com/eric4057/gba_dual_langgraph)。

## 安裝到 Cursor

### 方式 A：當專案打開（推薦）

Clone 後用 Cursor 打開本 repo，skill 位於：

```text
.cursor/skills/dsl-to-langgraph/
```

### 方式 B：個人 skills

```bash
mkdir -p ~/.cursor/skills
ln -sfn /path/to/dsl-to-langgraph/.cursor/skills/dsl-to-langgraph \
  ~/.cursor/skills/dsl-to-langgraph
```

之後在對話中提到「DSL 轉 LangGraph」「把 Dify 工作流遷成 LangGraph」等，agent 應載入此 skill。

## Skill 內容

```text
.cursor/skills/dsl-to-langgraph/
├── SKILL.md           # 主流程
├── REFERENCE.md       # DSL 辨識與節點對映
├── EXAMPLES.md        # 既有專案範例
├── CHECKLIST.md       # 交付驗收
├── scripts/
│   ├── parse_dsl.py           # 解析 DSL → inventory
│   └── scaffold_project.py    # 產生專案骨架
└── templates/         # scaffold 用模板
```

## 快速使用

```bash
# 1) 解析 DSL
python3 .cursor/skills/dsl-to-langgraph/scripts/parse_dsl.py your-flow.yml -o inventory.json

# 2) 產生骨架
python3 .cursor/skills/dsl-to-langgraph/scripts/scaffold_project.py \
  --name my-app \
  --out ./my-app \
  --model-name my-app \
  --port 8030
```

然後依 `SKILL.md` 把 inventory 填進 `nodes/` 與 `graph.py`。

`parse_dsl.py` 需要 `PyYAML`（僅解析 `.yml` 時）：

```bash
pip install pyyaml
```

## 授權

Private skill／內部使用。請勿把 DSL 內的密鑰提交進 git。
