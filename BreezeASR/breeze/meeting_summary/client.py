from collections.abc import Callable
import json

import requests

from breeze.meeting_summary.errors import SummaryError
from breeze.meeting_summary.prompt import SYSTEM_PROMPT, build_user_prompt

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.1:8b"
DEFAULT_TEMPERATURE = 0.2

TokenCallback = Callable[[str], None]


def resolve_model_name(requested: str, installed: list[str]) -> str | None:
    """裸名稱在本機只有同系列 `:8b` 時改用那個 tag。已指定其他 tag 則不改。"""
    names = [name for name in installed if name]
    if requested in names:
        return requested
    if ":" in requested and not requested.endswith(":latest"):
        return None
    family = requested.split(":", 1)[0]
    for candidate in (f"{family}:8b", f"{family}:latest"):
        if candidate in names:
            return candidate
    matches = [name for name in names if name.startswith(f"{family}:")]
    if len(matches) == 1:
        return matches[0]
    return None


class OllamaChatClient:
    """只負責跟本機 Ollama 串流對話，不處理檔案與匯出。"""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        model: str = DEFAULT_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: tuple[float, float] = (5, 600),
    ):
        self._host = host.rstrip("/")
        self._model = model
        self._temperature = temperature
        self._timeout = timeout

    def summarize(
        self,
        transcript: str,
        *,
        source_name: str,
        created_at: str,
        on_token: TokenCallback | None = None,
    ) -> str:
        payload = {
            "model": self._model,
            "stream": True,
            "options": {"temperature": self._temperature},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_user_prompt(
                        transcript,
                        source_name=source_name,
                        created_at=created_at,
                    ),
                },
            ],
        }
        return self._chat(payload, on_token=on_token)

    def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
        payload = {
            "model": self._model,
            "stream": True,
            "options": {"temperature": self._temperature if temperature is None else temperature},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        return self._chat(payload)

    def _chat(self, payload: dict, on_token: TokenCallback | None = None) -> str:
        url = f"{self._host}/api/chat"
        try:
            response = self._post_chat(url, payload)
        except requests.exceptions.ConnectionError as exc:
            raise SummaryError(
                "連不到 Ollama。請先在本機執行 `ollama serve`，確認 http://127.0.0.1:11434 有在聽。"
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise SummaryError(f"Ollama 回應逾時。請確認 {self._model} 已下載且本機負載正常。") from exc

        if response.status_code == 404:
            response.close()
            resolved = self._installed_model(self._model)
            if resolved is None or resolved == self._model:
                raise SummaryError(
                    f"Ollama 找不到模型 `{self._model}`。請執行 `ollama pull {self._model}`。"
                )
            payload["model"] = resolved
            try:
                response = self._post_chat(url, payload)
            except requests.exceptions.ConnectionError as exc:
                raise SummaryError(
                    "連不到 Ollama。請先在本機執行 `ollama serve`，確認 http://127.0.0.1:11434 有在聽。"
                ) from exc
            except requests.exceptions.Timeout as exc:
                raise SummaryError(f"Ollama 回應逾時。請確認 {self._model} 已下載且本機負載正常。") from exc
            if response.status_code == 404:
                response.close()
                raise SummaryError(
                    f"Ollama 找不到模型 `{resolved}`。請執行 `ollama pull {resolved}`。"
                )
        if response.status_code >= 400:
            detail = response.text.strip() or response.reason
            response.close()
            raise SummaryError(f"Ollama 回傳 HTTP {response.status_code}：{detail}")

        chunks: list[str] = []
        try:
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise SummaryError("Ollama 串流內容不是合法 JSON。") from exc
                if event.get("error"):
                    raise SummaryError(f"Ollama 錯誤：{event['error']}")
                token = str((event.get("message") or {}).get("content") or "")
                if token:
                    chunks.append(token)
                    if on_token is not None:
                        on_token(token)
        except requests.exceptions.RequestException as exc:
            raise SummaryError(f"讀取 Ollama 串流失敗：{exc}") from exc
        finally:
            response.close()

        markdown = "".join(chunks).strip()
        if not markdown:
            raise SummaryError("Ollama 沒有產出任何文字。")
        return markdown

    def _post_chat(self, url: str, payload: dict):
        return requests.post(url, json=payload, stream=True, timeout=self._timeout)

    def _installed_model(self, requested: str) -> str | None:
        try:
            response = requests.get(f"{self._host}/api/tags", timeout=(5, 10))
        except requests.exceptions.RequestException:
            return None
        try:
            if response.status_code >= 400:
                return None
            names = [
                str(item.get("name") or "")
                for item in (response.json().get("models") or [])
                if isinstance(item, dict)
            ]
        except (ValueError, AttributeError):
            return None
        finally:
            response.close()
        return resolve_model_name(requested, names)
