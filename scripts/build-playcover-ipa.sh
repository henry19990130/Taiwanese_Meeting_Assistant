#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IOS_DIR="$PROJECT_ROOT/ios/App"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
BUILD_DIR="$PROJECT_ROOT/build/playcover"
ARCHIVE_PATH="$BUILD_DIR/App.xcarchive"
EXPORT_PATH="$BUILD_DIR/ipa"
CONFIGURATION="${1:-Release}"

echo -e "${GREEN}🏗️  Building MeetSum IPA for PlayCover${NC}"
echo "Configuration: $CONFIGURATION"
echo "Output: $EXPORT_PATH"

echo -e "${YELLOW}📦 Building frontend...${NC}"
cd "$FRONTEND_DIR"
npm ci
npm run build

echo -e "${YELLOW}🔄 Syncing Capacitor iOS...${NC}"
npx cap sync ios

echo -e "${YELLOW}📥 Resolving Swift Packages...${NC}"
cd "$IOS_DIR"
xcodebuild -project App.xcodeproj \
  -scheme App \
  -resolvePackageDependencies \
  -configuration "$CONFIGURATION"

echo -e "${YELLOW}🏗️  Archiving (no code signing)...${NC}"
mkdir -p "$BUILD_DIR"
xcodebuild -project App.xcodeproj \
  -scheme App \
  -configuration "$CONFIGURATION" \
  -destination 'generic/platform=iOS' \
  -archivePath "$ARCHIVE_PATH" \
  -derivedDataPath "$BUILD_DIR/DerivedData" \
  clean archive \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGN_IDENTITY="" \
  CODE_SIGNING_REQUIRED=NO \
  PROVISIONING_PROFILE="" \
  PROVISIONING_PROFILE_SPECIFIER="" \
  DEVELOPMENT_TEAM="" \
  | xcpretty || exit ${PIPESTATUS[0]}

cat > "$BUILD_DIR/ExportOptions.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>method</key>
    <string>ad-hoc</string>
    <key>stripSwiftSymbols</key>
    <true/>
    <key>compileBitcode</key>
    <false/>
    <key>signingStyle</key>
    <string>manual</string>
    <key>signingCertificate</key>
    <string>Sign to Run Locally</string>
    <key>provisioningProfiles</key>
    <dict/>
</dict>
</plist>
EOF

echo -e "${YELLOW}📤 Exporting IPA...${NC}"
xcodebuild -exportArchive \
  -archivePath "$ARCHIVE_PATH" \
  -exportPath "$EXPORT_PATH" \
  -exportOptionsPlist "$BUILD_DIR/ExportOptions.plist" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGN_IDENTITY="" \
  | xcpretty || exit ${PIPESTATUS[0]}

IPA_FILE=$(find "$EXPORT_PATH" -name "*.ipa" | head -1)
if [ -z "$IPA_FILE" ]; then
  echo -e "${RED}❌ IPA not found!${NC}"
  exit 1
fi

VERSION=$(date +"%Y%m%d-%H%M")
FINAL_NAME="MeetSum-PlayCover-v${VERSION}.ipa"
FINAL_PATH="$BUILD_DIR/$FINAL_NAME"
mv "$IPA_FILE" "$FINAL_PATH"

echo -e "${GREEN}✅ Build successful!${NC}"
echo -e "IPA: ${YELLOW}$FINAL_PATH${NC}"
echo -e "Size: ${YELLOW}$(du -h "$FINAL_PATH" | cut -f1)${NC}"
echo ""
echo -e "${GREEN}📱 安裝到 PlayCover:${NC}"
echo "  1. 開啟 PlayCover"
echo "  2. 拖入 $FINAL_PATH 或 File > Open 選擇此檔案"
echo "  3. 在 PlayCover 中雙擊啟動"