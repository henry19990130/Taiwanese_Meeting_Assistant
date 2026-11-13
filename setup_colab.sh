#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
mkdir -p logs

[ -f .env ] || cp .env.example .env
# 去掉 Windows 換行的 \r，否則每個值尾巴都會多一個看不見的字元
set -a; source <(tr -d '\r' < .env); set +a

DB_USER="${DB_USER:-meeting}"
DB_NAME="${DB_NAME:-meeting_assistant}"
if [ -z "${DB_PASSWORD:-}" ]; then
  echo "必須在 .env 設定 DB_PASSWORD"
  exit 1
fi
LLM_MODEL="${LLM_MODEL:-qwen3.8:27b}"
ASR_ENGINE="${ASR_ENGINE:-hf}"

step() { echo; echo "==== [$1/6] $2 ===="; }

step 1 "安裝系統套件 (ffmpeg / PostgreSQL)"
export DEBIAN_FRONTEND=noninteractive
disable_r_sources() {
  for f in /etc/apt/sources.list.d/*; do
    [ -f "$f" ] || continue
    case "$f" in *.disabled) continue ;; esac
    if grep -qiE "r-project|r2u|cran" "$f"; then
      mv "$f" "$f.disabled" && echo "   已停用與本專案無關的套件來源：$(basename "$f")"
    fi
  done
  [ -f /etc/apt/sources.list ] && sed -i -E '/r-project|r2u|cran/s/^deb/# deb/' /etc/apt/sources.list
}
if ! apt-get update -qq > logs/apt_update.log 2>&1; then
  echo "   [警告] 部分套件來源更新失敗（通常是 Colab 內建的 R 來源），停用後重試…"
  disable_r_sources
  apt-get update -qq >> logs/apt_update.log 2>&1 \
    || echo "   [警告] 仍有來源失敗，略過並繼續安裝（詳見 logs/apt_update.log）"
fi
if ! apt-get install -y -qq ffmpeg postgresql postgresql-contrib zstd pciutils lshw > logs/apt.log 2>&1; then
  echo "   [錯誤] 系統套件安裝失敗，log 最後 20 行："
  tail -n 20 logs/apt.log
  exit 1
fi
echo "完成"

step 2 "安裝 Python 套件"
pip install -q -r backend/requirements.txt 2>&1 | tail -n 5
echo "完成"

step 3 "啟動 PostgreSQL 並建立資料表"
service postgresql start
for i in $(seq 1 20); do
  runuser -u postgres -- pg_isready -q && break
  sleep 1
done

psql_admin() { runuser -u postgres -- psql -v ON_ERROR_STOP=1 -tAc "$1"; }

esc_pass=$(printf '%s' "$DB_PASSWORD" | sed "s/'/''/g")
if [ "$(psql_admin "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'")" != "1" ]; then
  psql_admin "CREATE ROLE ${DB_USER} LOGIN PASSWORD '${esc_pass}';"
else
  psql_admin "ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${esc_pass}';"
fi
if [ "$(psql_admin "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'")" != "1" ]; then
  psql_admin "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
fi
PGPASSWORD="$DB_PASSWORD" psql -q -h localhost -U "$DB_USER" -d "$DB_NAME" \
  -v ON_ERROR_STOP=1 -f database/schema.sql
if [ -n "${DEMO_PASSWORD:-}" ]; then
  python scripts/create_user.py "${DEMO_USERNAME:-demo}" --password "$DEMO_PASSWORD" --reset
else
  echo "沒有 DEMO_PASSWORD，略過示範帳號"
fi
echo "完成：資料庫 ${DB_NAME}"

step 4 "安裝 Ollama 並下載 ${LLM_MODEL}"
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh > logs/ollama_install.log 2>&1
fi

if ! curl -sf http://127.0.0.1:11434/api/version >/dev/null; then
  # 省顯示卡記憶體：flash attention＋8 位元上下文暫存；一次只放一個語言模型；常駐給小幫手用
  OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 OLLAMA_MAX_LOADED_MODELS=1 \
  OLLAMA_KEEP_ALIVE=-1 nohup ollama serve > logs/ollama.log 2>&1 &
  for i in $(seq 1 30); do
    curl -sf http://127.0.0.1:11434/api/version >/dev/null && break
    sleep 1
  done
fi
curl -sf http://127.0.0.1:11434/api/version >/dev/null \
  || { echo "Ollama 啟動失敗，請看 logs/ollama.log"; exit 1; }

echo "下載中（已下載過會很快略過），進度記錄在 logs/ollama_pull.log …"
if ! ollama pull "$LLM_MODEL" > logs/ollama_pull.log 2>&1; then
  echo "❌ 下載 ${LLM_MODEL} 失敗，log 最後幾行："
  tail -c 1500 logs/ollama_pull.log | tr '\r' '\n' | tail -n 15
  exit 1
fi
echo "完成"

# 重點摘要的微調版（SUMMARY_MODEL，預設 meetsum-summary）：
# 先找專案內的 models/meetsum-summary，沒有模型檔才找雲端硬碟；
# 已建立過就略過；找不到檔案或建立失敗都不會中斷安裝，重點會自動改用 ${LLM_MODEL}
SUMMARY_MODEL="${SUMMARY_MODEL-meetsum-summary}"
if [ -z "${SUMMARY_MODEL_DIR:-}" ] || ! ls "${SUMMARY_MODEL_DIR}"/*.gguf >/dev/null 2>&1; then
  if ls "$PROJECT_DIR/models/meetsum-summary"/*.gguf >/dev/null 2>&1; then
    SUMMARY_MODEL_DIR="$PROJECT_DIR/models/meetsum-summary"
  else
    SUMMARY_MODEL_DIR="${SUMMARY_MODEL_DIR:-/content/drive/MyDrive/MeetSum_finetune/ollama_summary}"
  fi
fi
if [ -n "$SUMMARY_MODEL" ]; then
  if ollama list | awk 'NR>1 {print $1}' | grep -qxE "${SUMMARY_MODEL}(:latest)?"; then
    echo "   重點摘要模型 ${SUMMARY_MODEL} 已存在"
  elif [ -f "${SUMMARY_MODEL_DIR}/Modelfile" ] && ls "${SUMMARY_MODEL_DIR}"/*.gguf >/dev/null 2>&1; then
    echo "   從 ${SUMMARY_MODEL_DIR} 建立重點摘要模型 ${SUMMARY_MODEL}（約 2–5 分鐘）…"
    if ( cd "$SUMMARY_MODEL_DIR" && ollama create "$SUMMARY_MODEL" -f Modelfile ) > logs/ollama_create_summary.log 2>&1; then
      echo "   完成"
    else
      echo "   ⚠️ 建立失敗（重點會改用 ${LLM_MODEL}），log 最後幾行："
      tail -c 800 logs/ollama_create_summary.log | tr '\r' '\n' | tail -n 5
    fi
  else
    echo "   ⚠️ 找不到 ${SUMMARY_MODEL_DIR} 的 Modelfile 或 .gguf（專案和雲端硬碟都沒有模型檔），重點會改用 ${LLM_MODEL}"
  fi
fi

step 5 "預先下載四個語音辨識模型 (${ASR_ENGINE})"
( cd backend && python - <<'PY'
import os
from app import config
from app.services.asr_models import LANGUAGES
from huggingface_hub import snapshot_download
from huggingface_hub.utils import GatedRepoError, HfHubHTTPError

if config.ASR_ENGINE == "fake":
    print("ASR_ENGINE=fake：不下載語音模型")
    raise SystemExit(0)
token = os.environ.get("HF_TOKEN") or None
for code, cfg in LANGUAGES.items():
    repo = cfg["model_id"]
    if os.path.isdir(repo):
        print(f"[{cfg['label']}] 使用本機模型資料夾：", repo)
        continue
    try:
        path = snapshot_download(repo, token=token,
                                 allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.tiktoken", "*.py"])
        print(f"[{cfg['label']}] {repo} → {path}")
    except (GatedRepoError, HfHubHTTPError) as exc:
        print(f"[{cfg['label']}] ⚠️ 無法下載 {repo}：{type(exc).__name__}")
        if cfg.get("gated"):
            print(f"     請到 https://huggingface.co/{repo} 登入並同意條款，"
                  "再把 Hugging Face token 存成 Colab 金鑰 HF_TOKEN（或 .env 的 HF_TOKEN）")
PY
)

step 6 "環境檢查"
cd backend
python ../scripts/test_db.py
python ../scripts/check_env.py
