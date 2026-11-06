"""MCP-сервер sape-mcp: инструменты для работы с sape.ru из LLM-бота.

Запуск: sape-mcp (stdio). Конфигурация через переменные окружения:
  SAPE_LOGIN  — логин аккаунта sape.ru
  SAPE_TOKEN  — API-токен (https://passport.sape.ru/security/token/)
  SAPE_API_URL — необязательно, по умолчанию https://api.sape.ru/xmlrpc/
  SAPE_MAX_CALLS_PER_MINUTE — необязательно, по умолчанию 115 (лимит sape.ru — 120)
"""

from __future__ import annotations

import os
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP

from .client import DEFAULT_API_URL, SapeClient, parse_ids

mcp = FastMCP("sape-mcp")

_client: SapeClient | None = None


def get_client() -> SapeClient:
    global _client
    if _client is None:
        login = os.environ.get("SAPE_LOGIN", "").strip()
        token = os.environ.get("SAPE_TOKEN", "").strip()
        if not login or not token:
            raise RuntimeError(
                "Не заданы SAPE_LOGIN и SAPE_TOKEN. "
                "Токен создаётся на https://passport.sape.ru/security/token/"
            )
        _client = SapeClient(
            login=login,
            token=token,
            api_url=os.environ.get("SAPE_API_URL", DEFAULT_API_URL),
            max_calls_per_minute=int(os.environ.get("SAPE_MAX_CALLS_PER_MINUTE", "115")),
        )
    return _client


# --- Баланс и аккаунт -------------------------------------------------------

@mcp.tool()
def get_balance() -> dict[str, Any]:
    """Текущий баланс аккаунта sape.ru: полный и доступный к тратам."""
    client = get_client()
    return {
        "total": client.call("sape.get_balance"),
        "available": client.call("sape.get_balance_real"),
    }


@mcp.tool()
def get_user() -> dict[str, Any]:
    """Информация о текущем пользователе: login, баланс, расходы за сутки/неделю, месячный бюджет."""
    return dict(get_client().call("sape.get_user"))


# --- Проекты ----------------------------------------------------------------

@mcp.tool()
def list_projects(
    show_deleted: Annotated[bool, "Показывать удалённые проекты"] = False,
    show_counts: Annotated[bool, "Включить количество урлов и ссылок"] = True,
) -> dict[str, Any]:
    """Список проектов (кампаний) оптимизатора с количеством урлов и ссылок."""
    options = {"show_deleted": show_deleted, "show_count": show_counts}
    return {"projects": get_client().call("sape.get_projects", options)}


@mcp.tool()
def get_project(project_id: Annotated[int, "ID проекта"]) -> dict[str, Any]:
    """Параметры проекта: расходы за сегодня/вчера/всего, число ссылок OK, настройки автоснятия."""
    return dict(get_client().call("sape.get_project", project_id))


# --- URL-ы и анкоры ----------------------------------------------------------

@mcp.tool()
def list_urls(project_id: Annotated[int, "ID проекта"]) -> dict[str, Any]:
    """Список URL-ов проекта с их ID и статистикой."""
    return {"urls": get_client().call("sape.get_urls", project_id)}


@mcp.tool()
def get_url_anchors(url_id: Annotated[int, "ID URL-а"]) -> dict[str, Any]:
    """Список анкоров URL-а: текст, сколько раз использован, лимит использований."""
    return {"anchors": get_client().call("sape.get_url_anchors", url_id)}


# --- Ссылки ------------------------------------------------------------------

@mcp.tool()
def get_project_links(
    project_id: Annotated[int, "ID проекта (или несколько через запятую)"],
) -> dict[str, Any]:
    """Все размещённые ссылки проекта: площадка, URL страницы, анкор, цена, статус."""
    client = get_client()
    ids = parse_ids(project_id)
    links: list[Any] = []
    for pid in ids:
        links.extend(client.call("sape.get_project_links", pid))
    return {"count": len(links), "links": links}


@mcp.tool()
def get_url_links(url_id: Annotated[int, "ID URL-а"]) -> dict[str, Any]:
    """Ссылки конкретного URL-а с их статусами."""
    return {"links": get_client().call("sape.get_url_links", url_id)}


# --- Поиск площадок и покупка -------------------------------------------------

@mcp.tool()
def search_pages(
    url_id: Annotated[int, "ID URL-а, для которого ищутся площадки"],
    filter_query: Annotated[dict[str, Any], "Фильтр поиска (см. документацию sape.search_pages): например {'words': ['тема'], 'max_price': 50, 'pr_min': 1}"],
    page: Annotated[int, "Номер страницы результатов (с 0)"] = 0,
    page_size: Annotated[int, "Размер страницы (до 100)"] = 50,
) -> dict[str, Any]:
    """Поиск страниц площадок для покупки ссылок под URL по заданию: темы, цена, тИЦ/PR и др."""
    return {
        "pages": get_client().call("sape.search_pages", url_id, filter_query, page, page_size)
    }


@mcp.tool()
def create_placement(
    page_id: Annotated[int, "ID страницы площадки (из search_pages)"],
    url_id: Annotated[int, "ID URL-а, на который покупается ссылка"],
    anchor: Annotated[str, "ID анкора, текст анкора или 0 — взять следующий неиспользованный"] = "0",
    max_price: Annotated[float, "Максимальная цена за ссылку; если цена выше — покупка не выполняется"] = 0.0,
    wait_approval: Annotated[bool, "Установить статус «ожидает подтверждения оптимизатора», если возможно"] = False,
) -> dict[str, Any]:
    """Купить ссылку (размещение) на выбранной странице. Тратит реальные деньги аккаунта."""
    client = get_client()
    anchor_param: Any
    if anchor.strip() == "0":
        anchor_param = 0
    elif anchor.strip().isdigit():
        anchor_param = int(anchor)
    else:
        anchor_param = anchor
    options: dict[str, Any] = {}
    if max_price > 0:
        options["max_price"] = max_price
    if wait_approval:
        options["force_seo_wait"] = 1
    placement_id = client.call("sape.placement_create", page_id, url_id, anchor_param, options)
    return {"placement_id": placement_id}


@mcp.tool()
def create_placements(
    placements: Annotated[list[dict[str, Any]], "Список: [{page_id, url_id, anchor?, max_price?}, ...] (до 200 за вызов)"],
) -> dict[str, Any]:
    """Пакетная покупка ссылок. Тратит реальные деньги аккаунта."""
    if len(placements) > 200:
        raise ValueError("Максимум 200 placements за вызов")
    prepared: list[dict[str, Any]] = []
    for item in placements:
        entry = {
            "page_id": int(item["page_id"]),
            "url_id": int(item["url_id"]),
            "anchor": 0 if str(item.get("anchor", "0")) == "0" else item.get("anchor", 0),
        }
        if item.get("max_price"):
            entry["max_price"] = float(item["max_price"])
        prepared.append(entry)
    return {"result": get_client().call("sape.placements_create", prepared)}


# --- Универсальный вызов ------------------------------------------------------

@mcp.tool()
def sape_call(
    method: Annotated[str, "Полное имя метода API, например sape.get_site, sape.get_system_bills"],
    params: Annotated[list[Any], "Позиционные аргументы метода (см. https://api.sape.ru/xmlrpc/)"] | None = None,
) -> Any:
    """Универсальный вызов любого метода XML-RPC API sape.ru, для которого нет отдельного инструмента."""
    return get_client().call(method, *(params or []))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
