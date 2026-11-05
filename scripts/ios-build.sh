#!/usr/bin/env bash
# iOS IPA 建置腳本
# 用法: ./scripts/ios-build.sh [--scheme Scheme名稱] [--configuration Debug|Release] [--output-dir 路徑]

set -euo pipefail

# 顏色輸出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 專案根目錄
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
IOS_DIR="$PROJECT_ROOT/ios/App"
BUILD_DIR="$IOS_DIR/build"
IPA_DIR="$BUILD_DIR/ipa"

# 預設參數
SCHEME="App"
CONFIGURATION="Release"
OUTPUT_DIR="$IPA_DIR"

# 解析參數
while [[ $# -gt 0 ]]; do
    case $1 in
        --scheme)
            SCHEME="$2"
            shift 2
            ;;
        --configuration)
            CONFIGURATION="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -h|--help)
            echo "用法: $0 [選項]"
            echo "選項:"
            echo "  --scheme <name>         Xcode Scheme 名稱 (預設: App)"
            echo "  --configuration <name>  建置配置 Debug|Release (預設: Release)"
            echo "  --output-dir <path>     IPA 輸出目錄 (預設: ios/App/build/ipa)"
            echo "  -h, --help              顯示此說明"
            exit 0
            ;;
        *)
            echo -e "${RED}未知參數: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  覓聲 MeetSum iOS IPA 建置腳本${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "專案根目錄: ${YELLOW}$PROJECT_ROOT${NC}"
echo -e "前端目錄: ${YELLOW}$FRONTEND_DIR${NC}"
echo -e "iOS 專案目錄: ${YELLOW}$IOS_DIR${NC}"
echo -e "Scheme: ${YELLOW}$SCHEME${NC}"
echo -e "Configuration: ${YELLOW}$CONFIGURATION${NC}"
echo -e "輸出目錄: ${YELLOW}$OUTPUT_DIR${NC}"
echo ""

# 檢查必要工具
check_tool() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}錯誤: 找不到 $1，請先安裝 Xcode Command Line Tools${NC}"
        exit 1
    fi
}

echo -e "${BLUE}[1/6] 檢查建置環境...${NC}"
check_tool xcodebuild
check_tool xcrun
check_tool npx

# 檢查是否在 macOS 上
if [[ "$(uname)" != "Darwin" ]]; then
    echo -e "${RED}錯誤: 此腳本只能在 macOS 上執行${NC}"
    exit 1
fi

echo -e "${GREEN}✓ 建置環境檢查通過${NC}"
echo ""

# 步驟 1: 同步 Capacitor
echo -e "${BLUE}[2/6] 同步 Capacitor 專案...${NC}"
cd "$FRONTEND_DIR"
npx cap sync ios
echo -e "${GREEN}✓ Capacitor 同步完成${NC}"
echo ""

# 步驟 2: 更新 CocoaPods (如果有 Podfile)
if [[ -f "$IOS_DIR/Podfile" ]]; then
    echo -e "${BLUE}[3/6] 更新 CocoaPods 依賴...${NC}"
    cd "$IOS_DIR"
    if command -v pod &> /dev/null; then
        pod install --repo-update
        echo -e "${GREEN}✓ CocoaPods 更新完成${NC}"
    else
        echo -e "${YELLOW}⚠ 找不到 pod 指令，跳過 CocoaPods 更新 (請確認已安裝 CocoaPods)${NC}"
    fi
    echo ""
else
    echo -e "${BLUE}[3/6] 無 Podfile，跳過 CocoaPods 步驟${NC}"
    echo ""
fi

# 步驟 3: 建置 Archive
echo -e "${BLUE}[4/6] 建置 Xcode Archive...${NC}"
cd "$IOS_DIR"

# 清理舊建置
xcodebuild -workspace App.xcworkspace -scheme "$SCHEME" -configuration "$CONFIGURATION" clean

# 建置 Archive
ARCHIVE_PATH="$BUILD_DIR/App.xcarchive"
xcodebuild -workspace App.xcworkspace \
    -scheme "$SCHEME" \
    -configuration "$CONFIGURATION" \
    -destination "generic/platform=iOS" \
    -archivePath "$ARCHIVE_PATH" \
    -quiet \
    archive

if [[ ! -d "$ARCHIVE_PATH" ]]; then
    echo -e "${RED}錯誤: Archive 建置失敗${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Archive 建置成功: $ARCHIVE_PATH${NC}"
echo ""

# 步驟 4: 匯出 IPA
echo -e "${BLUE}[5/6] 匯出 IPA...${NC}"

# 建立 ExportOptions.plist (如果不存在)
EXPORT_OPTIONS_PLIST="$IOS_DIR/ExportOptions.plist"
if [[ ! -f "$EXPORT_OPTIONS_PLIST" ]]; then
    echo -e "${YELLOW}建立預設 ExportOptions.plist...${NC}"
    cat > "$EXPORT_OPTIONS_PLIST" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>method</key>
    <string>development</string>
    <key>teamID</key>
    <string>$(DEVELOPMENT_TEAM)</string>
    <key>signingStyle</key>
    <string>automatic</string>
    <key>stripSwiftSymbols</key>
    <true/>
    <key>uploadBitcode</key>
    <false/>
    <key>uploadSymbols</key>
    <true/>
    <key>compileBitcode</key>
    <false/>
</dict>
</plist>
EOF
    echo -e "${GREEN}✓ 已建立 ExportOptions.plist (開發部署模式)${NC}"
    echo -e "${YELLOW}注意: 請根據需要修改 ExportOptions.plist (方法: development/ad-hoc/app-store/enterprise)${NC}"
fi

# 匯出 IPA
xcodebuild -exportArchive \
    -archivePath "$ARCHIVE_PATH" \
    -exportPath "$OUTPUT_DIR" \
    -exportOptionsPlist "$EXPORT_OPTIONS_PLIST" \
    -quiet

# 尋找產生的 IPA
IPA_FILE=$(find "$OUTPUT_DIR" -name "*.ipa" -type f | head -n 1)

if [[ -z "$IPA_FILE" ]]; then
    echo -e "${RED}錯誤: 找不到產生的 IPA 檔案${NC}"
    exit 1
fi

echo -e "${GREEN}✓ IPA 匯出成功${NC}"
echo ""

# 步驟 5: 顯示結果
echo -e "${BLUE}[6/6] 建置完成！${NC}"
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  IPA 已成功產生${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "IPA 路徑: ${YELLOW}$IPA_FILE${NC}"
echo -e "檔案大小: ${YELLOW}$(du -h "$IPA_FILE" | cut -f1)${NC}"
echo ""

# 顯示安裝指引
echo -e "${BLUE}安裝方式:${NC}"
echo -e "  1. 透過 Xcode: 開啟 Window → Devices and Simulators → 拖曳 IPA 安裝"
echo -e "  2. 透過 Apple Configurator 2"
echo -e "  3. 透過 TestFlight (需上傳至 App Store Connect)"
echo -e "  4. 透過第三方工具 (如 iMazing、AltStore)"
echo ""

# 顯示後續步驟建議
echo -e "${BLUE}後續建議:${NC}"
echo -e "  - 修改 ExportOptions.plist 的 method 為 ad-hoc/app-store 以對應不同部署需求"
echo -e "  - 設定 DEVELOPMENT_TEAM 環境變數或在 Xcode 中設定 Team"
echo -e "  - 使用 fastlane match 管理憑證與 Provisioning Profile (生產環境建議)"
echo ""

exit 0