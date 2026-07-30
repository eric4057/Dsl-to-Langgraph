# DSL → LangGraph 參考

> 由 `SKILL.md` 按需載入。

## 支援的 DSL

### 1. Dify（YAML / JSON）

特徵：

- `kind: app`
- `app.mode`: `advanced-chat` / `workflow` / `chat`
- `workflow.graph.nodes` + `workflow.graph.edges`

重要欄位：

- 節點：`id`、`data.type`、`data.title`、`data` 內 prompt／dataset／code
- 邊：`source`、`target`、`sourceHandle`（分類／if-else 分支鍵）

### 2. LangFlow（JSON）

特徵：`data.nodes` / `data.edges`，或頂層 `nodes`/`edges`；component 常有 `data.type` / `data.node.template`。

對映思路：每個 component → 一個 node 函式或 service 呼叫；ChatInput/Output → API 邊界，不進 graph 中間態。

### 3. Flowise（JSON）

特徵：chatflow 的 `nodes` + `edges`；常見 `chatPromptTemplate`、`openAI`、`retriever`、`agent`。

對映：線性 chain 變 `add_edge`；agent 工具改為明確節點或 `ToolNode`（僅在需要 ReAct 時）。

### 4. n8n（JSON）

特徵：`nodes` + `connections`（非 edges 陣列）。

先把 `connections` 展成 edge 列表，再套同一套拓撲規則。IF / Switch → conditional edges。

### 5. Generic nodes+edges

接受最小格式：

```yaml
name: my-flow
nodes:
  - id: start
    type: start
    title: Start
  - id: answer
    type: llm
    title: Answer
    config:
      prompt: "..."
edges:
  - source: start
    target: answer
```

或 JSON 等價結構。`parse_dsl.py` 對此直接輸出 inventory。

---

## Dify 節點 → LangGraph

| Dify `data.type` | LangGraph 作法 |
|---|---|
| `start` | API 組初始 state；可選 `normalize_input` 節點 |
| `answer` | 寫入 `answer`；串流用 stream writer |
| `llm` | LLM 節點；prompt 從 DSL 抽出 |
| `question-classifier` | 分類節點 + `add_conditional_edges` |
| `if-else` | 條件函式 + conditional edges |
| `knowledge-retrieval` | `retrieve`（Qdrant 等）；多知識庫 → 多 collection 或 `multi` |
| `variable-aggregator` | 通常刪除；上游寫入同一 state 欄位 |
| `template-transform` | Jinja/f-string helper，併入下一節點 |
| `code` | 純函式模組；有副作用則獨立 node |
| `http-request` / `tool` | `httpx` service + node |
| `assigner` | 直接在 node 回傳 state 更新 |
| `loop` / `iteration` | 有限迴圈狀態或一次批次處理 |
| `agent` | 拆成工具節點序列，或單一 agent 節點（註明工具清單） |
| `document-extractor` | 前處理 node（PDF/音訊等） |
| `custom-note` | 忽略（文件用） |

## 其他 DSL 常見對映

| 概念 | LangGraph |
|---|---|
| Router / IF / Switch | `add_conditional_edges` |
| Parallel branches | 多 node 後 list fan-in edge |
| Retriever / Vector store | `retrieve` + 外部向量 DB |
| Tool / HTTP / Webhook | service + node |
| Memory / conversation | `history` in state；API 從 messages 組入 |
| Output / End | `answer` → `END` |

---

## 專案檔案職責

| 檔案 | 職責 |
|---|---|
| `graph.py` | `StateGraph`、edges、`compile()`、匯出 `graph` |
| `state.py` | `WorkflowState` 與共用 TypedDict |
| `nodes/*.py` | 單一節點邏輯 |
| `config.py` | 環境變數 |
| `services.py` | 共用客戶端（LLM、Qdrant、HTTP） |
| `api.py` | OpenAI-compatible HTTP |
| `langgraph.json` | `langgraph dev` 入口 |

## 串流約定

回答節點內：

```python
from langgraph.config import get_stream_writer

writer = get_stream_writer()
if writer:
    writer({"type": "answer_delta", "content": token})
```

`api.py` 只轉發 `type == "answer_delta"` 的 content 成 SSE `delta.content`。

## 安全

- DSL 可能含 API key／dataset 憑證：寫入 `.env.example` 佔位，**不要**提交真實值
- `code` 節點程式碼需人工審視後再遷入
- 對外 API 預設可關 auth；有 `API_AUTH_KEY` 則強制 Bearer
