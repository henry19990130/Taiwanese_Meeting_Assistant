#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
mkdir -p logs

[ -f .env ] || cp .env.example .env
set -a; source .env; set +a

DB_USER="${DB_USER:-meeting}"
DB_PASSWORD="${DB_PASSWORD:-meeting}"
DB_NAME="${DB_NAME:-meeting_assistant}"
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

if [ "$(psql_admin "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'")" != "1" ]; then
  psql_admin "CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';"
fi
if [ "$(psql_admin "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'")" != "1" ]; then
  psql_admin "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
fi
PGPASSWORD="$DB_PASSWORD" psql -q -h localhost -U "$DB_USER" -d "$DB_NAME" \
  -v ON_ERROR_STOP=1 -f database/schema.sql
python scripts/create_user.py "${DEMO_USERNAME:-demo}" --password "${DEMO_PASSWORD:-demo1234}" --reset
echo "完成：資料庫 ${DB_NAME}"

step 4 "安裝 Ollama 並下載 ${LLM_MODEL}"
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh > logs/ollama_install.log 2>&1
fi

if ! curl -sf http://127.0.0.1:11434/api/version >/dev/null; then
  OLLAMA_KEEP_ALIVE=24h nohup ollama serve > logs/ollama.log 2>&1 &
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

step 5 "預先下載 Taiwan-Tongues-ASR-CE (${ASR_ENGINE})"
( cd backend && python - <<PY
import os
from huggingface_hub import snapshot_download
from taigi_asr.config import FASTER_WHISPER_MODEL_ID, HUGGINGFACE_MODEL_ID
engine = "${ASR_ENGINE}"
repos = {"hf": [HUGGINGFACE_MODEL_ID], "fw": [FASTER_WHISPER_MODEL_ID],
         "auto": [HUGGINGFACE_MODEL_ID, FASTER_WHISPER_MODEL_ID], "fake": []}[engine]
for repo in repos:
    if os.path.isdir(repo):
        print("使用本機模型資料夾：", repo)
        continue
    path = snapshot_download(repo, allow_patterns=["*.json", "*.safetensors", "*.bin", "*.txt"])
    print("模型位置：", path)
PY
)

step 6 "環境檢查"
cd backend
python ../scripts/test_db.py
python ../scripts/check_env.py
