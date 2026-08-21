---
name: dsl-to-langgraph
description: >-
  Convert Dify workflow DSL (YAML export: kind app + workflow.graph) into a
  standalone LangGraph Python project with graph.py, state.py, nodes/,
  services.py, api.py, and OpenAI-compatible HTTP API. Primary use: Dify →
  LangGraph migration. Also accepts LangFlow/Flowise/n8n when needed.
  Use when converting Dify DSL to LangGraph, migrating Dify chat/RAG/agent
  apps, scaffolding a LangGraph service from a Dify export.
---

# Dify DSL → LangGraph

Agent-agnostic skill（Cursor / OpenClaw / GPT / Codex / 任何能讀 SKILL.md 的 agent）。

**主用途：** 把 **Dify** 匯出的工作流 DSL（`advanced-chat`／`workflow`）轉成**可獨立執行**的 LangGraph 專案（非 Dify 外掛、非 runtime 解譯器）。  
其他格式（LangFlow／Flowise／n8n）僅作次要相容。

參考風格（皆由 Dify 語意遷出）：`nchc_qa_langgraph`、`gba_langgraph`、`gba_dual_langgraph`。

### Dify 對齊原則

1. 以 `workflow.graph.nodes[].data.type` 為唯一工項來源；inventory 的 `dify_node_mapping` 決定實作／合併／忽略
2. 分支邊：`question-classifier`／`if-else` 的 `edge.sourceHandle` = class.id／case_id → `add_conditional_edges`
3. Dify 變數選擇器（如 `{{#llm.text#}}`）→ LangGraph `state` 欄位
4. Dify 內建知識庫 → **獨立 pgvector RAG**（見下方）；dataset_ids → collection 對照寫進 README
5. 節點檔必須帶 `DSL_ID`（Dify node id）方便對回畫布 DEBUG

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
├── services.py         # LLM／HTTP／KB（與 nodes 契約對齊；scaffold 必產）
├── nodes/
├── langgraph.json
├── requirements.txt 或 pyproject.toml
├── .env.example
├── README.md
└── tests/
```

預設：**語意等價遷移**（可合併 glue：template / assigner / 單純 aggregator）。

### 範圍判斷原則（必遵）

**一切「要不要做」只依 DSL 是否含對應工項／節點判斷**——inventory 有該 type／語意能力才實作；DSL 沒有就不要加。  
勿因「常見最佳實務」或臆測需求而額外加功能（例如 DSL 無引用／來源組裝，就不要強制 citation 鏈）。

## 工作流程

```text
Progress:
- [ ] 快速路徑: deploy.py 一鍵部署（跳至 §4a-快速，自動 0→4b + install + start）
---
- [ ] 0. （建議）預處理瘦身大 DSL
- [ ] 1. 辨識 DSL 並解析圖 → inventory.json
- [ ] 2. 畫出目標 LangGraph 拓撲（對照 dify_node_mapping）
- [ ] 3. 定義／確認 WorkflowState 欄位
- [ ] 4. scaffold 專案骨架
- [ ] 4b. **generate_from_inventory**（自動化填 nodes／graph／logic／prompts，含 conditional edges）
- [ ] 5. 校對 selector／merge 註解／環境變數
- [ ] 6. 確認 OpenAI-compatible api.py（上傳節點才加 /v1/files）
- [ ] 7. README、.env、測試
- [ ] 8. 對照 checklist 驗收
```

### 0. 預處理瘦身（大 DSL／Discord／長 context 建議）

貼進 agent 前先刪 UI／佈局／密鑰雜訊，只留轉換必要欄位：

```bash
python3 "$SKILL_DIR/scripts/slim_dsl.py" <dsl-file> [-o <dsl.slim.yml>]
```

- 會去掉：`position`／`selected`／`viewport`／icon／`paramSchemas` 等
- 會保留：nodes／edges、type／title、prompt／code／HTTP／KB／分支條件、模型名
- 明顯密鑰改成 `{{REDACTED}}`
- 產出可再交給 `parse_dsl.py`（結構仍可辨識）

### 1. 辨識與解析

有執行環境時：

```bash
# 大檔建議先 slim 再 parse
python3 "$SKILL_DIR/scripts/slim_dsl.py" <dsl-file> -o /tmp/flow.slim.yml
python3 "$SKILL_DIR/scripts/parse_dsl.py" /tmp/flow.slim.yml [-o inventory.json]
```

無執行環境：讀 DSL，依訊號判斷來源（詳見 [references/REFERENCE.md](references/REFERENCE.md)）：

- `kind: app` + `workflow.graph` → Dify
- `nodes` + `connections` → n8n
- LangFlow / Flowise component JSON → 對應來源
- 其餘 `nodes` + `edges`/`links` → generic

產出 inventory（Dify 時特別含）：

- `type_counts`、`has_rag`、`has_citation`、`suggested_langgraph_nodes`
- **`dify_node_mapping`**：每個 Dify 節點 → `action`（implement／merge／ignore）+ `langgraph_node` + 模板檔
- **`dify_branch_edges`**：classifier／if-else 的 `sourceHandle` → target，用來組 conditional edges

有 KB 只建議 `retrieve`；有引用／來源工項才建議 `order_citations`／`build_context`。  
實作時**嚴格以 `dify_node_mapping` 逐列落地**（見 §3b）；禁止自由發揮節點功能或形狀。

### 2. 拓撲設計

1. 合併 glue；保留 `if-else` / classifier / router 為 conditional edges
2. 平行分支 → fan-in（參考 `gba_dual_langgraph`）
3. 平台 KB（`has_rag`）→ **pgvector** + `retrieve`（勿繼續綁 Dify 內建庫）
4. 最終 `state["answer"]`；串流用 `get_stream_writer()` 發 `answer_delta`
5. 先給 mermaid／文字流程再寫碼

### 3. 狀態

`TypedDict, total=False`。最少：`query`、`history`、中間產物、`answer`（可選 `sources`）。  
節點：`def node(state) -> dict`，只回傳更新欄位。

### 3b. 節點功能結構化（硬性；禁止自由發揮）

**每個 Dify 節點的功能必須結構化實作，禁止自創抽象／合併無關邏輯／省略契約欄位。**

#### 實作協定（逐列執行 `dify_node_mapping`）

對 mapping 每一列：

| `action` | 必須做 |
|---|---|
| `implement` | 1) 複製 `template` 指定的 `.tmpl` 2) 填入 `DSL_ID`／`DSL_TITLE`／`DSL_TYPE`／`NODE_KEY=langgraph_node` 3) 只改 READ／CALL／WRITE 內的業務語意（prompt、URL、條件）4) 函式名＝`{langgraph_node}_node` 或 `route_*` |
| `merge` | **不建檔**；把語意併進 mapping 指定／相鄰的 implement 節點，並在該節點 docstring 註明「merged from \<dify_id\>」 |
| `ignore` | **不建檔**（custom-note／loop-start 等） |

禁止：

- 不照模板、自己寫一套 node 形狀
- 把多個無關 Dify type 塞進同一個「神節點」
- inventory 沒有的能力（例如無引用工項卻加 citation 鏈）
- 拿掉 META／`NodeDebug`／`DSL_ID`（高頻與 implement 節點皆須可對回 Dify 畫布）

#### 固定形狀（所有 implement）

詳見 [references/NODE_CONTRACT.md](references/NODE_CONTRACT.md)：

1. docstring：`DSL: type / title`、`DSL_ID`、讀取、寫入  
2. META 常數 + `READ → CALL → WRITE`  
3. `*_node(state) -> dict`（route 為 `-> str`）+ partial update  
4. I/O 只走 `services.py`；純邏輯可放 `logic.py`  
5. 高頻 type 必須 `NodeDebug`／`log_route`；專案含 `node_debug.py`、`run_node.py`、`state.trace`、`DEBUG_NODES`

| Dify type | 模板（不可改用別種形狀） |
|---|---|
| start | `normalize_input.py.tmpl` |
| llm | `llm.py.tmpl` |
| answer | `answer_full.py.tmpl` |
| question-classifier | `classify.py.tmpl` |
| if-else | `route.py.tmpl` |
| knowledge-retrieval | `retrieve.py.tmpl` |
| http-request / tool | `http_request.py.tmpl`／`tool.py.tmpl` |
| code（非 citation） | `code_transform.py.tmpl` |
| agent / parameter-extractor | `agent.py.tmpl`／`parameter_extractor.py.tmpl` |
| document-extractor | `document_extractor.py.tmpl` |
| loop／iteration | `iteration.py.tmpl` |
| 引用衍生（僅 has_citation） | `order_citations.py.tmpl`／`build_context.py.tmpl` |

### 4. Scaffold

```bash
python3 "$SKILL_DIR/scripts/scaffold_project.py" \
  --name <project_name> \
  --out <target_dir> \
  --model-name <api_model> \
  --port <port>
```

- `--port` **可自訂**（寫入 `API_PORT`）；省略則預設 `8000`。產出後也可在 `.env` 改 `API_PORT`。
- 中文／非 ASCII 專案名會得到 `app-<hash>` slug；**務必**用 `--model-name` 指定對外模型名。
- scaffold 的 `nodes/answer.py` 僅是骨架佔位；**下一步必須跑 `generate_from_inventory.py`（或手動依 mapping 換掉）**，不可把骨架 TODO／stub 當完成。

#### 4a-快速. 一鍵部署（deploy.py）

**最簡路徑：** 一條指令完成 parse → generate → install → start → health check：

```bash
python3 "$SKILL_DIR/scripts/deploy.py" <dsl-file> \
  --name my-bot --model-name my-bot --port 8030 --out ./my-bot
```

| 參數 | 說明 |
|---|---|
| `dsl`（positional） | Dify DSL YAML 路徑 |
| `--name` | 專案名稱（省略則取 DSL 檔名） |
| `--model-name` | API model 名（省略則同 `--name`） |
| `--port` | 服務埠（預設 8000） |
| `--out` | 輸出目錄（預設 `./<name>`） |
| `--no-start` | 只 codegen 不啟動 |
| `--slim` | 強制先瘦身（預設 >500 行自動觸發） |
| `--with-pgvector` | 加 pgvector RAG（`has_rag` 時自動帶入） |

執行後自動：slim → parse → scaffold + generate（含 conditional edges）→ venv + pip install → `.env` → compile check → uvicorn 啟動 → `/health` 輪詢。  
使用者只需事後在 `.env` 填入 LLM 連線資訊（`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`CHAT_MODEL`）再重啟。

#### 4b. 依 inventory 自動產生節點（半自動路徑）

把「逐列 mapping → 複製模板、填 META、接 has_rag／has_citation／merge 註記、組 graph」自動化：

```bash
python3 "$SKILL_DIR/scripts/generate_from_inventory.py" \
  --inventory <inventory.json> \
  --dsl <original-or-slim.yml> \
  --out <target_dir> \
  --force
```

一次做完 scaffold + generate（`--out` 須為空目錄）：

```bash
python3 "$SKILL_DIR/scripts/generate_from_inventory.py" \
  --inventory <inventory.json> --dsl <flow.yml> --out <target_dir> \
  --scaffold --name <project_name> --model-name <api_model> --port <port> \
  [--with-pgvector]
```

腳本會：

| 產出 | 說明 |
|---|---|
| `nodes/*.py` | 每個 `implement` 一檔；META／`DSL_ID` 已填 |
| `graph.py` | 依 edges 串接（含 `add_conditional_edges`）；`has_citation` 插入 citation 鏈 |
| `logic.py` | 嵌入 Dify `code` 的 `main`（需 `--dsl` 才完整） |
| `prompts.py` | 抽出 LLM system／user 模板 + 粗略 selector 替換 |
| `state.py` | 依輸出欄位擴充 |
| `GENERATE_REPORT.json` | merge 對照、警告 |

**自動處理：**

- `dify_branch_edges` → `add_conditional_edges`（question-classifier 用 `route_after_*`、if-else 用 `route_*` 雙版本函式）
- if-else route 節點產出 `_node → dict`（存 state）+ `route → str`（conditional edge 用）兩個函式
- 分支邊用 conditional edges、非分支邊用 linear edges
- `tool` / `parameter-extractor` 類型產出 stub + TODO
- DSL `environment_variables` 始終 append 到 `.env.example`

**需 Agent 校對：**

- merge 節點的整理邏輯實際呼叫（只在目標節點註明 merged from）
- `{{#nodeId.field#}}` 複雜 selector 對齊
- `/v1/files`、真實 `.env` 連線與行為驗收

無執行環境時：仍依 §3b 手動複製模板（等價於腳本行為）。

#### 4c. DSL 需要知識庫時（`has_rag=true`）→ 建 pgvector

**skill 自動依 inventory 判斷**；有 `knowledge-retrieval` 就加，沒有就不要建。  
`generate_from_inventory.py --scaffold` 在 `has_rag=true` 時會自動帶 `--with-pgvector`（亦可顯式傳入）。

```bash
python3 "$SKILL_DIR/scripts/scaffold_project.py" \
  --name <project_name> --out <target_dir> --model-name <api_model> --port <port> \
  --with-pgvector --pgvector-port 5433 --embedding-dim 1024
```

產出：`docker-compose.pgvector.yml`、`rag/schema.sql`、`rag/ingest_pgvector.py`、`services.search_knowledge`（pgvector）。

```bash
docker compose -f docker-compose.pgvector.yml up -d
# .env 設 DATABASE_URL=postgresql://rag:ragpass@127.0.0.1:5433/rag
# 與 EMBEDDING_MODEL／EMBEDDING_DIM（維度須一致）
python rag/ingest_pgvector.py --dir ./docs --collection default
```

多 Dify dataset → 多 `collection`；`retrieve` 依分類／platform 選 collection。  
引用鏈仍只看 `has_citation`，與是否用 pgvector 無關。

無腳本時：複製 `assets/templates/`（含 `rag/`）並替換 `{{PROJECT_NAME}}`、`{{API_MODEL}}`、`{{API_PORT}}`、`{{PROJECT_SLUG}}`、`{{GRAPH_EXPORT}}`、`{{PGVECTOR_PORT}}`、`{{EMBEDDING_DIM}}`。

### 5–6. 實作慣例（generate 之後）

- **優先跑完 §4b**，再人工校對，勿從零手寫節點形狀
- 一邏輯區塊 → 一個 `nodes/*.py`；`graph.py` 只組裝
- `config.py`：pydantic-settings + `.env`
- API 必備：`POST /v1/chat/completions`（含 stream）、`GET /v1/models`、`GET /health`
- 可選 Bearer `API_AUTH_KEY`；模型名容忍 `openai/<name>`
- DSL 含上傳／文件節點時才加 `/v1/files`（參考 `gba_dual_langgraph`）
- 使用者可見文案預設繁中
- **引用／參考連結**：僅當 DSL 含對應工項（來源區塊／citation code／template／文中引用格式等）時才做（見下方與 [references/REFERENCE.md](references/REFERENCE.md)）

#### RAG 引用／參考連結（skill 自動判定）

**不必人工刻意決定要不要做。** 以 `parse_dsl.py` 的 **`has_citation`** 為準：  
- `false` → 整節不做、checklist 不勾  
- `true` → 必須做下列固定順序  
僅有 `has_rag`、無引用工項 → 只做 `retrieve`。

`has_citation=true` 時採固定順序：

1. 相同來源（URL 或檔案路徑）多個 chunk → **共用同一編號**
2. 文中引用格式：優先保留 **DSL 既有公開格式**；若 DSL 無明確格式則預設 `[[n]](URL)`；編號依**文中第一次出現**從 1 起編，**連續不跳號**
3. `answer` 後處理必須依出現順序重編號；跳號／亂序要改寫成 1..N
4. 文末 `### 來源` 區塊順序 = 文中引用順序（同一份 1..N 清單）
5. 未實際用到的來源不要塞進來源區塊；完全沒引用時可 fallback 排序第一筆
6. 建議節點：`retrieve → order_citations → build_context → answer`（citation 相關 `code` 併入後兩者）

節點對映：[references/REFERENCE.md](references/REFERENCE.md)  
節點契約：[references/NODE_CONTRACT.md](references/NODE_CONTRACT.md)  
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
