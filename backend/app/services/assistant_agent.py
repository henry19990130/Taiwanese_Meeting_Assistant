from __future__ import annotations

import datetime as dt
import json
import logging
import re
from zoneinfo import ZoneInfo

import httpx

from app import config
from app.services import assistant_search as S

log = logging.getLogger(__name__)

REFUSE = "抱歉，這個問題跟你的會議紀錄無關，我只能幫你查會議裡的內容喔。你可以試試下面的選項，或問我會議相關的問題。"
WEEKDAY = "一二三四五六日"

SYSTEM_PROMPT = """你是「鉛筆小書記」，會議助理網站裡的小幫手。你只能回答「使用者自己的會議紀錄」相關的問題：會議內容、決議、待辦、負責人、期限、誰說過什麼、某句話的出處。
今天是 {today}（星期{weekday}）。

規則：
1. 回答前一定要先呼叫工具查資料。答案只能根據工具回傳的內容，不可以用自己的知識補充或猜測。
2. 問題跟會議紀錄無關（例如寫信、翻譯、寫程式、閒聊、天氣、一般知識），不要呼叫工具，只回覆：OFF_TOPIC
3. 問題太模糊、必須先問清楚才能查，回覆一句以「ASK:」開頭的追問。
4. 回答中引用的每個事實後面，加上工具結果裡的編號，例如「上線日改為 11/22 [3]」。
5. 工具都查不到，就說會議紀錄裡沒有找到，不要猜。
6. 期間參數直接用使用者的說法即可（例如「上個月」「這週」「10月」），程式會換算。
7. 用繁體中文，口語、簡短；有多項時用條列。不要輸出 JSON 或程式碼。"""

TOOLS = [
    {"type": "function", "function": {
        "name": "search_meetings",
        "description": "依關鍵字、期間、人名找會議，回傳會議清單（名稱、日期、一句話總結）。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "關鍵字，例如：預算、官網改版"},
            "period": {"type": "string", "description": "會議日期範圍，例如：上個月、這週、9月、最近30天"},
            "person": {"type": "string", "description": "與會或被提到的人名"}}}}},
    {"type": "function", "function": {
        "name": "search_content",
        "description": "在逐字稿與會議重點裡找跟問題相關的內容（誰說過什麼、某件事怎麼決定）。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "要找的內容，用關鍵詞，例如：上線日 延後"},
            "period": {"type": "string", "description": "會議日期範圍（可省略）"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "get_meeting_summary",
        "description": "讀一場會議的完整重點（決議、待辦、討論、下次會議）。meeting_id 從 search_meetings 的結果取得。",
        "parameters": {"type": "object", "properties": {
            "meeting_id": {"type": "string"}}, "required": ["meeting_id"]}}},
    {"type": "function", "function": {
        "name": "list_action_items",
        "description": "查待辦事項：指定負責人、在某期間到期、或還沒有負責人的。",
        "parameters": {"type": "object", "properties": {
            "assignee": {"type": "string", "description": "負責人名字"},
            "due_period": {"type": "string", "description": "到期日範圍，例如：這週、下週、10月"},
            "unassigned": {"type": "boolean", "description": "true = 只列還沒有負責人的"},
            "meeting_period": {"type": "string", "description": "只看某期間的會議"}}}}},
    {"type": "function", "function": {
        "name": "find_quote",
        "description": "找一句話出自哪場會議、第幾分鐘，附前後文。",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "使用者提供的那句話"}}, "required": ["text"]}}},
]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


def today_local() -> dt.date:
    return dt.datetime.now(ZoneInfo(config.TIMEZONE)).date()


def run_tool(name: str, args: dict, lib: list[dict], src: S.Sources, today: dt.date) -> dict:
    a = args if isinstance(args, dict) else {}
    s = lambda k: (str(a[k]).strip() or None) if a.get(k) not in (None, "") else None
    if name == "search_meetings":
        return S.search_meetings(lib, src, today, query=s("query"), period=s("period"), person=s("person"))
    if name == "search_content":
        q = s("query")
        return S.search_content(lib, src, today, q, period=s("period")) if q else {"error": "缺少 query"}
    if name == "get_meeting_summary":
        return S.get_meeting_summary(lib, src, s("meeting_id") or "")
    if name == "list_action_items":
        un = a.get("unassigned")
        un = un if isinstance(un, bool) else str(un).lower() in ("true", "1", "yes")
        return S.list_action_items(lib, src, today, assignee=s("assignee"), due_period=s("due_period"),
                                   unassigned=un, meeting_period=s("meeting_period"))
    if name == "find_quote":
        t = s("text")
        return S.find_quote(lib, src, t) if t else {"error": "缺少 text"}
    return {"error": f"沒有這個工具：{name}"}


def _count(result: dict) -> int:
    if "error" in result:
        return 0
    if "count" in result:
        return int(result["count"])
    return 1


def _clip(obj, n: int = 160):
    if isinstance(obj, str):
        return obj if len(obj) <= n else obj[: n - 1] + "…"
    if isinstance(obj, list):
        return [_clip(x, n) for x in obj]
    if isinstance(obj, dict):
        return {k: _clip(v, n) for k, v in obj.items() if k != "context"}
    return obj


def finalize(text: str, called: list[dict], src: S.Sources) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    trace = [{"tool": c["tool"], "args": c["args"], "count": c["count"]} for c in called]
    if "OFF_TOPIC" in text or not called:
        if called == [] and text.upper().startswith("ASK:"):
            return {"kind": "ask", "text": text[4:].strip(), "sources": [], "trace": trace}
        return {"kind": "refuse", "text": REFUSE, "sources": [], "trace": trace}
    if all(c["count"] == 0 for c in called):
        return {"kind": "not_found", "sources": [], "trace": trace,
                "text": "你的會議紀錄裡沒有找到相關的內容。我不會用猜的回答，要不要換個關鍵字，或指定是哪一場會議？"}
    cited: list[int] = []

    def keep(m):
        n = int(m.group(1))
        if src.get(n) is None:
            return ""
        if n not in cited:
            cited.append(n)
        return f"[{n}]"
    text = re.sub(r"\[(\d{1,3})\]", keep, text)
    sources = [src.get(n) for n in cited] or src.items[:3]
    return {"kind": "answer", "text": text, "sources": sources, "trace": trace}


class AssistantAgent:
    def __init__(self) -> None:
        self.backend = config.LLM_BACKEND

    def answer(self, lib: list[dict], question: str, history: list[dict] | None = None,
               today: dt.date | None = None) -> dict:
        today = today or today_local()
        src = S.Sources()
        if self.backend == "fake":
            return self._fake(lib, question, src, today)

        messages = [{"role": "system", "content": SYSTEM_PROMPT.format(
            today=today.isoformat(), weekday=WEEKDAY[today.weekday()])}]
        for h in (history or [])[-6:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": str(h["content"])[:800]})
        messages.append({"role": "user", "content": question})

        called: list[dict] = []
        text = ""
        for step in range(config.ASSISTANT_MAX_STEPS + 1):
            allow_tools = step < config.ASSISTANT_MAX_STEPS
            msg = self._chat(messages, allow_tools)
            calls = msg.get("tool_calls") or []
            if calls and allow_tools:
                messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
                for c in calls:
                    fn = c.get("function") or {}
                    name = fn.get("name", "")
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except ValueError:
                            args = {}
                    result = run_tool(name, args, lib, src, today) if name in TOOL_NAMES else {"error": "沒有這個工具"}
                    called.append({"tool": name, "args": args, "count": _count(result)})
                    log.info("小幫手工具 %s %s → %d 筆", name, args, _count(result))
                    messages.append({"role": "tool", "tool_name": name,
                                     "content": json.dumps(_clip(result), ensure_ascii=False, default=str)})
                continue
            text = msg.get("content") or ""
            break
        return finalize(text, called, src)

    def _chat(self, messages: list[dict], allow_tools: bool) -> dict:
        payload: dict = {
            "model": config.LLM_MODEL, "messages": messages, "stream": False,
            "think": config.ASSISTANT_THINK,
            "options": {"temperature": config.LLM_TEMPERATURE, "seed": config.LLM_SEED,
                        "num_ctx": config.LLM_NUM_CTX},
        }
        if allow_tools:
            payload["tools"] = TOOLS
        resp = httpx.post(f"{config.OLLAMA_HOST}/api/chat", json=payload, timeout=config.LLM_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            raise RuntimeError(f"Ollama 回應 {resp.status_code}：{resp.text[:200]}")
        return resp.json().get("message") or {}

    def _fake(self, lib, question, src, today) -> dict:
        r = S.search_content(lib, src, today, question)
        called = [{"tool": "search_content", "args": {"query": question}, "count": r["count"]}]
        if r["count"] == 0:
            return finalize("OFF_TOPIC", [], src)
        lines = [f"- {x['meeting']}（{x['date'][5:].replace('-', '/')}）：{x['text'][:40]} [{x['ref']}]"
                 for x in r["results"][:3]]
        return finalize("（測試模式）找到這些相關內容：\n" + "\n".join(lines), called, src)


_agent: AssistantAgent | None = None


def get_agent() -> AssistantAgent:
    global _agent
    if _agent is None:
        _agent = AssistantAgent()
    return _agent
