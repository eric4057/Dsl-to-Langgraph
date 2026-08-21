# Dsl-to-Langgraph

**主用途：** 將 **Dify** 匯出的工作流 DSL（`kind: app` + `workflow.graph`）轉成獨立 **LangGraph** Python 服務，並提供 **OpenAI-compatible HTTP API**。

次要相容：LangFlow／Flowise／n8n／通用 nodes＋edges。  
適用環境：Cursor、OpenClaw、ChatGPT Custom GPT、Codex／GPT Skills，以及純 CLI。

## 內含程式

| 程式 | 路徑 | 用途 |
|---|---|---|
| DSL 瘦身 | [`scripts/slim_dsl.py`](scripts/slim_dsl.py) | 去除大型匯出檔的 UI／佈局雜訊，並遮罩明顯密鑰，供後續解析或交給 agent |
| DSL 解析 | [`scripts/parse_dsl.py`](scripts/parse_dsl.py) | 產出 inventory；Dify 另含 `dify_node_mapping`、`dify_branch_edges`、`has_citation` |
| 專案骨架 | [`scripts/scaffold_project.py`](scripts/scaffold_project.py) | 產生 LangGraph 骨架；`--with-pgvector` 時加 RAG 資料庫（compose／schema／ingest） |
| **依 inventory 產生節點** | [`scripts/generate_from_inventory.py`](scripts/generate_from_inventory.py) | 讀 mapping + 模板（建議加 `--dsl`）→ 寫出 `nodes/`、`graph.py`、`logic.py`、`prompts.py` |

輔助文件：[`SKILL.md`](SKILL.md)（agent 遷移流程）、[`references/`](references/)（對映／契約／範例／驗收）、[`assets/templates/`](assets/templates/)（骨架與**各節點類型**模板）、[`agents/openai.yaml`](agents/openai.yaml)、[`gpt/CUSTOM_GPT_INSTRUCTIONS.md`](gpt/CUSTOM_GPT_INSTRUCTIONS.md)。

每個 Dify 節點功能必須**結構化**、禁止自由發揮：以 inventory `dify_node_mapping` 逐列複製對應模板（見 [`references/NODE_CONTRACT.md`](references/NODE_CONTRACT.md)、[`assets/templates/nodes/`](assets/templates/nodes/)）。  
高頻節點另有 **DEBUG 固定外殼**（`node_debug.py`、`state.trace`、`run_node.py`、`DEBUG_NODES`）。

### `scripts/slim_dsl.py`

處理過大的 DSL 匯出（例如數千行 Dify YAML），降低塞入 agent時的 context 壓力。

- **移除：** 畫布資訊（`position`、`selected`、`viewport` 等）、icon、tool `paramSchemas`，以及其他非語意 UI 欄位  
- **保留：** 圖拓撲、節點 `type`／`title`、prompt、code、HTTP／KB 設定、分支條件、模型識別  
- **遮罩：** 明顯密鑰 → `{{REDACTED}}`  
- **輸出：** 仍可供 `parse_dsl.py` 解析

```bash
python3 scripts/slim_dsl.py path/to/flow.yml -o /tmp/flow.slim.yml
python3 scripts/slim_dsl.py path/to/flow.yml -o /tmp/flow.slim.json --format json
```

讀取 YAML 需安裝：`pip install pyyaml`。

### `scripts/parse_dsl.py`

辨識 DSL 方言，並彙整圖結構，供遷移規劃使用。

```bash
python3 scripts/parse_dsl.py /tmp/flow.slim.yml -o /tmp/inventory.json
```

常見欄位：`source`、`has_rag`、`has_citation`、`type_counts`、`external_hints`、`suggested_langgraph_nodes`。  
Dify 另有：`dify_node_mapping`（每節點 → implement／merge／ignore + LangGraph 名 + 模板）、`dify_branch_edges`（classifier／if-else 分支）。  
有 KB 只建議 `retrieve`；偵測到引用／來源工項才建議 `order_citations`／`build_context`。

### `scripts/scaffold_project.py`

建立最小可用的 OpenAI-compatible LangGraph 服務。專案名為非 ASCII（例如中文）時，請明確指定 `--model-name`。

```bash
python3 scripts/scaffold_project.py \
  --name "my-app" \
  --out ./my-app \
  --model-name my-app \
  --port 8030
```

| 參數 | 必填 | 說明 |
|---|---|---|
| `--name` | 是 | 專案顯示名稱 |
| `--out` | 是 | 輸出目錄（須為空或不存在） |
| `--model-name` | 否 | 對外 `API_MODEL`；中文名強烈建議指定 |
| `--port` | 否 | **可自訂**；寫入骨架的 `API_PORT`。不傳時預設 **8000**（上例 `8030` 僅為示範） |

產出後也可在專案 `.env` 用 `API_PORT=` 隨時改埠，不必重跑 scaffold。

骨架中的 `nodes/answer.py` 僅為佔位實作；交付前須改寫為 DSL 對應邏輯。

### `scripts/generate_from_inventory.py`

在 scaffold 之後（或加 `--scaffold` 一次做完），依 `dify_node_mapping` **自動產生**結構化節點與 `graph.py`：

```bash
python3 scripts/parse_dsl.py flow.yml -o inventory.json
python3 scripts/generate_from_inventory.py \
  --inventory inventory.json --dsl flow.yml --out ./my-app \
  --scaffold --name my-app --model-name my-app --port 8030
```

| 參數 | 說明 |
|---|---|
| `--inventory` | `parse_dsl.py` 產出 |
| `--dsl` | **強烈建議**：原始／slim YAML，才能嵌入完整 code／prompt |
| `--out` | 專案目錄 |
| `--scaffold` | 目錄為空時先跑 scaffold；`has_rag` 時可加 `--with-pgvector` |
| `--force` | 覆寫已產生的 nodes |

產出含 `GENERATE_REPORT.json`（merge 對照、警告）。Agent 仍須校對 selector、補 conditional edges、填 `.env` 並驗收。

## OpenAI-compatible API（LangGraph 對外介面）

遷移／scaffold 產出的專案會包含 [`assets/templates/api.py.tmpl`](assets/templates/api.py.tmpl) → `api.py`：  
**內部跑 LangGraph**（`graph.invoke`／`graph.astream`），**對外提供 OpenAI Chat Completions 格式**，供 curl、Open WebUI、LiteLLM 等直接呼叫。

| 路由 | 說明 |
|---|---|
| `POST /v1/chat/completions` | 問答；`stream: true` 時以 SSE 回傳 delta |
| `GET /v1/models` | 回傳 `API_MODEL` |
| `GET /health` | 健康檢查 |

這不是把「既有 LangGraph Server API」自動轉成 OpenAI 的獨立轉接器，而是產出專案時**內建**這層包裝（LangGraph 在內、OpenAI 格式在外）。完整遷移時 `SKILL.md` 要求必須保留此 API。

## CLI 完整流程

```bash
cd /path/to/dsl-to-langgraph
python3 -m venv .venv && source .venv/bin/activate
pip install pyyaml

python3 scripts/slim_dsl.py your-flow.yml -o /tmp/your-flow.slim.yml
python3 scripts/parse_dsl.py /tmp/your-flow.slim.yml -o /tmp/inventory.json
python3 scripts/scaffold_project.py \
  --name "my-app" --out ./my-app --model-name my-app --port 8030
  # --port 可改成任意可用埠；省略則預設 8000
```

接著依 [`SKILL.md`](SKILL.md)，以 inventory 為依據實作真實節點（語意等價遷移，而非逐一搬運所有 glue 節點）。

## 倉庫結構

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

## 安裝

### Cursor

```bash
git clone https://github.com/eric4057/dsl-to-langgraph.git
mkdir -p ~/.cursor/skills
ln -sfn "$(pwd)/dsl-to-langgraph" ~/.cursor/skills/dsl-to-langgraph
```

或直接以 Cursor 開啟本倉庫（`.cursor/skills/` 內含專案 skill 連結）。

### OpenClaw

將本目錄放置或複製至 `workspace/skills/dsl-to-langgraph`（容器內常見路徑為 `/home/node/.openclaw/workspace/skills/dsl-to-langgraph`）。請以 **`exec`** 執行腳本，勿呼叫不存在的 `dsl-to-langgraph` tool。

```bash
python3 /home/node/.openclaw/workspace/skills/dsl-to-langgraph/scripts/slim_dsl.py \
  /path/to/flow.yml -o /tmp/flow.slim.yml
```

### ChatGPT Custom GPT

1. 將 [`gpt/CUSTOM_GPT_INSTRUCTIONS.md`](gpt/CUSTOM_GPT_INSTRUCTIONS.md) 貼入 Instructions  
2. 上傳 `SKILL.md`、`references/`、`assets/templates/` 作為 Knowledge  

### Codex／OpenAI skill bundle

安裝或上傳 skill 根目錄（`SKILL.md` + `agents/` + `scripts/` + `references/` + `assets/`）。

## Agent 提示詞範例

```text
使用 dsl-to-langgraph skill。
1. slim_dsl.py → /tmp/flow.slim.yml
2. parse_dsl.py → inventory.json
3. scaffold_project.py → /tmp/my-langgraph（--model-name …）
4. 依 SKILL.md 完成語意等價遷移，含 OpenAI-compatible api.py
```

## 延伸閱讀

- [`SKILL.md`](SKILL.md) — 遷移流程  
- [`references/REFERENCE.md`](references/REFERENCE.md) — 節點對映與引用規則  
- [`references/NODE_CONTRACT.md`](references/NODE_CONTRACT.md) — 各類型節點固定結構  
- [`references/EXAMPLES.md`](references/EXAMPLES.md)  
- [`references/CHECKLIST.md`](references/CHECKLIST.md)  

## 授權

Private／內部使用。請勿提交 DSL 匯出中的密鑰。
