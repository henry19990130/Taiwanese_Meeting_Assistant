# feat(image): Implement Meeting Summary Image Pipeline

## 功能說明

本次新增 AI 會議摘要圖片處理模組，並整合至前端會議摘要頁面，提供摘要資料轉換、重要性評分、卡片選取、資料驗證及 PNG 圖片產生功能。

## 修改內容

- 新增 `imageAdapter.js`：摘要資料格式轉換。
- 新增 `imageScoring.js`：六維度重要性評分與 P0–P3 優先級。
- 新增 `imageSelector.js`：依分數選取最多五張摘要卡片。
- 新增 `imageValidator.js`：檢查圖片資料完整性。
- 新增 `summaryCardsImage.js`：使用 Canvas 繪製會議摘要圖片。
- 修改 `shareImage.js`：保留舊有圖片函式相容性。
- 修改 `summaryView.js`：整合圖片產生與下載流程，加入按鈕狀態及錯誤處理。
- 修改 `package.json`：新增 `npm run test:image` 測試指令。
- 新增 `imagePipeline.test.js`：圖片資料處理流程測試。

## 測試方式

```bash
cd frontend
npm run test:image
npm run build
```

## 待改善項目

- 確認 P0 重點強制保留規則。
- 整合 Top 5 卡片選取結果與實際圖片繪製。
- 完善圖片資料驗證失敗時的處理方式。
- 進行完整的前端操作與圖片輸出測試。
