# 轉換範例

以下對應真實專案，作為風格與切割粒度基準。

## 例 1：Dify RAG 客服 → `nchc_qa_langgraph`

**來源**：Dify advanced-chat（問題分類 + 多知識庫 + 引用回答）

**DSL 特徵**：`question-classifier`、多個 `knowledge-retrieval`、`code`、`template-transform`、`answer`

**目標拓撲**：

```text
START → normalize_input → rewrite_query → classify
  ├─ fixed / out_of_scope → fixed_answer → END
  └─ retrieve → order_citations → build_context → answer → END
```

**遷移重點**：

- 多個 knowledge-retrieval + aggregator → 單一 `retrieve`（依 platform 選 collection／`multi`）
- 引用編號邏輯從 code/template 收斂到 `context.py` + `answer.py`
- 固定匯款／超出範圍 → `fixed_answer`，不走檢索

**API**：`:8020`，`API_MODEL=nchc-qa-langgraph`

## 例 2：Dify 影片行為查詢 → `gba_langgraph`

**來源**：影片 → UAS `/predict` → SearXNG → LLM 回答

**目標拓撲**（線性）：

```text
START → start_input → predict_video → format_prediction
  → build_search_query → search_searxng → format_search_results
  → generate_llm_answer → answer → END
```

**遷移重點**：

- HTTP 節點變 `services`／node 內 `httpx`
- 每個階段獨立 `nodes/*.py`
- 外部失敗寫入 state，由最終回答節點說明

## 例 3：Dify 雙路影片 → `gba_dual_langgraph`

**來源**：UAS ∥ Gemma Video Adapter → 視覺優先搜尋詞 → SearXNG → 整合回答；無影片走文字路

**目標拓撲**：

```text
START → start_input → check_video
  ├─ 有影片：predict_video ∥ analyze_video → … → video_answer → END
  └─ 無影片：build_text_query → search → … → text_answer → END
```

**遷移重點**：

- 平行邊：`add_edge(["format_prediction","format_video_analysis"], "build_video_query")`
- `api.py` 支援 `/v1/files` + chat `files[]`
- LiteLLM 相容：模型名去 `openai/` 前綴

## 例 4：Generic YAML（最小）

輸入：

```yaml
name: hello-rag
nodes:
  - {id: start, type: start, title: Start}
  - {id: retrieve, type: knowledge-retrieval, title: Retrieve}
  - {id: answer, type: llm, title: Answer}
edges:
  - {source: start, target: retrieve}
  - {source: retrieve, target: answer}
```

預期專案節點：`normalize_input`（可選）→ `retrieve` → `answer`；加上完整 `api.py`。

## 命名建議

| DSL title | 建議模組／節點名 |
|---|---|
| 問題分類 | `classify` |
| 知識檢索 | `retrieve` |
| 條件分支 | `route_*` 函式 |
| LLM 回答 | `answer` / `llm_answer` |
| HTTP 呼叫 | 依服務：`predict`、`search` |
