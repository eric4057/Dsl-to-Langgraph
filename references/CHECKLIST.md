# 交付 Checklist

> 由 `SKILL.md` 按需載入。完成遷移時逐項確認：

## 解析與設計

- [ ] 已辨識 DSL 來源（Dify / LangFlow / Flowise / n8n / generic）
- [ ] 已產出節點／邊 inventory（或同等說明）
- [ ] 已畫出目標拓撲（文字或 mermaid）
- [ ] 已標出需替代的外部依賴（KB、HTTP、tools）

## 專案結構

- [ ] `graph.py` / `state.py` / `nodes/` / `config.py` / `api.py` 齊全
- [ ]（若有外部呼叫）`services.py` 或等價封裝
- [ ] `langgraph.json` 指向 `./graph.py:graph`
- [ ] `requirements.txt` 或 `pyproject.toml`
- [ ] `.env.example`（無真實密鑰）
- [ ] `README.md`（流程、啟動、curl）
- [ ] `.gitignore` 含 `.env`、`.venv`、`__pycache__`
- [ ] 無骨架 stub／TODO 殘留在交付碼中

## 行為

- [ ] 主要分支語意與 DSL 對齊
- [ ] 條件路由有明確 route 函式
- [ ] 最終 `state["answer"]` 有值
- [ ] 串流：`answer_delta` → SSE（若需要串流）
- [ ] 錯誤／空輸入有合理 HTTP 或回答

## 引用／參考連結（RAG 時必勾）

- [ ] 節點含 `order_citations`／`build_context`（或等價合併實作）
- [ ] 相同來源共用同一編號
- [ ] 文中引用依第一次出現重編為連續 1..N（不跳號）
- [ ] 預設 `[[n]](URL)`，或已依使用者指定保留原公開格式且順序仍一致
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
