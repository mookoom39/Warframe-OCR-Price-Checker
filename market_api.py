"""Клиент Warframe.Market (публичное API v2, при ошибке доступа — v1)."""
import statistics
import time
import requests

import config


class MarketError(Exception):
    pass


class MarketHTTPError(MarketError):
    """Сервер ответил, но с кодом ошибки (можно попробовать запасное API)."""


class ItemNotFound(MarketError):
    pass


def item_url(slug: str) -> str:
    return f"{config.SITE_BASE}/{slug}"


def _get_json(url, headers=None, timeout=None):
    resp = None
    for attempt in range(3):          # до 3 попыток при таймауте/обрыве
        try:
            resp = requests.get(url, headers=headers or config.HEADERS,
                                timeout=timeout or config.REQUEST_TIMEOUT)
            break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt == 2:
                if isinstance(e, requests.exceptions.Timeout):
                    raise MarketError("Таймаут: сервер Warframe.Market не ответил вовремя.")
                raise MarketError("Нет соединения с интернетом или сервер недоступен.")
            time.sleep(1.0)
        except requests.exceptions.RequestException as e:
            raise MarketError(f"Ошибка сети: {e}")

    code = resp.status_code
    if code == 404:
        raise ItemNotFound(url)
    if code == 429:
        raise MarketHTTPError("Слишком много запросов (429). Подождите пару секунд.")
    if code == 403:
        raise MarketHTTPError("Сервер вернул HTTP 403 (доступ запрещён). Возможно, "
                              "блокировка защиты сайта: попробуйте позже, другую сеть или VPN.")
    if code != 200:
        raise MarketHTTPError(f"Сервер вернул HTTP {code}.")
    try:
        return resp.json()
    except ValueError:
        raise MarketError("Неожиданный формат ответа API.")


def _orders_from(data):
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):                 # v2
            return data["data"]
        payload = data.get("payload")                          # v1
        if isinstance(payload, dict) and isinstance(payload.get("orders"), list):
            return payload["orders"]
    raise MarketError("Неожиданный формат ответа API.")


def _items_from(data, language):
    out = []
    if isinstance(data, dict) and isinstance(data.get("data"), list):       # v2
        for it in data["data"]:
            i18n = it.get("i18n") or {}
            entry = i18n.get(language) or i18n.get("ru") or i18n.get("en") or {}
            if entry.get("name") and it.get("slug"):
                out.append((entry["name"], it["slug"]))
        return out
    payload = data.get("payload") if isinstance(data, dict) else None        # v1
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        for it in payload["items"]:
            if it.get("item_name") and it.get("url_name"):
                out.append((it["item_name"], it["url_name"]))
        return out
    raise MarketError("Неожиданный формат списка предметов.")


def fetch_orders(slug: str) -> list:
    try:
        return _orders_from(_get_json(f"{config.API_V2}/orders/item/{slug}"))
    except MarketHTTPError as first:
        try:
            return _orders_from(_get_json(f"{config.API_V1}/items/{slug}/orders"))
        except ItemNotFound:
            raise
        except MarketError:
            raise first


def fetch_all_items(language: str = "ru"):
    """Полный список предметов Market: [(название на языке, slug), ...]."""
    headers = dict(config.HEADERS)
    headers["Language"] = language
    try:
        return _items_from(_get_json(f"{config.API_V2}/items", headers, 30), language)
    except MarketHTTPError as first:
        try:
            return _items_from(_get_json(f"{config.API_V1}/items", headers, 30), language)
        except MarketError:
            raise first


# ---------- анализ ----------
def _otype(o):
    return o.get("type") or o.get("order_type")


def _rank(o):
    r = o.get("rank")
    return o.get("mod_rank") if r is None else r


def ranks_of(orders: list):
    """Для модов/арканов: отсортированный список рангов, иначе []."""
    return sorted({_rank(o) for o in orders if _rank(o) is not None})


def analyze(orders: list, rank=None):
    """Фильтр: sell + ingame (+ранг). Возвращает статистику или None."""
    prices = sorted(
        o["platinum"]
        for o in orders
        if _otype(o) == "sell"
        and o.get("visible", True)
        and (o.get("user") or {}).get("status") == "ingame"
        and isinstance(o.get("platinum"), (int, float))
        and (rank is None or _rank(o) == rank)
    )
    if not prices:
        return None
    top = prices[: config.TOP_N_AVG]
    return {
        "count": len(prices),
        "min": prices[0],
        "median": statistics.median(prices),
        "avg_top": sum(top) / len(top),
        "top_n": len(top),
    }
