# MeetSum Discovery Worker

App 的**固定入口**。Colab 每次啟動都會換一組 `https://xxxx.trycloudflare.com` 臨時網址，
這個 Worker 負責保存「目前有效的網址」，App 只要記住 Worker 的網址就能自動連上。

```
App 啟動 ──GET /current──▶ Worker(KV) ──回傳──▶ { api_url: "https://discover.xxx" }
Colab 啟動 ──POST /update──▶ Worker(KV)（帶 Bearer PUSH_TOKEN）
App API  ──/api/*──▶ Worker ──代理──▶ https://xxx.trycloudflare.com
```

Worker 也直接代理後端。App 把 API base 設成 Worker 的固定網域即可，
Colab 換網址、重開都不用改 App 設定。

**為什麼要代理？** Google OAuth 只接受事先登記的 redirect URI，
trycloudflare 網址每次都不同。以 Worker 固定網域當後端後，
`https://discover.example.com/api/v1/auth/google/callback` 只需登記一次。

## 一次性部署

```bash
cd infra/discovery-worker
npm install -g wrangler          # 或 npx wrangler
wrangler login                   # 用你的 Cloudflare 帳號授權

# 1. 建立 KV
wrangler kv namespace create MEETSUM_KV
#    → 把回傳的 id 填進 wrangler.toml

# 2. 設定推送密鑰（自己產生一組長隨機字串）
wrangler secret put PUSH_TOKEN

# 3. 部署
wrangler deploy
```

部署後會得到 `https://meetsum-discovery.<你的帳號>.workers.dev`。
若要用自己的網域，取消 `wrangler.toml` 裡 `routes` 的註解並填入 `discover.<你的網域>`。

## 讓 Colab 發佈網址

在 Colab 的 **Secrets**（左側鑰匙圖示）加入：

| 名稱 | 值 |
|---|---|
| `DISCOVERY_URL` | `https://discover.<你的網域>/update`（或 workers.dev 的 `/update`） |
| `DISCOVERY_PUSH_TOKEN` | 與 Worker 的 `PUSH_TOKEN` 相同 |

`run_all.py` 的「開臨時網址」步驟成功後會自動 POST 到 `DISCOVERY_URL`。
本地開發可寫在 `.env`：

```env
DISCOVERY_URL=https://discover.example.com/update
DISCOVERY_PUSH_TOKEN=...
```

## App 端設定

建置時帶入固定入口：

```bash
VITE_DISCOVERY_URL=https://discover.example.com/current npm run build
```

App 啟動時會先讀這個網址，取得 `api_url`（Worker 本身）後自動設定後端；
使用者在「伺服器…」手動輸入的位址優先，且不會被自動發現覆蓋。

## Google OAuth 設定

`.env` 把導回網址固定成 Worker：

```env
GOOGLE_REDIRECT_BASE=https://discover.example.com
```

Google Cloud Console → OAuth 用戶端（Web application）→
已授權的重新導向 URI 加入：

```
https://discover.example.com/api/v1/auth/google/callback
```

之後 Colab 每次換網址都不需要再改 Google 設定。

## 手動測試

```bash
curl https://discover.example.com/current
curl -X POST https://discover.example.com/update \
  -H "Authorization: Bearer $PUSH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://demo.trycloudflare.com"}'
```
