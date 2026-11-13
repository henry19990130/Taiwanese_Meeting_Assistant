# 撰寫會議摘要（覓聲 摘要微調的標準答案）

你要為指定的會議，各寫一份 JSON 摘要。這些摘要會成為微調 Qwen 的「標準答案」，品質要高、要嚴格遵守規則。

工作目錄：`/home/claude/ft/sum`（所有指令都在這裡執行，指令前加 `PYTHONWARNINGS=ignore`）

## 規則來源
- 摘要規則與 JSON 結構：`summary_prompt_copy.py` 裡的 `SYSTEM_PROMPT`，以及 `LANGUAGE_RULES`。
  - 國語會議（lang=zh）：套用 `LANGUAGE_RULES["zh"]`，用繁體中文（台灣用語）寫。
  - 英文會議（lang=en）：套用 `LANGUAGE_RULES["en"]`，用英文寫；headline 25 個英文單字以內。
  先完整讀一次 `summary_prompt_copy.py`，每一條規則都要遵守。
- 範例（已通過驗證的一份）：`targets/20200706_L_R001S01C01.json`，照它的風格與細緻程度寫。

## 每一場會議的流程
1. 看逐字稿：`python3 sumtool.py show <會議ID> [max_segs]`（英文會議要帶 max_segs，只摘要前面那幾段）
2. 依規則寫摘要，存成 `targets/<會議ID>.json`（用 Write 工具，UTF-8，合法 JSON，結構與範例完全相同：
   headline、meeting_content{reports, discussions, decisions, action_items, next_meeting}、review_notes）
3. 驗證：`python3 sumtool.py check <會議ID> [max_segs]`，必須印出 `OK`。
   有錯就修正（最常見：quote 不是逐字稿中的「連續原文」— 請直接從 show 的輸出複製一小段，不要改字、不要省略標點）。
4. 換下一場。

## 品質要求
- quote 要短而精準（5～30 字），一定是該 segment 的連續原文；英文 quote 照抄（含大小寫、標點）。
- 每個 reports / discussions / decisions / action_items 項目至少一筆 evidence。
- 決議要有明確確認的語句；只是建議不能當決議。沒有負責人或期限要寫進 review_notes。
- 逐字稿是語音辨識結果或人工逐字稿，可能有錯字與口語，理解時依上下文判斷。
- 不要改動 `targets/` 以外的任何檔案，也不要改別人負責的會議。

完成後回報：每場會議的 ID 與是否 OK。
