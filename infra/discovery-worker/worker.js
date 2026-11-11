/**
 * MeetSum Discovery + Proxy Worker
 *
 * 固定入口：App 永遠只認這個網址。Colab 每次啟動後把當次的
 * trycloudflare 臨時網址寫進來，App 就能自動找到後端。
 *
 * 除了「發現」之外，這個 Worker 也直接代理後端：
 *   /api/*、/docs 等非保留路徑 → 轉送到目前有效的 Colab 網址。
 *
 * 這樣做的主要理由是 Google OAuth：Google 只接受「事先登記」的
 * redirect URI，trycloudflare 每次都不一樣。如果 App 直接連 Colab，
 * 每次都要去 Google Console 改設定。改用 Worker 的固定網域當後端，
 * redirect URI 就永遠是同一個。
 *
 * 路由：
 *   GET  /current   → { url, api_url, updated_at, proxy: true }  （App 讀取）
 *   POST /update    → 需要 Bearer PUSH_TOKEN                     （Colab 寫入）
 *   GET  /health    → { status: "ok" }
 *   其他             → 代理到目前的 Colab 後端
 *
 * 環境變數 / Secrets：
 *   PUSH_TOKEN  （wrangler secret put PUSH_TOKEN）
 *   MEETSUM_KV  （wrangler.toml 的 kv_namespaces）
 */

const KEY = "current";
const MAX_AGE_MS = 1000 * 60 * 60 * 24 * 7; // 超過 7 天視為過期

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
  "Access-Control-Max-Age": "86400",
};

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...CORS },
  });
}

function isHttpsUrl(raw) {
  try {
    const u = new URL(String(raw));
    return u.protocol === "https:" && u.hostname.endsWith(".trycloudflare.com");
  } catch (_) {
    return false;
  }
}

async function currentBackend(env) {
  const raw = await env.MEETSUM_KV.get(KEY, "json");
  if (!raw || !raw.url) return null;
  if (Date.now() - Number(raw.updated_at || 0) > MAX_AGE_MS) return null;
  return raw;
}

/** 把請求原樣轉給 Colab；保留 3xx 的 Location（meetsum:// 深層連結要靠它）。 */
async function proxy(request, env, url) {
  const backend = await currentBackend(env);
  if (!backend) return json({ ok: false, error: "no_backend" }, 503);

  const target = new URL(backend.url);
  target.pathname = url.pathname;
  target.search = url.search;

  const headers = new Headers(request.headers);
  headers.delete("host");
  // 讓後端推導出「使用者看到的」網址（Google redirect_uri、音檔連結都要一致）
  headers.set("x-forwarded-host", url.host);
  headers.set("x-forwarded-proto", url.protocol.replace(":", ""));

  const init = { method: request.method, headers, redirect: "manual" };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = request.body;
  }

  let res;
  try {
    res = await fetch(target.toString(), init);
  } catch (exc) {
    return json({ ok: false, error: "backend_unreachable", detail: String(exc) }, 502);
  }
  return new Response(res.body, { status: res.status, headers: new Headers(res.headers) });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }

    if (url.pathname === "/health") {
      return json({ status: "ok", service: "meetsum-discovery" });
    }

    if (url.pathname === "/current" && request.method === "GET") {
      const raw = await currentBackend(env);
      if (!raw) return json({ url: null, api_url: null, updated_at: null, proxy: true });
      return json({
        url: raw.url,
        // App 可以直接把 API base 設成 Worker，之後 Colab 換網址也不用重設
        api_url: url.origin,
        updated_at: raw.updated_at,
        stale: false,
        proxy: true,
      });
    }

    if (url.pathname === "/update" && request.method === "POST") {
      const auth = request.headers.get("Authorization") || "";
      const token = auth.startsWith("Bearer ") ? auth.slice(7) : "";
      if (!env.PUSH_TOKEN || token !== env.PUSH_TOKEN) {
        return json({ ok: false, error: "unauthorized" }, 401);
      }
      let body;
      try {
        body = await request.json();
      } catch (_) {
        return json({ ok: false, error: "invalid_json" }, 400);
      }
      if (!isHttpsUrl(body.url)) {
        return json({ ok: false, error: "invalid_url" }, 400);
      }
      const record = { url: String(body.url), updated_at: Date.now() };
      await env.MEETSUM_KV.put(KEY, JSON.stringify(record));
      return json({ ok: true, ...record, api_url: url.origin, proxy: true });
    }

    // 其餘路徑（/api/...、/docs…）都代理到目前的 Colab
    return proxy(request, env, url);
  },
};
