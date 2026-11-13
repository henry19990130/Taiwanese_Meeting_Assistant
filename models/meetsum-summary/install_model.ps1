# 覓聲：把微調版重點模型 meetsum-summary 放進專案並匯入 Ollama
# 用法（在專案根目錄的 PowerShell）：
#   powershell -ExecutionPolicy Bypass -File models\meetsum-summary\install_model.ps1
# 參數：
#   -Source   GGUF 來源（預設：雲端硬碟 G:\我的雲端硬碟\MeetSum_finetune\ollama_summary）
#   -SkipHash 不檢查 SHA256（檢查 16.8GB 約需 1–3 分鐘）
param(
  [string]$Source = 'G:\我的雲端硬碟\MeetSum_finetune\ollama_summary',
  [switch]$SkipHash
)
$ErrorActionPreference = 'Stop'
$here   = $PSScriptRoot
$name   = 'meetsum-summary'
$file   = 'meetsum-summary-Q4_K_M.gguf'
$sha256 = 'aa5f9ac344309b52e49d27a667625a0c46bf775ea3bd52050170462406b5792a'
$gguf   = Join-Path $here $file

Write-Host "==== [1/3] 模型檔 $file ===="
if (Test-Path $gguf) {
  Write-Host "   已在專案內：$gguf"
} elseif (Test-Path (Join-Path $Source $file)) {
  Write-Host "   從 $Source 複製（16.8GB，雲端硬碟要先下載，請耐心等候）…"
  robocopy $Source $here $file /J /R:2 /W:5 | Out-Host
  if ($LASTEXITCODE -ge 8) { throw "複製失敗（robocopy 代碼 $LASTEXITCODE）" }
} else {
  throw "找不到模型檔。請把 $file 放到 $here，或用 -Source 指定所在資料夾。"
}

if (-not $SkipHash) {
  Write-Host "==== [2/3] 檢查檔案完整性（SHA256）===="
  $h = (Get-FileHash $gguf -Algorithm SHA256).Hash.ToLower()
  if ($h -ne $sha256) { throw "SHA256 不符，檔案可能沒複製完整：$h" }
  Write-Host "   正確"
} else {
  Write-Host "==== [2/3] 略過 SHA256 檢查 ===="
}

Write-Host "==== [3/3] 匯入 Ollama 為 $name ===="
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  Write-Host "   模型檔已放進專案，但這台電腦沒有安裝 Ollama（https://ollama.com/download）。"
  Write-Host "   裝好後再執行一次這個腳本即可完成匯入。"
  exit 0
}
Push-Location $here
try {
  ollama create $name -f Modelfile
  if ($LASTEXITCODE -ne 0) { throw "ollama create 失敗" }
} finally { Pop-Location }
ollama list
Write-Host ""
Write-Host "完成。.env 設定 SUMMARY_MODEL=$name、SUMMARY_THINK=false，重點摘要就會改用微調版。"
