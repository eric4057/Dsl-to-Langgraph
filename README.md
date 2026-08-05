# dsl-to-langgraph

跨平台 **Agent Skill**：把工作流 DSL（Dify／LangFlow／Flowise／n8n／generic）轉成獨立 **LangGraph** 專案，並附 **OpenAI-compatible API**（`api.py`）。

同一套 skill 可用於 Cursor、OpenClaw、ChatGPT Custom GPT、Codex／GPT Skills，或純 CLI。

---

## 瘦身程式在哪？

**路徑：** [`scripts/slim_dsl.py`](scripts/slim_dsl.py)

大 DSL（例如幾千行的 Dify 匯出）貼進 agent／Discord 前，先用它刪掉 UI／佈局／工具 schema 雜訊，只留轉換必要欄位，避免塞爆 context。

```bash
cd /home/ubuntu/dsl-to-langgraph   # 或你 clone 後的目錄

# 基本用法
python3 scripts/slim_dsl.py "/path/to/Grounding Workflow.yml" \
  -o /tmp/flow.slim.yml

# 輸出 JSON
python3 scripts/slim_dsl.py your-flow.yml -o /tmp/flow.slim.json --format json
```

| 項目 | 說明 |
|---|---|
| **會刪** | `position`、`selected`、`viewport`、icon、`paramSchemas`、多餘 UI 欄位等 |
| **會留** | nodes／edges、`type`／`title`、prompt、code、HTTP、KB、分支條件、模型名 |
| **密鑰** | 明顯 secret 改成 `{{REDACTED}}` |
| **下一步** | 把 `.slim.yml` 交給 `parse_dsl.py` 或貼給 agent |

依賴：解析 YAML 需 `pip install pyyaml`。

---

## 這套 skill 做什麼？

不是一鍵編譯器，而是：

1. **腳本**：瘦身 → 解析 inventory → scaffold 專案骨架  
2. **SKILL.md**：指導 agent 做語意等價遷移（填真實 `nodes/`、路由、API）

產出固定包含：`graph.py`、`state.py`、`nodes/`、`api.py`（`/v1/chat/completions`）、`.env.example`、測試等。

---

## 目錄結構

```text
dsl-to-langgraph/
├── SKILL.md                      # Agent 主指示
├── README.md                     # 本文件
├── agents/openai.yaml            # GPT / Codex UI metadata
├── gpt/CUSTOM_GPT_INSTRUCTIONS.md
├── references/
│   ├── REFERENCE.md              # DSL 節點對映、引用規則
│   ├── EXAMPLES.md               # 轉換範例
│   └── CHECKLIST.md              # 交付驗收
├── scripts/
│   ├── slim_dsl.py               # ★ DSL 瘦身（大檔必用）
│   ├── parse_dsl.py              # 解析 → inventory.json
│   └── scaffold_project.py       # 產生 LangGraph 專案骨架
└── assets/templates/             # scaffold 用的 api/graph/nodes 模板
```

---

## 推薦流程（CLI）

```bash
cd /path/to/dsl-to-langgraph
python3 -m venv .venv && source .venv/bin/activate
pip install pyyaml

# 0) 瘦身（大檔／貼進 Discord／長 context 強烈建議）
python3 scripts/slim_dsl.py your-flow.yml -o /tmp/your-flow.slim.yml

# 1) 解析 inventory
python3 scripts/parse_dsl.py /tmp/your-flow.slim.yml -o /tmp/inventory.json
# 看摘要：source、has_rag、suggested_langgraph_nodes

# 2) 產生骨架（中文專案名一定要加 --model-name）
python3 scripts/scaffold_project.py \
  --name "智慧客服" \
  --out ./my-app \
  --model-name my-qa-langgraph \
  --port 8030
```

接著依 `SKILL.md` + `inventory.json` 把真實業務邏輯填進 `my-app/nodes/`（不要只留骨架「已收到：…」）。

| 腳本 | 路徑 | 用途 |
|---|---|---|
| 瘦身 | `scripts/slim_dsl.py` | 壓縮 DSL、去 UI／密鑰雜訊 |
| 解析 | `scripts/parse_dsl.py` | 產出節點／邊／建議 LangGraph 節點 |
| 骨架 | `scripts/scaffold_project.py` | 產出可跑的空殼專案 |

---

## 安裝到各環境

### Cursor

```bash
git clone https://github.com/eric4057/dsl-to-langgraph.git
mkdir -p ~/.cursor/skills
ln -sfn "$(pwd)/dsl-to-langgraph" ~/.cursor/skills/dsl-to-langgraph
```

或直接用 Cursor 打開本 repo。

### OpenClaw

把本目錄放到（或複製到）：

```text
workspace/skills/dsl-to-langgraph
```

容器內常見路徑：

```text
/home/node/.openclaw/workspace/skills/dsl-to-langgraph
```

觸發後用 **`exec`** 跑腳本，**不要**呼叫名為 `dsl-to-langgraph` 的 tool。

OpenClaw 瘦身範例：

```bash
python3 /home/node/.openclaw/workspace/skills/dsl-to-langgraph/scripts/slim_dsl.py \
  "/path/to/flow.yml" -o /tmp/flow.slim.yml
```

### ChatGPT Custom GPT

1. Instructions：貼上 [`gpt/CUSTOM_GPT_INSTRUCTIONS.md`](gpt/CUSTOM_GPT_INSTRUCTIONS.md)  
2. Knowledge：上傳 `SKILL.md`、`references/`、`assets/templates/`（可打 zip）

### Codex / OpenAI skill bundle

上傳整個 repo（至少 `SKILL.md` + `agents/` + `scripts/` + `references/` + `assets/`）。

---

## 給 Agent 的提示詞範例

```text
使用 dsl-to-langgraph skill。
1) 先用 scripts/slim_dsl.py 瘦身 /path/to/flow.yml → /tmp/flow.slim.yml
2) 再 parse_dsl.py 產出 inventory
3) scaffold 到 /tmp/my-langgraph（--model-name xxx）
4) 依 SKILL.md 完成語意等價遷移與 OpenAI-compatible api.py
```

只解析：

```text
用 dsl-to-langgraph 先 slim 再解析 /path/to/flow.yml，
告訴我 source、has_rag、suggested_langgraph_nodes 與建議拓撲。
```

---

## 更多文件

- [`SKILL.md`](SKILL.md) — 完整遷移步驟  
- [`references/REFERENCE.md`](references/REFERENCE.md) — 節點對映、引用固定順序  
- [`references/EXAMPLES.md`](references/EXAMPLES.md) — 範例  
- [`references/CHECKLIST.md`](references/CHECKLIST.md) — 驗收清單  

## 授權

Private／內部使用。請勿提交 DSL 內密鑰。
