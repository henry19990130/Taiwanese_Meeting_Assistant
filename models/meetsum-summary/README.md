# meetsum-summary：覓聲重點摘要微調版

Qwen3.8-27B 加上覓聲摘要 LoRA，合併後量化為 Q4_K_M，給 Ollama 使用。

| 檔案 | 說明 |
|---|---|
| `meetsum-summary-Q4_K_M.gguf` | 模型檔，16.8GB，**不進 git**（.gitignore 已排除） |
| `Modelfile` | Ollama 匯入設定，`FROM ./meetsum-summary-Q4_K_M.gguf` |
| `install_model.ps1` | Windows 一鍵：複製模型檔 → 檢查 SHA256 → `ollama create` |

SHA256：`aa5f9ac344309b52e49d27a667625a0c46bf775ea3bd52050170462406b5792a`

## 使用方式

**Windows（本機）**：在專案根目錄執行
```powershell
powershell -ExecutionPolicy Bypass -File models\meetsum-summary\install_model.ps1
```
沒有 `.gguf` 時會自動從 `G:\我的雲端硬碟\MeetSum_finetune\ollama_summary` 複製。

**Colab / Linux**：`setup_colab.sh` 會自動處理，先找這個資料夾的 `.gguf`，沒有才找雲端硬碟
`/content/drive/MyDrive/MeetSum_finetune/ollama_summary`。

## 後端設定（.env）

```
SUMMARY_MODEL=meetsum-summary
SUMMARY_THINK=false      # 微調版摘要請關閉思考模式
SUMMARY_LANGS=zh         # 只有中文會議用微調版，其他語言用 LLM_MODEL
```
模型不存在時，後端會自動改用 `LLM_MODEL`，不會中斷。

## 顯示卡記憶體

- 只跑重點摘要：約 19.5GB
- 語言模型常駐＋語音辨識＋助理同時運作：最高 28.2GB（A100 實測），32GB 消費級顯示卡可執行
