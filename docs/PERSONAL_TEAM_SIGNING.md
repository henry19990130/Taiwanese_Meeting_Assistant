# Personal Team 簽名指南（真機 iOS 安裝）

適用情況：用**免費 Apple ID**（Personal Team）把 `MeetSum-PersonalTeam.ipa` 安裝到**自己的 iPhone**。

> ⚠️ 重要限制
> - Personal Team 只能做 **Development 簽名**，不能 Ad Hoc／App Store 分發
> - 描述檔 **7 天後失效**，到期需重新執行簽名 workflow
> - 只有描述檔內**已註冊 UDID 的裝置**能安裝
> - 其他人請使用無簽名 `MeetSum-PlayCover.ipa` 搭配 Sideloadly／AltStore 自行重簽

## 流程總覽

1. 在 Mac 上用 Xcode 產生 Personal Team 憑證與描述檔
2. 匯出 `.p12` 與 `.mobileprovision`，轉成 base64
3. 加入 GitHub Secrets
4. 到 Actions 跑 `Build Signed IPA (Personal Team)`，IPA 會自動附加到指定 release

## 1. 建立 Personal Team 憑證與描述檔

> 需在能正常建置 Xcode 專案的 Mac 上操作。

1. Xcode → Settings → Accounts → `+` → 登入 Apple ID
2. 開啟 `ios/App/App.xcodeproj`，選 `App` target → Signing & Capabilities：
   - 勾選 **Automatically manage signing**
   - Team 選 **你的名字 (Personal Team)**
   - Bundle Identifier 填 `com.meetsum.app`
     - 若顯示已被其他團隊註冊，改成自己的（例：`com.<你的名字>.meetsum`），並記下新 ID
3. 用 USB 連接 iPhone，選該裝置按 **Run** 一次
   - 這會註冊裝置 UDID 並產生 development provisioning profile
4. iPhone：設定 → 一般 → VPN 與裝置管理 → 信任你的開發者憑證

## 2. 找到並確認描述檔

```bash
ls -lt ~/Library/MobileDevice/Provisioning\ Profiles/ | head -5
```

找最新的，確認內容：

```bash
security cms -D -i ~/Library/MobileDevice/Provisioning\ Profiles/<UUID>.mobileprovision > /tmp/profile.plist
plutil -p /tmp/profile.plist | grep -E '"Name"|TeamIdentifier|application-identifier|ProvisionedDevices'
```

確認：
- `Name`（workflow 用 `PROVISIONING_PROFILE_SPECIFIER` 配對）
- `TeamIdentifier`（即 Team ID，10 碼）
- `application-identifier` 尾端 Bundle ID 與你填的一致
- `ProvisionedDevices` 包含你的 iPhone UDID

## 3. 匯出 Apple Development 憑證（.p12）

1. Keychain Access → login 鑰匙圈 → 搜尋 `Apple Development`
2. 找到 `Apple Development: 你的名字 (TEAMID)`，確認左側有私人金鑰
   - 沒有的話：Xcode → Settings → Accounts → Manage Certificates → `+` → Apple Development
3. 右鍵 → Export → 存成 `PersonalTeam.p12`，自訂一組密碼（用於 `IOS_CERT_PASSWORD`）

## 4. 轉 base64 並加入 GitHub Secrets

```bash
base64 -i PersonalTeam.p12 | pbcopy
base64 -i ~/Library/MobileDevice/Provisioning\ Profiles/<UUID>.mobileprovision | pbcopy
```

Repo → Settings → Secrets and variables → Actions → New repository secret：

| Secret | 內容 |
|---|---|
| `IOS_CERT_P12_BASE64` | `.p12` 的 base64 |
| `IOS_CERT_PASSWORD` | 匯出 `.p12` 時設定的密碼 |
| `IOS_PROVISIONING_PROFILE_BASE64` | `.mobileprovision` 的 base64 |
| `IOS_TEAM_ID` | 10 碼 Team ID |
| `IOS_BUNDLE_ID` | 選填，預設 `com.meetsum.app` |
| `KEYCHAIN_PASSWORD` | 選填，CI 臨時 keychain 的任意密碼 |

**不要把任何憑證內容或密碼貼到 issue／PR／對話中。**

## 5. 執行簽名 build

GitHub → Actions → `Build Signed IPA (Personal Team)` → Run workflow：
- `release_tag`：要附加 IPA 的 release（預設 `v1.1.0`）
- `bundle_id`：預設 `com.meetsum.app`
- 完成後 `MeetSum-PersonalTeam.ipa` 會出現在該 release 的資產列表

## 6. 安裝到 iPhone

- 用 AirDrop／Finder 把 IPA 拖到 iPhone 安裝，或用 Apple Configurator
- 首次啟動若顯示「不受信任的開發者」：設定 → 一般 → VPN 與裝置管理 → 信任憑證

## 7. 到期更新（7 天後）

重跑第 2 步確認描述檔未變 → 直接重跑第 5 步 workflow 即可。
若描述檔已過期無法使用，回到 Xcode 重新 Run 一次讓它更新，再匯出新的 `.mobileprovision`。

## 本機簽名（備用）

在有 Xcode 憑證的 Mac 上也可以直接跑：

```bash
./scripts/ios-personal-sign.sh --team-id <TEAM_ID> --bundle-id com.meetsum.app
```

## 常見問題

| 問題 | 處理 |
|---|---|
| `com.meetsum.app` 已被註冊 | Bundle ID 改自己的（例 `com.<名字>.meetsum`），Xcode 重新 Run 產生新描述檔，更新 `IOS_BUNDLE_ID` 與 `IOS_PROVISIONING_PROFILE_BASE64`，重跑 workflow |
| `No profiles for 'xxx' were found` | 描述檔名稱與 `Name` 不符或未安裝；確認 secret 是最新描述檔 |
| `device is not registered` | 裝置 UDID 不在描述檔內；USB 連 iPhone 在 Xcode 重新 Run 一次 |
| 憑證匯入後仍找不到 identity | 確認 `.p12` 密碼正確、keychain 已 unlock、有跑 `set-key-partition-list` |
