# 節點類型固定結構（Node Contract）

**主場景：Dify `data.type` → LangGraph node。**  
遷移時以 `parse_dsl.py` 產出的 **`dify_node_mapping`** 為準：每一個 Dify 節點對應 `implement`／`merge`／`ignore` 與建議函式名／模板。

## 禁止自由發揮（硬性）

| 允許 | 禁止 |
|---|---|
| 依 mapping 的 `template` 複製後填業務語意 | 自創 node 檔案結構／簽名 |
| 依 Dify prompt／URL／cases 填 CALL 區 | 發明 DSL 沒有的節點或分支 |
| merge 列併入相鄰 implement，並註明 dify_id | 把多個無關 type 揉成一個「神節點」 |
| 高頻節點用 `NodeDebug`／`log_route` | 刪除 META／`DSL_ID`／契約 docstring |

**逐列協定：** `implement` → 複製模板＋填 META；`merge`／`ignore` → 不建檔。  
功能結構化 = **同一 type 永遠同一套形狀**，只換 DSL 帶進來的資料。

通用規則適用全部節點；各類型再補專用欄位與模板。

**範圍：** 只為 inventory 中實際存在的 Dify 工項建檔；沒有的 type 不要預先實作。

模板目錄：[`assets/templates/nodes/`](../assets/templates/nodes/)  
DEBUG 共用：[`assets/templates/node_debug.py.tmpl`](../assets/templates/node_debug.py.tmpl)  
單節點 CLI：[`assets/templates/run_node.py.tmpl`](../assets/templates/run_node.py.tmpl)

---

## 高頻節點 DEBUG 固定格式（必遵）

依常見 DSL 統計，下列 type 必須用固定外殼（方便對齊 DSL_ID、看 IN/OUT、累積 `state.trace`）：

| 優先 | DSL type | 模板 | META 常數 |
|---|---|---|---|
| 1 | `code` | `code_transform.py.tmpl` | `NODE_KEY` / `DSL_*` |
| 2 | `llm` | `llm.py.tmpl` | 同上 |
| 3 | `knowledge-retrieval` | `retrieve.py.tmpl` | 同上 |
| 4 | `answer` | `answer_full.py.tmpl` | 同上 |
| 5 | `http-request` | `http_request.py.tmpl` | 同上 |
| 6 | `if-else` | `route.py.tmpl` | `ROUTE_NAME` + `log_route` |
| 7 | `start` | `normalize_input.py.tmpl`／`start.py.tmpl` | 同上 |

### 每個高頻節點檔案固定長這樣

```python
"""節點：…

DSL: <type> / <title>
DSL_ID: <dify node id>
讀取: …
寫入: …
"""

# --- META（DEBUG 定位；勿刪）---
NODE_KEY = "retrieve"
DSL_TYPE = "knowledge-retrieval"
DSL_TITLE = "知識庫檢索"
DSL_ID = "1781…"          # 對齊 inventory / Dify id
READS = ("query", "retrieval_query")
WRITES = ("documents",)

def retrieve_node(state):
    dbg = NodeDebug(NODE_KEY, DSL_TYPE, DSL_TITLE, DSL_ID, state, READS)
    try:
        # --- READ ---
        # --- CALL ---   # I/O → services；純邏輯 → logic
        # --- WRITE ---
        return dbg.ok({...})
    except Exception as exc:
        return dbg.fail(exc, fallback={...}, error_field="…_error")
        # 或：raise dbg.reraise(exc) from exc
```

### DEBUG 產物

| 機制 | 說明 |
|---|---|
| `state["trace"]` | `Annotated[..., operator.add]`；每節點回傳 `trace: [entry]` |
| `entry` 欄位 | `node`, `dsl_type`, `dsl_title`, `dsl_id`, `status`, `reads`, `writes_keys`, `writes`(摘要), `error`, `elapsed_ms` |
| `DEBUG_NODES=true` | logging：`[node=…] IN/OUT/ERR` |
| `python run_node.py <node> --query …` | 不跑整圖，單點驗證 |

`if-else` 回傳 `str`，用 `log_route(...)`；不寫 `trace`（可在前後業務節點看 condition 欄位）。

---

## 通用契約（所有節點）

### 檔案與命名

| 項目 | 規則 |
|---|---|
| 檔案 | `nodes/<動詞>.py`，一邏輯一檔 |
| 函式 | `def <name>_node(state: WorkflowState) -> dict:` |
| 路由函式 | `def route_<name>(state: WorkflowState) -> str:`（僅條件邊） |
| 匯出 | `nodes/__init__.py` 明確 `__all__` |

### Docstring（必填）

```python
"""節點：<一句職責>

DSL: <原 type> / <原 title>
DSL_ID: <原 node id>
讀取: <state 欄位, ...>
寫入: <state 欄位, ...>
"""
```

### 行為

1. 簽名固定：`(state: WorkflowState) -> dict`
2. **只回傳要更新的欄位**（partial update）；高頻節點另透過 `dbg.ok`／`dbg.fail` 附上 `trace`
3. 外部 I/O（LLM／HTTP／向量庫）走 `services.py`，節點內不直接建 client
4. 可恢復錯誤：寫入 `error`（或類型專用 `*_error`），勿讓整圖無訊息崩潰（除非輸入非法需 400）
5. 禁止在節點內讀真實密鑰硬編碼；只用 `settings`
6. 高頻節點必須含 `# --- META ---` 與 `READ → CALL → WRITE` 分段註解（見上）

---

## 類型對照與契約

| DSL type | LangGraph 模組／函式 | 模板 | 備註 |
|---|---|---|---|
| `start` | `normalize_input_node` | `normalize_input.py.tmpl` | 亦可部分在 API 組 state |
| `llm` | `<role>_llm_node` | `llm.py.tmpl` | 依職責命名：`classify`／`direct_answer`／`generate` |
| `answer` | `answer_node` 或併入上一 LLM | `answer_full.py.tmpl`（scaffold 佔位為 `answer.py.tmpl`） | 最終寫 `answer`；串流用 `answer_delta` |
| `question-classifier` | `classify_node` + `route_after_classify` | `classify.py.tmpl` | 必搭配 conditional edges |
| `if-else` | `route_<name>` | `route.py.tmpl` | 通常無獨立業務 node，只回字串標籤 |
| `knowledge-retrieval` | `retrieve_node` | `retrieve.py.tmpl` | 後端用 **pgvector**（`--with-pgvector`）；僅 `has_citation` 才接 citation 鏈 |
| `http-request` | `<service>_http_node` | `http_request.py.tmpl` | |
| `tool` | `<tool>_node` | `tool.py.tmpl` | Firecrawl 等 |
| `code` | 純函式在 `logic.py` + 薄 node，或併入鄰居 | `code_transform.py.tmpl` | 引用／context 類併入 build_context／answer |
| `agent` | `plan_*_node` 或工具序列 | `agent.py.tmpl` | 優先拆成明確節點 |
| `parameter-extractor` | `extract_<name>_node` | `parameter_extractor.py.tmpl` | 常可與 agent／LLM 合併 |
| `document-extractor` | `extract_document_node` | `document_extractor.py.tmpl` | |
| `loop`／`iteration` | `<batch>_node` 內 for，或有限狀態機 | `iteration.py.tmpl` | 避免無限迴圈 |
| `template-transform` | helper，**不單獨成 node** | — | 併入下一節點 |
| `assigner` | state 更新，**常併入** | — | 可內嵌於前後 node |
| `variable-aggregator` | **刪除** | — | 上游寫同一欄位 |
| `custom-note` | **忽略** | — | |
| （RAG 衍生） | `order_citations_node`／`build_context_node` | `order_citations.py.tmpl`／`build_context.py.tmpl` | 僅 DSL 含引用／來源工項時才做 |

---

## 各類型：讀寫欄位與結構要點

### 1. `normalize_input`（start）

- **讀取：** `query`, `history`
- **寫入：** `query`, `history`（清理後）；非法輸入 `raise ValueError`
- **結構：** 無外部 I/O

### 2. `llm`

- **讀取：** 依 prompt 所需（`query`／`context`／`evidence_text`…）
- **寫入：** 業務欄位（如 `direct_answer`、`answer_markdown`、structured 結果）
- **結構：**
  1. 組 messages（system／user 從 DSL 抽出，放 `prompts.py` 常數）
  2. `services.chat_text` 或 `chat_json`
  3. 解析後回傳 dict
- **禁止：** 節點內 `OpenAI(...)`

### 3. `answer`

- **讀取：** 最終文字來源（`final_answer`／`direct_answer`／生成結果）
- **寫入：** `answer`（必要）；可選 `sources`
- **結構：** 若需串流 → `get_stream_writer()` 發 `{"type":"answer_delta","content":...}`  
- DSL 有引用／來源工項時，先跑引用後處理再寫入

### 4. `question-classifier` → classify + route

- **classify 寫入：** `need_search`／`platform`／`label`, `classify_reason`
- **route：** 純函式，回傳邊標籤字串（如 `"search"`／`"direct"`）
- **結構：** classify 用 JSON schema；route **不含** I/O

### 5. `if-else` → route

- **讀取：** 條件相關 state
- **回傳：** `str` 標籤，對應 `add_conditional_edges` mapping
- **結構：** 無 I/O；處理 DSL 布林／字串不一致（如 `true`／`"yes"`）

### 6. `knowledge-retrieval` → retrieve

- **讀取：** `retrieval_query` 或 `query`；可選 `platform`
- **寫入：** `documents: list[{content, score, metadata, ...}]`
- **結構：** 只檢索；排序／組 context 分給後續節點

### 7. `http-request`

- **讀取：** URL／query 所需 state
- **寫入：** `http_status`, `http_body`（或專用名如 `search_raw`）
- **結構：** `services` 內 `httpx`；逾時／非 2xx 寫 `*_error` 與可降級結果

### 8. `tool`

- **讀取：** tool 參數對應欄位（如 `url`）
- **寫入：** tool 原始／正規化輸出
- **結構：** 與 http 相同層級；認證只從 `settings`

### 9. `code` → transform／logic

- **優先：** 抽出純函式到 `logic.py`，node 只做 state 進出
- **引用／ledger／formatter：** 併入 `build_context`／`output_formatter`／`answer`
- **寫入：** code 的 outputs 對映到 state 鍵

### 10. `agent`

- **讀取：** `query`
- **寫入：** 規劃結果（如 `queries`, `plan_raw`）
- **結構：** 能改寫成「單次 structured LLM」就不要上完整 ReAct；需要工具時拆成後續 http／tool 節點

### 11. `parameter-extractor`

- **讀取：** 上游文字
- **寫入：** 具名欄位（如 `queries: list[str]`）
- **結構：** JSON／schema 解析；失敗時合理 fallback

### 12. `document-extractor`

- **讀取：** 檔案路徑／bytes／URL
- **寫入：** `extracted_text`（或 chunks）
- **結構：** 解析邏輯可放 `services`／`logic`

### 13. `iteration`／`loop`

- **讀取：** 迭代列表（如 `queries`／`selected_urls`）
- **寫入：** 累積結果（如 `selected_urls`／`all_scrape_results`）
- **結構：** 單一 node 內 `for` 批次（有上限）；或明確 loop 狀態 + 條件邊（須防無限）

### 14. RAG：`order_citations`／`build_context`

- **order_citations 讀寫：** `documents`（重排）
- **build_context 寫入：** `context`, `citation_map`；來源鍵穩定（url／path）
- 見 REFERENCE 引用固定順序一節

---

## 最小範例骨架（所有類型共用形狀）

```python
"""節點：<職責>

DSL: <type> / <title>
讀取: a, b
寫入: c, d
"""

from __future__ import annotations

from state import WorkflowState


def example_node(state: WorkflowState) -> dict:
    # 1. 讀取
    # 2. 呼叫 services / logic
    # 3. 回傳 partial update
    return {"c": "..."}
```

實作時複製 [`assets/templates/nodes/`](../assets/templates/nodes/) 對應 `.tmpl`，替換 DSL 語意後刪除佔位註解。
