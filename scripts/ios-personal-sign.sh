#!/usr/bin/env bash
# Personal Team Development 簽名建置腳本（本機備用，適用有 Xcode 憑證的 Mac）
#
# 前置需求：
#   1. Xcode 已登入 Apple ID，且出現 Personal Team
#   2. security find-identity -p codesigning 可看到 "Apple Development" 憑證
#   3. 已產生 development provisioning profile（含你的裝置 UDID）
#
# 用法：
#   ./scripts/ios-personal-sign.sh --team-id ABCDE12345 [--bundle-id com.meetsum.app] [--device XXX]
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IOS_DIR="$PROJECT_ROOT/ios/App"
BUILD_DIR="$IOS_DIR/build"
CONFIGURATION="Release"
TEAM_ID=""
BUNDLE_ID="com.meetsum.app"
DEVICE_NAME=""

usage() {
    cat <<EOF
用法: $0 --team-id <TEAM_ID> [--bundle-id <id>] [--device <名稱>]

  --team-id <id>       Apple Team ID（10 碼，Xcode → Settings → Accounts 可查）
  --bundle-id <id>     Bundle Identifier（預設: com.meetsum.app；若已被其他團隊註冊請改自己的）
  --device <名稱>      指定連接的 iPhone 名稱（可省略）
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --team-id)      TEAM_ID="$2"; shift 2 ;;
        --bundle-id)    BUNDLE_ID="$2"; shift 2 ;;
        --device)       DEVICE_NAME="$2"; shift 2 ;;
        -h|--help)      usage ;;
        *) echo -e "${RED}未知參數: $1${NC}"; usage ;;
    esac
done

if [[ -z "$TEAM_ID" ]]; then
    echo -e "${RED}錯誤: 必須提供 --team-id${NC}"
    usage
fi

command -v xcodebuild >/dev/null || { echo -e "${RED}錯誤: 找不到 xcodebuild${NC}"; exit 1; }
security find-identity -v -p codesigning | grep "Apple Development" >/dev/null || {
    echo -e "${RED}錯誤: Keychain 沒有 Apple Development 憑證${NC}"
    echo "請先在 Xcode → Settings → Accounts → Manage Certificates 建立。"
    exit 1
}

# 1. 建置前端
echo -e "${BLUE}[1/4] 建置前端...${NC}"
cd "$PROJECT_ROOT"
VITE_API_BASE_URL="http://localhost:8000" npm run build

# 2. 同步 Capacitor
echo -e "${BLUE}[2/4] 同步 Capacitor iOS...${NC}"
npx cap sync ios

# 3. Archive（manual signing，使用描述檔自動配對）
echo -e "${BLUE}[3/4] Archive (Personal Team 簽名)...${NC}"
ARCHIVE_PATH="$BUILD_DIR/App.xcarchive"
rm -rf "$ARCHIVE_PATH"
cd "$IOS_DIR"
DEST="generic/platform=iOS"
if [[ -n "$DEVICE_NAME" ]]; then DEST="platform=iOS,name=$DEVICE_NAME"; fi

xcodebuild -project App.xcodeproj \
    -scheme App \
    -configuration "$CONFIGURATION" \
    -destination "$DEST" \
    -archivePath "$ARCHIVE_PATH" \
    archive \
    -allowProvisioningUpdates \
    CODE_SIGN_STYLE=Manual \
    CODE_SIGN_IDENTITY="Apple Development" \
    DEVELOPMENT_TEAM="$TEAM_ID" \
    PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE_ID"

# 4. 匯出 IPA（development 分發）
echo -e "${BLUE}[4/4] 匯出 IPA...${NC}"
EXPORT_DIR="$BUILD_DIR/ipa-personal"
rm -rf "$EXPORT_DIR"
cat > "$BUILD_DIR/PersonalTeamExportOptions.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>method</key>
	<string>development</string>
	<key>teamID</key>
	<string>${TEAM_ID}</string>
	<key>signingStyle</key>
	<string>manual</string>
	<key>stripSwiftSymbols</key>
	<true/>
</dict>
</plist>
EOF

xcodebuild -exportArchive \
    -archivePath "$ARCHIVE_PATH" \
    -exportOptionsPlist "$BUILD_DIR/PersonalTeamExportOptions.plist" \
    -exportPath "$EXPORT_DIR" \
    -allowProvisioningUpdates

IPA_FILE=$(find "$EXPORT_DIR" -name "*.ipa" | head -1)
if [[ -z "$IPA_FILE" ]]; then
    echo -e "${RED}錯誤: 找不到匯出的 IPA${NC}"
    exit 1
fi
cp "$IPA_FILE" "$PROJECT_ROOT/MeetSum-PersonalTeam.ipa"

echo ""
echo -e "${GREEN}✓ 完成: $PROJECT_ROOT/MeetSum-PersonalTeam.ipa${NC}"
echo -e "${YELLOW}提醒：Personal Team 描述檔 7 天後失效，且只能安裝在描述檔內已註冊的裝置。${NC}"
