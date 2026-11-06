"""Тесты клиента sape-mcp (без обращения к реальному API)."""

from __future__ import annotations

import xmlrpc.client
from unittest.mock import MagicMock, patch

import httpx
import pytest

from sape_mcp.client import SapeClient, _RateLimiter, parse_ids


def test_parse_ids_variants() -> None:
    assert parse_ids("12, 34 56") == [12, 34, 56]
    assert parse_ids([1, "2"]) == [1, 2]
    assert parse_ids("") == []
    assert parse_ids(None) == []


def test_rate_limiter_bounds() -> None:
    limiter = _RateLimiter(max_calls=3, window=0.2)
    for _ in range(3):
        limiter.acquire()
    assert len(limiter._times) == 3


def _make_client() -> tuple[SapeClient, MagicMock]:
    client = SapeClient("user", "token")
    proxy = MagicMock()
    client._proxy = proxy  # noqa: SLF001
    client._logged_in = True  # noqa: SLF001 — пропускаем login в тестах
    return client, proxy


def test_call_success() -> None:
    client, proxy = _make_client()
    proxy.sape.get_balance.return_value = 123.45
    assert client.call("sape.get_balance") == 123.45
    proxy.sape.get_balance.assert_called_once_with()


def test_call_adds_prefix() -> None:
    client, proxy = _make_client()
    proxy.sape.get_user.return_value = {"login": "u"}
    assert client.call("get_user") == {"login": "u"}


def test_fault_6xx_relogins_once() -> None:
    client, proxy = _make_client()
    proxy.sape.get_balance.side_effect = [
        xmlrpc.client.Fault(601, "not logged in"),
        10.0,
    ]
    assert client.call("sape.get_balance") == 10.0
    assert proxy.sape.get_balance.call_count == 2


def test_fault_other_raises_sape_error() -> None:
    from sape_mcp.client import SapeError

    client, proxy = _make_client()
    proxy.sape.get_balance.side_effect = xmlrpc.client.Fault(4112, "text error")
    with pytest.raises(SapeError) as exc_info:
        client.call("sape.get_balance")
    assert exc_info.value.code == 4112


def test_server_tools_registered() -> None:
    import asyncio

    from sape_mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    expected = {
        "get_balance", "get_user", "list_projects", "get_project",
        "list_urls", "get_url_anchors", "get_project_links",
        "get_url_links", "search_pages", "create_placement",
        "create_placements", "sape_call",
    }
    assert expected <= names
