# 錯字校正 LoRA 微調（國語＋英文）

目標：讓 Qwen3.8-27B 更準確地抓出語音辨識造成的同音／近音錯字。
原本的 `qwen3.8:27b` 不動；微調結果是另一個 Ollama 模型 `qwen3.8-27b-typo`，評分贏過原版才接進系統。

## 怎麼跑
Colab（96 GB GPU）打開 `finetune_typo.ipynb`，從上到下執行。結果都存在雲端硬碟 `MeetSum_finetune/`，
斷線後重跑會跳過已完成的步驟、訓練從 checkpoint 接續。全程約 6–8 小時。

## 資料從哪裡來（沒有用任何大型語言模型產生答案）
| 語言 | 語料 | 授權 | 用途 |
|---|---|---|---|
| 國語 | AISHELL-4（真實會議錄音＋人工逐字稿） | Apache-2.0 | train / dev / test 會議互不重疊 |
| 英文 | AMI Meeting Corpus（sdm 單一遠距麥克風） | CC BY 4.0 | 依官方 train / validation / test 切分 |

1. 用**專案正式的 ASR**（國語 Breeze-ASR-25、英文 Qwen3-ASR-1.7B，含幻覺過濾與簡轉繁）辨識錄音。
2. 辨識結果和人工逐字稿逐字對齊，只取「同音或近音、等長、1～3 字（英文 1～3 詞）」的替換錯誤當標準答案；
   語助詞、他/她/它、的/得/地、數字寫法、英文口語縮寫等「從聲音分不出來或兩種都對」的差異一律不算。
3. 訓練集另外用規則把同音詞換進句子（jieba 詞典 + 拼音；英文用語料詞彙的發音相近詞），增加正例。測試集不注入。
4. 樣本格式和 `typo_service.py` 送給 Qwen 的完全相同（同一份 system prompt、40 段一批、前 3 段 `[context]`），
   標準答案先用正式的 `parse_reply` / `parse_reply_en` 驗證過。

## 評分
- 一筆建議算「對」= 套用後的段落和人工逐字稿一致（忽略標點、大小寫）。
- 指標：準確率、召回率、F0.5（偏重準確率，對應 prompt 的「寧可少列，不要亂列」）、
  沒有錯字的批次被亂報的比例、套用建議前後的 CER（國語）／WER（英文）。
- 最終成績用 Ollama 跑（和正式系統同一條路徑、同樣的溫度與 seed）。
- 換上微調版的條件：F0.5 提升、準確率沒有下降超過 2 個百分點、CER/WER 沒變差（`compare.py`）。

## 檔案
| 檔案 | 做什麼 |
|---|---|
| `ft_common.py` | 正規化、對齊、標準答案擷取、同音字注入、評分 |
| `build_asr_data.py` | 下載語料 → 專案 ASR 辨識 → hyp/ref 會議檔 |
| `build_sft.py` | 轉成訓練／評測樣本 |
| `eval_typo.py` | 評分（ollama / hf / gold 三種後端） |
| `train_lora.py` | LoRA 訓練（注意力、線性注意力投影、MLP；r=16） |
| `export_ollama.py` | 轉成 Ollama 模型並做冒煙測試 |
| `compare.py` | 原版 vs 微調版報告與判定 |
| `make_notebook.py` | 產生 `finetune_typo.ipynb` |
