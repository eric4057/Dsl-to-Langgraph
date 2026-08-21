# 交付 Checklist

> 由 `SKILL.md` 按需載入。完成遷移時逐項確認。  
> **範圍原則：** 以 **Dify DSL** 工項為準；inventory 沒有就不做。  
> 實作清單以 `dify_node_mapping` 的 implement 列為準。

## 一鍵部署（deploy.py）

- [ ] `deploy.py` 產出 → 所有 `py_compile` 通過
- [ ] `graph.py` 含 `add_conditional_edges`（有分支邊時）
- [ ] 伺服器自動啟動 → `/health` 回傳 OK
- [ ] `.env` 已產出（填入 LLM 連線後 `/v1/chat/completions` 可正常回答）

## 解析與設計

- [ ] 已辨識為 Dify（或註明次要格式）
- [ ] 已產出 inventory（含 `dify_node_mapping`／`dify_branch_edges`）
- [ ] 已畫出目標拓撲（文字或 mermaid，節點旁標 Dify title／id）
- [ ] 已標出需替代的外部依賴（KB dataset_ids、HTTP、tools）
- [ ] classifier／if-else 分支已用 `sourceHandle` 對齊 conditional edges
- [ ] `has_rag=true` 時已產出／啟動 **pgvector**（compose＋schema＋`DATABASE_URL`＋ingest 或寫入介面）
- [ ] `has_rag=false` 時**未**多餘建向量庫

## 專案結構

- [ ] `graph.py` / `state.py` / `nodes/` / `config.py` / `api.py` 齊全
- [ ]（若有外部呼叫）`services.py` 或等價封裝
- [ ] `langgraph.json` 指向 `./graph.py:graph`
- [ ] `requirements.txt` 或 `pyproject.toml`
- [ ] `.env.example`（無真實密鑰）
- [ ] `README.md`（流程、啟動、curl）
- [ ] `.gitignore` 含 `.env`、`.venv`、`__pycache__`
- [ ] 無骨架 stub／TODO 殘留在交付碼中

## 節點結構化（禁止自由發揮）

- [ ] 已依 `dify_node_mapping` **逐列**處理（implement／merge／ignore）
- [ ] （建議）已跑 `scripts/generate_from_inventory.py`，或手動等價完成
- [ ] 已讀 `GENERATE_REPORT.json` 警告（分支邊／缺 --dsl 等）
- [ ] 每個 `implement` 都從對應 `.tmpl` 複製／產生，未自創形狀
- [ ] 每個 implement 檔含 META：`NODE_KEY`／`DSL_TYPE`／`DSL_TITLE`／`DSL_ID`／`READS`／`WRITES`
- [ ] 函式名對齊 mapping 的 `langgraph_node`（`*_node` 或 `route_*`）
- [ ] `merge`／`ignore` **沒有**對應空檔；merge 有在目標節點註明源 dify_id
- [ ] 外部 I/O 在 `services.py`；節點內無直接建 client／硬編碼密鑰
- [ ] 高頻節點含 `NodeDebug`／`log_route` + `READ→CALL→WRITE`
- [ ] 專案含 `node_debug.py`、`state.trace`；可用 `DEBUG_NODES`／`run_node.py`
- [ ] 無 inventory 之外的「額外神節點」

## 行為

- [ ] 主要分支語意與 DSL 對齊
- [ ] 條件路由有明確 route 函式
- [ ] 最終 `state["answer"]` 有值
- [ ] 串流：`answer_delta` → SSE（若需要串流）
- [ ] 錯誤／空輸入有合理 HTTP 或回答

## 引用／參考連結（自動判定；勿手動臆測）

> **由 skill 自行判斷，不必刻意撰寫或另開需求。**  
> 判準：`parse_dsl.py` → inventory **`has_citation`**（及 `dify_node_mapping` 是否含 citation 衍生列）。  
> - `has_citation=false` → **整節跳過，不要實作、不要勾**  
> - `has_citation=true` → 必須實作並驗收下列項目  
> （僅有 `has_rag`／`knowledge-retrieval`、無引用工項 → 只做 `retrieve`，本節仍跳過。）

**僅 `has_citation=true` 時勾選：**

- [ ] 節點含 `order_citations`／`build_context`（或等價合併實作）
- [ ] 相同來源共用同一編號
- [ ] 文中引用依第一次出現重編為連續 1..N（不跳號）
- [ ] 文中格式優先保留 DSL 既有公開格式；無則 `[[n]](URL)`
- [ ] `### 來源` 區塊順序與文中引用順序一致
- [ ] 未使用來源不出現在來源區塊
- [ ] 有針對亂序／跳號引用的單元測試（參考 `nchc_qa_langgraph`）

## API

- [ ] `POST /v1/chat/completions`（stream true/false）
- [ ] `GET /v1/models`
- [ ] `GET /health`
- [ ] 可選 Bearer `API_AUTH_KEY`
- [ ]（若有檔案）上傳與 chat 帶檔流程可用

## 品質

- [ ] 無提交密鑰
- [ ] 關鍵純函式或路由有測試
- [ ] 使用者可見文案語言符合需求（預設繁中）
