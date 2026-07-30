# 交付 Checklist

完成 DSL → LangGraph 遷移時逐項確認：

## 解析與設計

- [ ] 已辨識 DSL 來源（Dify / LangFlow / Flowise / n8n / generic）
- [ ] 已產出節點／邊 inventory（或同等說明）
- [ ] 已畫出目標拓撲（文字或 mermaid）
- [ ] 已標出需替代的外部依賴（KB、HTTP、tools）

## 專案結構

- [ ] `graph.py` / `state.py` / `nodes/` / `config.py` / `api.py` 齊全
- [ ] `langgraph.json` 指向 `./graph.py:graph`
- [ ] `requirements.txt` 或 `pyproject.toml`
- [ ] `.env.example`（無真實密鑰）
- [ ] `README.md`（流程、啟動、curl）
- [ ] `.gitignore` 含 `.env`、`.venv`、`__pycache__`

## 行為

- [ ] 主要分支語意與 DSL 對齊
- [ ] 條件路由有明確 route 函式
- [ ] 最終 `state["answer"]` 有值
- [ ] 串流：`answer_delta` → SSE（若需要串流）
- [ ] 錯誤／空輸入有合理 HTTP 或回答

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
