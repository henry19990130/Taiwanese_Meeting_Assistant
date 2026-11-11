/**
 * MeetSum Discovery Worker
 *
 * 固定入口：App 永遠只認這個網址，Colab 每次啟動後把當次的
 * trycloudflare 臨時網址寫進來，App 就能自動找到後端。
 *
 * 路由：
 *   GET  /current   → { url, updated_at }       （App 讀取，CORS 開放）
 *   POST /update    → 需要 Bearer PUSH_TOKEN     （Colab 寫入）
 *   GET  /health    → { status: "ok" }
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
      const raw = await env.MEETSUM_KV.get(KEY, "json");
      if (!raw || !raw.url) return json({ url: null, updated_at: null });
      const age = Date.now() - Number(raw.updated_at || 0);
      if (age > MAX_AGE_MS) return json({ url: null, updated_at: raw.updated_at, stale: true });
      return json({ url: raw.url, updated_at: raw.updated_at, stale: false });
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
      return json({ ok: true, ...record });
    }

    return json({ ok: false, error: "not_found" }, 404);
  },
};
