---
name: dsl-to-langgraph
description: >-
  Convert workflow DSLs (Dify YAML, LangFlow/Flowise JSON, n8n graphs, or
  generic nodes+edges) into a standalone LangGraph Python project with
  graph.py, state.py, nodes/, api.py, and OpenAI-compatible HTTP API.
  Use when converting DSL to LangGraph, migrating Dify/Flowise/n8n workflows,
  scaffolding a LangGraph service, or rebuilding chat/RAG/video pipelines.
---

# DSL → LangGraph

Agent-agnostic skill（Cursor / OpenClaw / GPT / Codex / 任何能讀 SKILL.md 的 agent）。

將工作流 DSL 轉成**可獨立執行**的 LangGraph 專案（非平台外掛、非 runtime 解譯器）。

參考風格：`nchc_qa_langgraph`、`gba_langgraph`、`gba_dual_langgraph`。

## 執行環境規則

1. **`SKILL_DIR`** = 本 `SKILL.md` 所在目錄（勿寫死 Cursor 路徑）。
2. 有 shell／`exec` 時：優先跑 `scripts/`；沒有則依 `assets/templates/` 手動產出等價檔案。
3. **OpenClaw**：本 skill **不是**可呼叫的 tool 名稱；用 `exec` 跑腳本，不要呼叫不存在的 `dsl-to-langgraph` tool。
4. **GPT（無程式執行）**：依本文件 + `references/` + `assets/templates/` 直接生成完整專案碼；可把 `gpt/CUSTOM_GPT_INSTRUCTIONS.md` 貼進 Custom GPT。
5. 密鑰只進 `.env.example` 佔位，永不寫進產出 repo。

## 產出目標（固定）

```text
<project>/
├── api.py              # /v1/chat/completions、/v1/models、/health
├── graph.py
├── state.py
├── config.py
├── services.py         # 選用
├── nodes/
├── langgraph.json
├── requirements.txt 或 pyproject.toml
├── .env.example
├── README.md
└── tests/
```

預設：**語意等價遷移**（可合併 glue：template / assigner / 單純 aggregator）。

## 工作流程

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

有執行環境時：

```bash
python3 "$SKILL_DIR/scripts/parse_dsl.py" <dsl-file> [-o inventory.json]
```

無執行環境：讀 DSL，依訊號判斷來源（詳見 [references/REFERENCE.md](references/REFERENCE.md)）：

- `kind: app` + `workflow.graph` → Dify
- `nodes` + `connections` → n8n
- LangFlow / Flowise component JSON → 對應來源
- 其餘 `nodes` + `edges`/`links` → generic

產出 inventory：名稱、節點、邊、分支／平行／迴圈、外部依賴。

### 2. 拓撲設計

1. 合併 glue；保留 `if-else` / classifier / router 為 conditional edges
2. 平行分支 → fan-in（參考 `gba_dual_langgraph`）
3. 平台 KB → 獨立向量庫（常用 Qdrant）+ `retrieve`
4. 最終 `state["answer"]`；串流用 `get_stream_writer()` 發 `answer_delta`
5. 先給 mermaid／文字流程再寫碼

### 3. 狀態

`TypedDict, total=False`。最少：`query`、`history`、中間產物、`answer`（可選 `sources`）。  
節點：`def node(state) -> dict`，只回傳更新欄位。

### 4. Scaffold

```bash
python3 "$SKILL_DIR/scripts/scaffold_project.py" \
  --name <project_name> \
  --out <target_dir> \
  --model-name <api_model> \
  --port <port>
```

- 中文／非 ASCII 專案名會得到 `app-<hash>` slug；**務必**用 `--model-name` 指定對外模型名。
- scaffold 的 `nodes/answer.py` 僅是骨架佔位；**交付前必須換成 DSL 真實邏輯**，不可把骨架 TODO／stub 當完成。

無腳本時：複製 `assets/templates/` 並替換 `{{PROJECT_NAME}}`、`{{API_MODEL}}`、`{{API_PORT}}`、`{{PROJECT_SLUG}}`、`{{GRAPH_EXPORT}}`。

### 5–6. 實作慣例

- 一邏輯區塊 → 一個 `nodes/*.py`；`graph.py` 只組裝
- `config.py`：pydantic-settings + `.env`
- API 必備：`POST /v1/chat/completions`（含 stream）、`GET /v1/models`、`GET /health`
- 可選 Bearer `API_AUTH_KEY`；模型名容忍 `openai/<name>`
- 有檔案需求時加 `/v1/files`（參考 `gba_dual_langgraph`）
- 使用者可見文案預設繁中
- **有引用／參考連結的 RAG**：必須採固定順序（見下方與 [references/REFERENCE.md](references/REFERENCE.md)）

#### RAG 引用／參考連結（固定順序，必做）

當 DSL 含 knowledge-retrieval／來源區塊／citation 時：

1. 相同來源（URL 或檔案路徑）多個 chunk → **共用同一編號**
2. **預設**文中引用格式：`[[n]](URL)`；編號依**文中第一次出現**從 1 起編，**連續不跳號**  
   （若使用者指定保留原 DSL 公開引用格式，則遵從使用者；否則採用此標準）
3. `answer` 後處理必須依出現順序重編號；跳號／亂序要改寫成 1..N
4. 文末 `### 來源` 區塊順序 = 文中引用順序（同一份 1..N 清單）
5. 未實際用到的來源不要塞進來源區塊；完全沒引用時可 fallback 排序第一筆
6. 建議節點：`retrieve → order_citations → build_context → answer`（citation 相關 `code` 併入後兩者）

節點對映：[references/REFERENCE.md](references/REFERENCE.md)  
範例：[references/EXAMPLES.md](references/EXAMPLES.md)

### 7–8. 文件與驗收

README + `.env.example` + tests。完成前勾 [references/CHECKLIST.md](references/CHECKLIST.md)。

## 自由度

| 可改 | 不可擅自改 |
|---|---|
| 合併 glue、改名、拆檔 | 刪業務分支、改分類語意 |
| 換向量庫／HTTP 實作 | 拿掉 OpenAI-compatible API |
| 平行化獨立 I/O | 提交密鑰 |

無法離線重現的能力（私有 KB、付費外掛）→ README 標明並留介面，勿靜默省略。
