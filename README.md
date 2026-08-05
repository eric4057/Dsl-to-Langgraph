# dsl-to-langgraph

將工作流 DSL（Dify、LangFlow、Flowise、n8n，或通用 nodes／edges）轉成獨立 **LangGraph** Python 服務，並提供 **OpenAI-compatible HTTP API** 的 Agent Skill。

適用環境：Cursor、OpenClaw、ChatGPT Custom GPT、Codex／GPT Skills，以及純 CLI。

## 內含程式

| 程式 | 路徑 | 用途 |
|---|---|---|
| DSL 瘦身 | [`scripts/slim_dsl.py`](scripts/slim_dsl.py) | 去除大型匯出檔的 UI／佈局雜訊，並遮罩明顯密鑰，供後續解析或交給 agent |
| DSL 解析 | [`scripts/parse_dsl.py`](scripts/parse_dsl.py) | 產出 inventory（來源類型、節點／邊、外部依賴、建議的 LangGraph 節點） |
| 專案骨架 | [`scripts/scaffold_project.py`](scripts/scaffold_project.py) | 產生可執行的 LangGraph 專案骨架（`api.py`、`graph.py`、`state.py`、`nodes/` 等） |

輔助文件：[`SKILL.md`](SKILL.md)（agent 遷移流程）、[`references/`](references/)（對映／範例／驗收）、[`assets/templates/`](assets/templates/)（骨架模板）、[`agents/openai.yaml`](agents/openai.yaml)、[`gpt/CUSTOM_GPT_INSTRUCTIONS.md`](gpt/CUSTOM_GPT_INSTRUCTIONS.md)。

### `scripts/slim_dsl.py`

處理過大的 DSL 匯出（例如數千行 Dify YAML），降低塞入 agent／Discord 時的 context 壓力。

- **移除：** 畫布資訊（`position`、`selected`、`viewport` 等）、icon、tool `paramSchemas`，以及其他非語意 UI 欄位  
- **保留：** 圖拓撲、節點 `type`／`title`、prompt、code、HTTP／KB 設定、分支條件、模型識別  
- **遮罩：** 明顯密鑰 → `{{REDACTED}}`  
- **輸出：** 仍可供 `parse_dsl.py` 解析

```bash
python3 scripts/slim_dsl.py path/to/flow.yml -o /tmp/flow.slim.yml
python3 scripts/slim_dsl.py path/to/flow.yml -o /tmp/flow.slim.json --format json
```

讀取 YAML 需安裝：`pip install pyyaml`。

### `scripts/parse_dsl.py`

辨識 DSL 方言，並彙整圖結構，供遷移規劃使用。

```bash
python3 scripts/parse_dsl.py /tmp/flow.slim.yml -o /tmp/inventory.json
```

常見欄位：`source`、`has_rag`、`type_counts`、`external_hints`、`suggested_langgraph_nodes`。

### `scripts/scaffold_project.py`

建立最小可用的 OpenAI-compatible LangGraph 服務。專案名為非 ASCII（例如中文）時，請明確指定 `--model-name`。

```bash
python3 scripts/scaffold_project.py \
  --name "my-app" \
  --out ./my-app \
  --model-name my-app \
  --port 8030
```

骨架中的 `nodes/answer.py` 僅為佔位實作；交付前須改寫為 DSL 對應邏輯。

## CLI 完整流程

```bash
cd /path/to/dsl-to-langgraph
python3 -m venv .venv && source .venv/bin/activate
pip install pyyaml

python3 scripts/slim_dsl.py your-flow.yml -o /tmp/your-flow.slim.yml
python3 scripts/parse_dsl.py /tmp/your-flow.slim.yml -o /tmp/inventory.json
python3 scripts/scaffold_project.py \
  --name "my-app" --out ./my-app --model-name my-app --port 8030
```

接著依 [`SKILL.md`](SKILL.md)，以 inventory 為依據實作真實節點（語意等價遷移，而非逐一搬運所有 glue 節點）。

## 倉庫結構

```text
.
├── SKILL.md
├── agents/openai.yaml
├── gpt/CUSTOM_GPT_INSTRUCTIONS.md
├── references/
├── scripts/
│   ├── slim_dsl.py
│   ├── parse_dsl.py
│   └── scaffold_project.py
└── assets/templates/
```

## 安裝

### Cursor

```bash
git clone https://github.com/eric4057/dsl-to-langgraph.git
mkdir -p ~/.cursor/skills
ln -sfn "$(pwd)/dsl-to-langgraph" ~/.cursor/skills/dsl-to-langgraph
```

或直接以 Cursor 開啟本倉庫（`.cursor/skills/` 內含專案 skill 連結）。

### OpenClaw

將本目錄放置或複製至 `workspace/skills/dsl-to-langgraph`（容器內常見路徑為 `/home/node/.openclaw/workspace/skills/dsl-to-langgraph`）。請以 **`exec`** 執行腳本，勿呼叫不存在的 `dsl-to-langgraph` tool。

```bash
python3 /home/node/.openclaw/workspace/skills/dsl-to-langgraph/scripts/slim_dsl.py \
  /path/to/flow.yml -o /tmp/flow.slim.yml
```

### ChatGPT Custom GPT

1. 將 [`gpt/CUSTOM_GPT_INSTRUCTIONS.md`](gpt/CUSTOM_GPT_INSTRUCTIONS.md) 貼入 Instructions  
2. 上傳 `SKILL.md`、`references/`、`assets/templates/` 作為 Knowledge  

### Codex／OpenAI skill bundle

安裝或上傳 skill 根目錄（`SKILL.md` + `agents/` + `scripts/` + `references/` + `assets/`）。

## Agent 提示詞範例

```text
使用 dsl-to-langgraph skill。
1. slim_dsl.py → /tmp/flow.slim.yml
2. parse_dsl.py → inventory.json
3. scaffold_project.py → /tmp/my-langgraph（--model-name …）
4. 依 SKILL.md 完成語意等價遷移，含 OpenAI-compatible api.py
```

## 延伸閱讀

- [`SKILL.md`](SKILL.md) — 遷移流程  
- [`references/REFERENCE.md`](references/REFERENCE.md) — 節點對映與引用規則  
- [`references/EXAMPLES.md`](references/EXAMPLES.md)  
- [`references/CHECKLIST.md`](references/CHECKLIST.md)  

## 授權

Private／內部使用。請勿提交 DSL 匯出中的密鑰。
