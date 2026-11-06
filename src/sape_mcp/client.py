"""Клиент XML-RPC API sape.ru с cookie-сессией и rate-limiting.

Документация API: https://api.sape.ru/xmlrpc/
Ограничение sape.ru: не более 120 запросов в минуту на аккаунт.
"""

from __future__ import annotations

import re
import threading
import time
import xmlrpc.client
from typing import Any

import httpx

DEFAULT_API_URL = "https://api.sape.ru/xmlrpc/"


class SapeError(Exception):
    """Ошибка вызова API sape.ru (fault)."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def sanitize(value: Any) -> Any:
    """Привести XML-RPC-спецтипы (DateTime, Binary, bytes) к JSON-сериализуемым."""
    if isinstance(value, xmlrpc.client.DateTime):
        return str(value)  # ISO8601-строка из ответа API
    if isinstance(value, xmlrpc.client.Binary):
        return value.data.decode("utf-8", "replace")
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    return value


class _RateLimiter:
    """Окно на 60 секунд: не более лимита запросов."""

    def __init__(self, max_calls: int = 115, window: float = 60.0) -> None:
        self._max = max_calls
        self._window = window
        self._times: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._times = [t for t in self._times if now - t < self._window]
                if len(self._times) < self._max:
                    self._times.append(now)
                    return
                sleep_for = self._window - (now - self._times[0]) + 0.05
            time.sleep(max(sleep_for, 0.05))


class _CookieTransport:
    """XML-RPC-транспорт поверх httpx с сохранением cookies сессии."""

    user_agent = "sape-mcp/1.0"

    def __init__(self, url: str, cookies: httpx.Cookies, timeout: float) -> None:
        self._url = url
        self._cookies = cookies
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    def request(self, host: str, handler: str, request_body: bytes, verbose: bool = False) -> Any:
        response = self._client.post(
            self._url,
            content=request_body,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "User-Agent": self.user_agent,
            },
            cookies=self._cookies,
        )
        # API sape.ru возвращает cookies сессии — сохраняем их.
        self._cookies.update(response.cookies)
        if response.status_code != 200:
            raise xmlrpc.client.ProtocolError(self._url, response.status_code, response.reason_phrase, dict(response.headers))
        # Кастомный транспорт обязан сам разобрать XML-RPC-ответ:
        # ServerProxy возвращает результат request() без дополнительного парсинга.
        unmarshaller = xmlrpc.client.Unmarshaller()
        parser = xmlrpc.client.ExpatParser(unmarshaller)
        parser.feed(response.content)
        parser.close()
        return unmarshaller.close()

    def close(self) -> None:
        self._client.close()


class SapeClient:
    """Сессия работы с XML-RPC API sape.ru.

    Авторизация: sape.login(login, token) при первом вызове; полученные
    cookies передаются с каждым последующим запросом.
    """

    def __init__(
        self,
        login: str,
        token: str,
        api_url: str = DEFAULT_API_URL,
        timeout: float = 60.0,
        max_calls_per_minute: int = 115,
    ) -> None:
        self._login = login
        self._token = token
        self._limiter = _RateLimiter(max_calls_per_minute)
        self._cookies = httpx.Cookies()
        self._transport = _CookieTransport(api_url, self._cookies, timeout)
        self._proxy = xmlrpc.client.ServerProxy(
            api_url,
            transport=self._transport,  # type: ignore[arg-type]
            allow_none=True,
        )
        self._logged_in = False

    def close(self) -> None:
        self._transport.close()

    def _ensure_login(self) -> None:
        if self._logged_in:
            return
        # login() вызывается напрямую, без рекурсии через call().
        self._limiter.acquire()
        result = sanitize(self._proxy.sape.login(self._login, self._token))
        self._logged_in = True
        return result

    def call(self, method: str, *params: Any) -> Any:
        """Выполнить метод sape.* и вернуть декодированный результат.

        Fault-ответы преобразуются в SapeError; 6xx — коды авторизации,
        при них выполняется повторный login и одна повторная попытка.
        """
        full_method = method if method.startswith("sape.") else f"sape.{method}"
        for attempt in (1, 2):
            try:
                self._ensure_login()
                self._limiter.acquire()
                target: Any = self._proxy
                for part in full_method.split("."):
                    target = getattr(target, part)
                return sanitize(target(*params))
            except xmlrpc.client.Fault as exc:
                if 600 <= exc.faultCode < 700 and attempt == 1:
                    self._logged_in = False
                    continue
                raise SapeError(exc.faultCode, exc.faultString) from exc
            except xmlrpc.client.ProtocolError as exc:
                if attempt == 1 and exc.errcode in (401, 403):
                    self._logged_in = False
                    continue
                raise SapeError(exc.errcode, exc.errmsg or "protocol error") from exc
        raise SapeError(-1, "unreachable")


def parse_ids(raw: Any) -> list[int]:
    """Привести вход к списку int-ID (строки, числа, разделители)."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        items: list[Any] = list(raw)
    else:
        items = re.split(r"[,\s]+", str(raw).strip()) if str(raw).strip() else []
    return [int(x) for x in items if str(x).strip() != ""]
