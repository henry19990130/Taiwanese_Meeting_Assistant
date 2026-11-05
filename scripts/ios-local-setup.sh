#!/bin/bash
# iOS 本地 ASR 模型下載與準備腳本
# 用於下載 WhisperKit 相容的 Core ML 模型

set -e

# 顏色輸出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
IOS_APP_DIR="$PROJECT_ROOT/ios/App"
MODEL_DIR="$IOS_APP_DIR/Models"
WHISPERKIT_MODELS_DIR="$HOME/Library/Caches/WhisperKitModels"

# 預設模型 (WhisperKit 官方推薦: large-v3-v20240930_626MB)
DEFAULT_MODEL="large-v3-v20240930_626MB"
DEFAULT_QUANTIZATION="q4_k"

# 解析參數
MODEL_SIZE="${1:-$DEFAULT_MODEL}"
QUANTIZATION="${2:-$DEFAULT_QUANTIZATION}"

# 將使用者友善的模型名稱對應到 HuggingFace Repo 內的實際目錄名稱
# WhisperKit 在 argmaxinc/whisperkit-coreml 中的目錄命名規則
# 參考: https://huggingface.co/argmaxinc/whisperkit-coreml
case "$MODEL_SIZE" in
    "small"|"small.en")
        REPO_MODEL_DIR="openai_whisper-${MODEL_SIZE}"
        ;;
    "base"|"base.en")
        REPO_MODEL_DIR="openai_whisper-${MODEL_SIZE}"
        ;;
    "tiny"|"tiny.en")
        REPO_MODEL_DIR="openai_whisper-${MODEL_SIZE}"
        ;;
    "large-v3-v20240930_626MB"|"large-v3-v20240930_turbo")
        REPO_MODEL_DIR="openai_whisper-${MODEL_SIZE}"
        ;;
    "distil-large-v3"|"distil-large-v3_turbo")
        REPO_MODEL_DIR="distil-whisper_${MODEL_SIZE}"
        ;;
    *)
        # 預設嘗試 openai_whisper- 前綴
        REPO_MODEL_DIR="openai_whisper-${MODEL_SIZE}"
        ;;
esac

echo -e "${BLUE}=== MeetSum iOS 本地 ASR 模型準備腳本 ===${NC}"
echo -e "${BLUE}模型: ${MODEL_SIZE} (${QUANTIZATION})${NC}"
echo -e "${BLUE}Repo 目錄: ${REPO_MODEL_DIR}${NC}"
echo -e "${BLUE}目標目錄: ${MODEL_DIR}${NC}"
echo ""

# 檢查必要工具
check_tool() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}錯誤: 找不到 $1，請先安裝${NC}"
        exit 1
    fi
}

echo -e "${YELLOW}檢查必要工具...${NC}"
check_tool "git"
check_tool "curl"

# 檢查 hf (新版 huggingface_hub CLI，推薦)
if command -v hf &> /dev/null; then
    HAS_HF_CLI=true
    echo -e "${GREEN}✓ hf CLI 已安裝${NC}"
else
    HAS_HF_CLI=false
    echo -e "${YELLOW}⚠ hf CLI 未安裝，將使用 git 下載${NC}"
    echo -e "${YELLOW}  建議安裝: pip install --upgrade huggingface_hub${NC}"
fi

# 建立模型目錄
mkdir -p "$MODEL_DIR"
mkdir -p "$WHISPERKIT_MODELS_DIR"

MODEL_NAME="${MODEL_SIZE}_${QUANTIZATION}"
MODEL_PATH="$MODEL_DIR/$MODEL_NAME"

# 檢查模型是否已存在
if [ -d "$MODEL_PATH" ] && [ -f "$MODEL_PATH/config.json" ]; then
    echo -e "${GREEN}✓ 模型已存在: $MODEL_PATH${NC}"
    echo -e "${GREEN}  若要重新下載，請先刪除此目錄${NC}"
    exit 0
fi

echo -e "${YELLOW}開始下載模型: ${MODEL_NAME}${NC}"

# 下載方式 1: 使用 hf (新版 huggingface_hub CLI，推薦)
if [ "$HAS_HF_CLI" = true ]; then
    echo -e "${BLUE}使用 hf 下載...${NC}"

    # WhisperKit 模型在 argmaxinc/whisperkit-coreml
    hf download argmaxinc/whisperkit-coreml \
        --include "${REPO_MODEL_DIR}/*" \
        --local-dir "$WHISPERKIT_MODELS_DIR/whisperkit-${MODEL_SIZE}"

    # 複製到 App 目錄 (Repo 內的目錄名稱可能不同於使用者輸入的模型名稱)
    DOWNLOADED_MODEL_DIR="$WHISPERKIT_MODELS_DIR/whisperkit-${MODEL_SIZE}/${REPO_MODEL_DIR}"

    if [ -d "$DOWNLOADED_MODEL_DIR" ]; then
        cp -R "$DOWNLOADED_MODEL_DIR" "$MODEL_PATH"
        echo -e "${GREEN}✓ 模型下載並複製完成${NC}"
    else
        echo -e "${RED}錯誤: 找不到下載的模型目錄: $DOWNLOADED_MODEL_DIR${NC}"
        echo -e "${YELLOW}實際下載內容:${NC}"
        ls -la "$WHISPERKIT_MODELS_DIR/whisperkit-${MODEL_SIZE}/" 2>/dev/null || echo "目錄不存在"
        exit 1
    fi
else
    # 下載方式 2: 使用 git clone (較慢但不需要額外依賴)
    echo -e "${BLUE}使用 git clone 下載 (較慢)...${NC}"

    TEMP_DIR=$(mktemp -d)
    cd "$TEMP_DIR"

    # 只 clone 特定模型目錄 (使用 sparse checkout)
    git init -q
    git remote add origin https://huggingface.co/argmaxinc/whisperkit-coreml
    git config core.sparseCheckout true
    echo "${REPO_MODEL_DIR}/*" > .git/info/sparse-checkout
    git pull --depth=1 origin main -q

    if [ -d "${REPO_MODEL_DIR}" ]; then
        cp -R "${REPO_MODEL_DIR}" "$MODEL_PATH"
        echo -e "${GREEN}✓ 模型下載並複製完成${NC}"
    else
        echo -e "${RED}錯誤: git clone 失敗或找不到模型${NC}"
        rm -rf "$TEMP_DIR"
        exit 1
    fi

    rm -rf "$TEMP_DIR"
fi

# 驗證模型完整性
echo -e "${YELLOW}驗證模型完整性...${NC}"

# WhisperKit Core ML 模型結構: config.json + *.mlmodelc 目錄
# 注意: tokenizer 可能內嵌在模型中，不一定有獨立的 tokenizer.json
REQUIRED_FILES=("config.json")
for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$MODEL_PATH/$file" ]; then
        echo -e "${RED}錯誤: 缺少必要檔案: $file${NC}"
        exit 1
    fi
done

# 檢查是否有 .mlmodelc 目錄 (Core ML 編譯後模型) - 至少需要 AudioEncoder 和 TextDecoder
MLMODEL_COUNT=$(ls -1 "$MODEL_PATH"/*.mlmodelc 2>/dev/null | wc -l)
if [ "$MLMODEL_COUNT" -lt 2 ]; then
    echo -e "${RED}錯誤: Core ML 模型目錄不足 (*.mlmodelc)，找到 $MLMODEL_COUNT 個，至少需要 2 個 (AudioEncoder, TextDecoder)${NC}"
    exit 1
fi

echo -e "${GREEN}✓ 所有必要檔案存在 (Core ML 模型: $MLMODEL_COUNT 個)${NC}"

# 顯示模型資訊
MODEL_SIZE_MB=$(du -sm "$MODEL_PATH" | cut -f1)
echo -e "${GREEN}✓ 模型準備完成！${NC}"
echo -e "${BLUE}模型路徑: $MODEL_PATH${NC}"
echo -e "${BLUE}模型大小: ~${MODEL_SIZE_MB} MB${NC}"

# 如果是 large-v3-turbo，也建議下載 small 作為備選
if [[ "$MODEL_SIZE" == *"large"* ]] && [ ! -d "$MODEL_DIR/small_q4_k" ]; then
    echo -e "${YELLOW}建議同時下載 small 模型作為低記憶體裝置備選${NC}"
    read -p "是否下載 small 模型? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        "$0" small q4_k
    fi
fi

echo -e "${GREEN}=== 完成 ===${NC}"