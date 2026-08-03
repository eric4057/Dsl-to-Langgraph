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
| `code` | 若為引用／context 組裝 → 併入 `build_context`／`answer`；其餘才獨立 `transform` |
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

## 引用／參考連結固定順序

適用：DSL 有知識檢索、retriever resource、citation、或「來源」區塊時。  
基準實作：`nchc_qa_langgraph` 的 `order_citations` → `build_context` → `answer` 後處理。

### 規則

1. **來源鍵**：`source_url` 優先，否則 `source_path`／穩定檔名；同一鍵共用一個 id。
2. **餵給模型前**（可選但建議）：依問題語意對來源分組排序（`order_citations`），讓 1..N 較合理。
3. **模型輸出格式（預設）**：`[[n]](URL)`（或後處理可辨識的 `[n]`），禁止自創網址列表。  
   若使用者明確要求保留原 DSL 對外引用格式，則保留該格式，但仍須滿足「連續編號＋來源順序一致」。
4. **後處理固定順序**（必做）：
   - 掃描回答中引用「第一次出現」的舊 id 順序
   - 重編為連續 `1..N`
   - 改寫成可點擊連結（預設 `[[new]](url)`）
   - 文末追加 `### 來源`，列序與文中 1..N **完全一致**
5. **禁止**：跳號、來源區塊與文中順序不一致、把未引用來源塞進列表湊數。

### inventory 會抽出的重點

`parse_dsl.py` 對 Dify 會盡量帶出（勿只依賴 type 名稱）：

- `prompt_excerpt`、`answer_template_excerpt`
- `dataset_ids`、`retrieval_mode`、rerank 相關 config
- `code_excerpt` + `code_looks_like_citation`
- `has_rag` 與建議節點（含 `order_citations`／`build_context`）

### 建議節點切分

```text
retrieve → order_citations → build_context → answer(_link_citations)
```

- `build_context`：組 `<document id="n">` 與 `citation_map`
- `answer`：串流正文；結束後跑 `_link_citations` 再補來源區塊（串流可先送正文、後送來源）

### 驗收例子

| 模型原始輸出 | 使用者應看到 |
|---|---|
| `先說 [[4]]，再說 [[2]]` | `先說 [[1]](url4)，再說 [[2]](url2)`，來源區塊亦為 1→2 |
| 有引用 1、2、缺 3 | 重編後僅連續用到的編號；來源區塊不含未使用項 |

## 安全

- DSL 可能含 API key／dataset 憑證：寫入 `.env.example` 佔位，**不要**提交真實值
- `code` 節點程式碼需人工審視後再遷入
- 對外 API 預設可關 auth；有 `API_AUTH_KEY` 則強制 Bearer
