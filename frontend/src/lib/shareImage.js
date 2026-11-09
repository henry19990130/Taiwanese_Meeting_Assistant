import { drawSummaryCardsImage } from "./image/summaryCardsImage.js";

// Backward-compatible export for existing integrations.
export function drawShareImage(data) {
  return drawSummaryCardsImage(data);
}

