#!/usr/bin/env bash
# iOS 開發環境安裝腳本
# 用於首次設定 macOS 開發環境以建置 覓聲 MeetSum iOS App

set -euo pipefail

# 顏色輸出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  覓聲 MeetSum iOS 開發環境安裝腳本${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 檢查是否在 macOS 上
if [[ "$(uname)" != "Darwin" ]]; then
    echo -e "${RED}錯誤: 此腳本只能在 macOS 上執行${NC}"
    exit 1
fi

# 檢查 Xcode
echo -e "${BLUE}[1/8] 檢查 Xcode...${NC}"
if ! command -v xcodebuild &> /dev/null; then
    echo -e "${RED}未安裝 Xcode${NC}"
    echo -e "請從 App Store 安裝 Xcode，或執行: ${YELLOW}xcode-select --install${NC}"
    exit 1
fi

XCODE_VERSION=$(xcodebuild -version | head -n 1)
echo -e "${GREEN}✓ ${XCODE_VERSION}${NC}"

# 同意 Xcode 授權
sudo xcodebuild -license accept 2>/dev/null || true

# 安裝 Xcode Command Line Tools
if ! xcode-select -p &> /dev/null; then
    echo -e "${YELLOW}安裝 Xcode Command Line Tools...${NC}"
    xcode-select --install
    echo -e "${YELLOW}請完成安裝後重新執行此腳本${NC}"
    exit 1
fi

# 檢查 Node.js
echo -e "${BLUE}[2/8] 檢查 Node.js...${NC}"
if ! command -v node &> /dev/null; then
    echo -e "${RED}未安裝 Node.js${NC}"
    echo -e "建議使用 nvm 安裝: ${YELLOW}curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash${NC}"
    echo -e "然後執行: ${YELLOW}nvm install 20${NC}"
    exit 1
fi

NODE_VERSION=$(node --version)
echo -e "${GREEN}✓ Node.js ${NODE_VERSION}${NC}"

# 檢查 npm
if ! command -v npm &> /dev/null; then
    echo -e "${RED}未安裝 npm${NC}"
    exit 1
fi

NPM_VERSION=$(npm --version)
echo -e "${GREEN}✓ npm ${NPM_VERSION}${NC}"

# 檢查 CocoaPods
echo -e "${BLUE}[3/8] 檢查 CocoaPods...${NC}"
if ! command -v pod &> /dev/null; then
    echo -e "${YELLOW}安裝 CocoaPods...${NC}"
    sudo gem install cocoapods
    pod setup
fi

POD_VERSION=$(pod --version)
echo -e "${GREEN}✓ CocoaPods ${POD_VERSION}${NC}"

# 安裝 fastlane (可選，但建議)
echo -e "${BLUE}[4/8] 檢查 fastlane...${NC}"
if ! command -v fastlane &> /dev/null; then
    echo -e "${YELLOW}安裝 fastlane (建議用於自動化部署)...${NC}"
    sudo gem install fastlane -NV
else
    FASTLANE_VERSION=$(fastlane --version | head -n 1)
    echo -e "${GREEN}✓ ${FASTLANE_VERSION}${NC}"
fi

# 安裝 carthage (可選)
echo -e "${BLUE}[5/8] 檢查 Carthage...${NC}"
if ! command -v carthage &> /dev/null; then
    echo -e "${YELLOW}安裝 Carthage (可選)...${NC}"
    if command -v brew &> /dev/null; then
        brew install carthage
    else
        echo -e "${YELLOW}未安裝 Homebrew，跳過 Carthage 安裝${NC}"
    fi
else
    CARTHAGE_VERSION=$(carthage version)
    echo -e "${GREEN}✓ Carthage ${CARTHAGE_VERSION}${NC}"
fi

# 專案依賴安裝
echo -e "${BLUE}[6/8] 安裝專案 npm 依賴...${NC}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ -f "package.json" ]]; then
    npm install
    echo -e "${GREEN}✓ npm 依賴安裝完成${NC}"
else
    echo -e "${RED}找不到 package.json${NC}"
    exit 1
fi

# Capacitor 同步
echo -e "${BLUE}[7/8] 同步 Capacitor iOS 專案...${NC}"
cd "$PROJECT_ROOT/frontend"
npx cap sync ios
echo -e "${GREEN}✓ Capacitor 同步完成${NC}"

# CocoaPods 安裝
echo -e "${BLUE}[8/8] 安裝 CocoaPods 依賴...${NC}"
cd "$PROJECT_ROOT/ios/App"
if [[ -f "Podfile" ]]; then
    pod install --repo-update
    echo -e "${GREEN}✓ CocoaPods 依賴安裝完成${NC}"
else
    echo -e "${YELLOW}無 Podfile，跳過${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  開發環境安裝完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}下一步:${NC}"
echo -e "  1. 開啟 Xcode 專案: ${YELLOW}open $PROJECT_ROOT/ios/App/App.xcworkspace${NC}"
echo -e "  2. 選擇開發團隊 (Signing & Capabilities → Team)"
echo -e "  3. 設定 Bundle Identifier (若需修改): com.meetsum.app"
echo -e "  4. 連接 iOS 實機或選擇模擬器"
echo -e "  5. 執行建置: ${YELLOW}./scripts/ios-build.sh${NC}"
echo ""
echo -e "${BLUE}常用指令:${NC}"
echo -e "  - 開啟 Xcode: ${YELLOW}open ios/App/App.xcworkspace${NC}"
echo -e "  - 同步前端變更: ${YELLOW}npx cap sync ios${NC}"
echo -e "  - 建置 IPA: ${YELLOW}./scripts/ios-build.sh${NC}"
echo -e "  - 開發模式在模擬器執行: ${YELLOW}npx cap run ios${NC}"
echo ""

# 提醒設定開發團隊
echo -e "${YELLOW}重要提醒:${NC}"
echo -e "  - 請在 Xcode 中設定 Signing & Capabilities → Team (您的 Apple Developer Team ID)"
echo -e "  - 開發部署 (development) 需要有效的開發者憑證"
echo -e "  - Ad Hoc / App Store 部署需對應的 Provisioning Profile"
echo -e "  - 建議使用 fastlane match 管理憑證: ${YELLOW}fastlane match development${NC}"
echo ""