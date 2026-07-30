---
name: dsl-to-langgraph
description: >-
  Convert workflow DSLs (Dify YAML, LangFlow/Flowise JSON, n8n-like graphs,
  or generic nodes+edges YAML/JSON) into a standalone LangGraph Python project
  with graph.py, state.py, nodes/, api.py, and OpenAI-compatible HTTP API.
  Use when the user asks to convert DSL to LangGraph, migrate a Dify workflow,
  scaffold a LangGraph service from a graph export, or rebuild a chat/RAG/video
  pipeline as an independent project.
---

# DSL → LangGraph

將工作流 DSL 轉成**可獨立執行**的 LangGraph 專案（非 Dify 外掛、非 runtime 解譯器）。

參考實作：`nchc_qa_langgraph`、`gba_langgraph`、`gba_dual_langgraph`。

## 何時使用

- 使用者提供 Dify / LangFlow / Flowise / n8n / 自訂 nodes+edges 匯出檔
- 要求產出完整專案：`graph.py`、`state.py`、`nodes/`、`api.py`、OpenAI-compatible API
- 要把既有工作流從平台鎖死環境遷出

## 產出目標（固定）

```text
<project>/
├── api.py              # FastAPI：/v1/chat/completions、/v1/models、/health
├── graph.py            # StateGraph 組裝與 compile
├── state.py            # WorkflowState TypedDict
├── config.py           # pydantic-settings / env
├── services.py         # 選用：LLM、HTTP、向量庫等封裝
├── nodes/              # 一節點一模組
│   ├── __init__.py
│   └── *.py
├── langgraph.json
├── requirements.txt 或 pyproject.toml
├── .env.example
├── README.md
└── tests/              # 至少覆蓋路由與關鍵節點
```

預設：**語意等價遷移**（行為對齊），不是逐節點 1:1 死搬。可合併純 glue 節點（template、assigner、單純 aggregator）。

## 工作流程

複製並追蹤：

```text
Progress:
- [ ] 1. 辨識 DSL 並解析圖
- [ ] 2. 畫出目標 LangGraph 拓撲
- [ ] 3. 定義 WorkflowState
- [ ] 4. scaffold 專案骨架
- [ ] 5. 實作 nodes / graph / config / services
- [ ] 6. 實作 OpenAI-compatible api.py
- [ ] 7. README、.env.example、測試
- [ ] 8. 對照 checklist 驗收
```

### 1. 辨識與解析

先跑（有檔案時）：

```bash
python3 ~/.cursor/skills/dsl-to-langgraph/scripts/parse_dsl.py <dsl-file> [-o inventory.json]
```

依副檔名／內容判斷來源：

| 訊號 | 來源 |
|---|---|
| 頂層 `kind: app` + `workflow.graph` | Dify YAML |
| `nodes`/`edges` 且含 `data.type` 如 `llm`、`knowledge-retrieval` | Dify |
| `nodes` 含 `data.type` 為 LangFlow component 名 | LangFlow |
| Flowise `nodes`/`edges` chatbot flow | Flowise |
| n8n `nodes` + `connections` | n8n |
| 自訂 `nodes` + `edges`（或 `links`） | Generic |

產出 inventory：app 名稱、節點表（id/type/title/關鍵設定）、邊表、分支／平行／迴圈、外部依賴（KB、HTTP、tools、models）。

詳見 [REFERENCE.md](REFERENCE.md)。

### 2. 拓撲設計

規則：

1. **合併 glue**：`template-transform`、`assigner`、僅轉格式的 `code`、單純 `variable-aggregator` → 併入相鄰業務節點或 helper。
2. **保留決策**：`if-else`、`question-classifier`、n8n IF、LangFlow router → `add_conditional_edges`。
3. **平行**：Dify 多分支出發後再 aggregator、或雙路 API → LangGraph 多節點後 fan-in（參考 `gba_dual_langgraph`）。
4. **迴圈**：能改寫成有限重試／單一 retrieve 迴圈就改寫；否則用明確的 loop 狀態欄位 + 條件邊。
5. **知識庫**：平台內建 KB → 獨立向量服務（常用 Qdrant）+ `retrieve` 節點；不要假裝還呼叫 Dify dataset API（除非使用者要求）。
6. **回答節點**：最終寫入 `state["answer"]`；串流用 `langgraph.config.get_stream_writer()` 發 `{"type":"answer_delta","content":...}`。

在 README／回覆中先給文字或 mermaid 流程，再寫碼。

### 3. 狀態

`state.py` 用 `TypedDict, total=False`。最少：

- 輸入：`query`、`history`（及檔案／影像等）
- 中間：路由結果、documents、context、外部 API 原始結果
- 輸出：`answer`、可選 `sources`

節點函式簽名：`def node(state: WorkflowState) -> dict:`，只回傳要更新的欄位。

### 4. Scaffold

```bash
python3 ~/.cursor/skills/dsl-to-langgraph/scripts/scaffold_project.py \
  --name <project_slug> \
  --out <target_dir> \
  --model-name <api_model> \
  --port <port>
```

再依 inventory 填實作；不要留下 TODO 佔位當完成。

### 5. 實作慣例

- **一 DSL 邏輯區塊 → 一個 `nodes/*.py`**，名稱用動詞：`classify.py`、`retrieve.py`。
- **`graph.py` 只組裝**，不含業務邏輯。
- **`config.py`**：`pydantic-settings` + `.env`；機密不進 git。
- **外部呼叫**：集中 `services.py` 或 `nodes` 內小函式；失敗要可降級或寫入 state 供後續說明。
- **繁中產品**：使用者可見字串預設繁體中文（與既有專案一致）。
- Prompt／分類規則／固定回答：從 DSL 抽出，保留語意，可整理成常數或 `prompts.py`。

節點對映表見 [REFERENCE.md](REFERENCE.md)。範例見 [EXAMPLES.md](EXAMPLES.md)。

### 6. OpenAI-compatible API

`api.py` 必須提供：

| 路由 | 行為 |
|---|---|
| `POST /v1/chat/completions` | 非串流 `graph.invoke`；串流 `graph.astream(..., stream_mode="custom")` → SSE |
| `GET /v1/models` | 回傳 `API_MODEL` |
| `GET /health` | liveness；相依服務可標 `degraded` |

慣例：

- 可選 `API_AUTH_KEY` + Bearer
- CORS 開放（與既有專案一致）
- 從 `messages` 取最後一則 user 為 `query`，先前為 `history`
- 需要檔案時：`POST /v1/files` 二段式（參考 `gba_dual_langgraph`）
- 模型名容忍 `openai/<name>` 前綴（LiteLLM）

### 7. 文件與測試

- README：來源 DSL 名稱、流程圖、結構、環境變數、curl 範例
- `.env.example`：所有必要 key，無真實密鑰
- `tests/`：路由函式、純函式節點、至少一條 happy-path graph（可 mock 外部 API）

### 8. 驗收

見 [CHECKLIST.md](CHECKLIST.md)。全部勾完才算完成。

## 自由度

| 可改 | 不可擅自改 |
|---|---|
| 合併 glue、重新命名節點、拆檔 | 刪除業務分支、改變分類語意 |
| 換向量庫／HTTP client 實作 | 拿掉 OpenAI-compatible API |
| 平行化獨立 I/O | 把密鑰寫進 repo |

若 DSL 含無法離線重現的能力（付費外掛、平台私有 KB），在 README 標「需替代實作／需憑證」，並實作明確介面，不要靜默省略。

## 附加資源

- [REFERENCE.md](REFERENCE.md) — DSL 辨識與節點對映
- [EXAMPLES.md](EXAMPLES.md) — 依既有專案的轉換範例
- [CHECKLIST.md](CHECKLIST.md) — 交付驗收
- `scripts/parse_dsl.py` — 解析 inventory
- `scripts/scaffold_project.py` — 專案骨架
- `templates/` — 骨架檔內容來源
