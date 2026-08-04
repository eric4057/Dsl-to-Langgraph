# dsl-to-langgraph

跨平台 **Agent Skill**：把工作流 DSL 轉成獨立 LangGraph 專案（含 OpenAI-compatible API）。

同一套 skill 可用於：

| 環境 | 用法 |
|---|---|
| **Cursor** | `~/.cursor/skills/dsl-to-langgraph` 或開啟本 repo |
| **OpenClaw** | 放到 `workspace/skills/dsl-to-langgraph`，用 `exec` 跑腳本 |
| **ChatGPT Custom GPT** | 貼上 `gpt/CUSTOM_GPT_INSTRUCTIONS.md` + 上傳 Knowledge |
| **Codex / GPT Skills** | 上傳本 skill 資料夾（含 `agents/openai.yaml`） |
| **純 CLI** | 直接跑 `scripts/slim_dsl.py`、`scripts/parse_dsl.py`、`scripts/scaffold_project.py` |

支援 DSL：Dify、LangFlow、Flowise、n8n、generic nodes+edges。


## 結構（Agent Skills 標準）

```text
.
├── SKILL.md                 # 主指示（所有 agent 共用）
├── agents/openai.yaml       # GPT / Codex UI metadata
├── scripts/                 # 可攜腳本（相對 SKILL_DIR）
├── references/              # 按需載入文件
├── assets/templates/        # scaffold 模板
├── gpt/CUSTOM_GPT_INSTRUCTIONS.md
└── README.md
```

## 安裝

### Cursor

```bash
git clone https://github.com/eric4057/dsl-to-langgraph.git
mkdir -p ~/.cursor/skills
ln -sfn "$(pwd)/dsl-to-langgraph" ~/.cursor/skills/dsl-to-langgraph
```

或直接用 Cursor 打開本 repo（已含 `.cursor/skills/dsl-to-langgraph` 連結）。

### OpenClaw

```bash
git clone https://github.com/eric4057/dsl-to-langgraph.git
# 常見容器路徑：
ln -sfn /absolute/path/to/dsl-to-langgraph \
  /home/node/.openclaw/workspace/skills/dsl-to-langgraph
# 或本機 OpenClaw workspace：
# ln -sfn /absolute/path/to/dsl-to-langgraph \
#   ~/.openclaw/workspace/skills/dsl-to-langgraph
```

觸發後用 **`exec`** 執行腳本，不要呼叫名為 `dsl-to-langgraph` 的 tool。

### ChatGPT Custom GPT

1. 建立 Custom GPT  
2. Instructions：貼上 [`gpt/CUSTOM_GPT_INSTRUCTIONS.md`](gpt/CUSTOM_GPT_INSTRUCTIONS.md)  
3. Knowledge：上傳 `SKILL.md`、`references/`、`assets/templates/`（可打成 zip）

### Codex / OpenAI skill bundle

將整個 repo（或至少 `SKILL.md` + `agents/` + `scripts/` + `references/` + `assets/`）作為 skill 安裝／上傳。`agents/openai.yaml` 提供 UI 顯示名稱與預設提示。

## CLI

```bash
# 0) 大 DSL 先瘦身（建議；Discord／長 context 必做）
python3 scripts/slim_dsl.py your-flow.yml -o /tmp/your-flow.slim.yml

# 1) 解析（YAML 需 PyYAML）
python3 scripts/parse_dsl.py /tmp/your-flow.slim.yml -o inventory.json

# 2) 骨架：中文專案名請一定加 --model-name
python3 scripts/scaffold_project.py \
  --name "智慧客服" --out ./my-app --model-name nchc-qa-langgraph --port 8030
```

```bash
pip install pyyaml   # parse .yml 時
```

`parse_dsl.py` 對 RAG 會建議 `order_citations`／`build_context`；inventory 含 prompt／rerank／code 摘要。

## 授權

Private／內部使用。請勿提交 DSL 內密鑰。
