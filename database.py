"""Локальная SQLite-БД: русское название -> slug на Warframe.Market."""
import sqlite3
from config import DB_PATH

PART_RU = {
    "blueprint": "Чертеж",
    "chassis": "Каркас",
    "neuroptics": "Нейрооптика",
    "systems": "Система",
    "barrel": "Ствол",
    "receiver": "Ресивер",
    "stock": "Приклад",
    "blade": "Лезвие",
    "disc": "Диск",
    "set": "Комплект",
}

WARFRAME_PARTS = ["blueprint", "chassis", "neuroptics", "systems", "set"]
RIFLE_PARTS = ["blueprint", "barrel", "receiver", "stock", "set"]
GLAIVE_PARTS = ["blueprint", "blade", "disc", "set"]

# (русское имя, префикс slug, список частей)
BASES = [
    ("Мэг Прайм", "mag_prime", WARFRAME_PARTS),
    ("Рино Прайм", "rhino_prime", WARFRAME_PARTS),
    ("Вольт Прайм", "volt_prime", WARFRAME_PARTS),
    ("Сарин Прайм", "saryn_prime", WARFRAME_PARTS),
    ("Эш Прайм", "ash_prime", WARFRAME_PARTS),
    ("Локи Прайм", "loki_prime", WARFRAME_PARTS),
    ("Нова Прайм", "nova_prime", WARFRAME_PARTS),
    ("Некрос Прайм", "nekros_prime", WARFRAME_PARTS),
    ("Эквинокс Прайм", "equinox_prime", WARFRAME_PARTS),
    ("Меса Прайм", "mesa_prime", WARFRAME_PARTS),
    ("Сома Прайм", "soma_prime", RIFLE_PARTS),
    ("Болтор Прайм", "boltor_prime", RIFLE_PARTS),
    ("Братон Прайм", "braton_prime", RIFLE_PARTS),
    ("Глейв Прайм", "glaive_prime", GLAIVE_PARTS),
]

EXTRA = [
    ("Кува Брамма", "kuva_bramma"),
    ("Кува Ком", "kuva_kohm"),
    ("Кува Хек", "kuva_hek"),
    ("Кува Карак", "kuva_karak"),
    ("Кува Нукор", "kuva_nukor"),
    ("Кува Брекк", "kuva_brakk"),
    ("Кува Огрис", "kuva_ogris"),
    ("Кува Зарр", "kuva_zarr"),
    ("Кува Тонкор", "kuva_tonkor"),
    ("Форма Чертеж", "forma_blueprint"),
]


def _seed_rows():
    rows = []
    for ru, slug, parts in BASES:
        for p in parts:
            rows.append((f"{ru} {PART_RU[p]}", f"{slug}_{p}"))
    rows.extend(EXTRA)
    return rows


def init_db():
    """Создаёт таблицу и добавляет недостающие записи (ничего не затирает)."""
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS items (
                   item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ru_name TEXT NOT NULL,
                   en_market_url_name TEXT NOT NULL UNIQUE
               )"""
        )
        con.executemany(
            "INSERT OR IGNORE INTO items (ru_name, en_market_url_name) VALUES (?, ?)",
            _seed_rows(),
        )


def load_items():
    """Возвращает список (item_id, ru_name, slug)."""
    with sqlite3.connect(DB_PATH) as con:
        return con.execute(
            "SELECT item_id, ru_name, en_market_url_name FROM items"
        ).fetchall()


def add_item(ru_name: str, slug: str):
    """Добавить свой предмет вручную."""
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT OR REPLACE INTO items (ru_name, en_market_url_name) VALUES (?, ?)",
            (ru_name.strip(), slug.strip().lower()),
        )


def _ensure_meta(con):
    con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")


def is_synced() -> bool:
    """Была ли уже загрузка полного списка с Market."""
    with sqlite3.connect(DB_PATH) as con:
        _ensure_meta(con)
        row = con.execute("SELECT value FROM meta WHERE key='synced'").fetchone()
        return bool(row)


def bulk_upsert(rows):
    """Массово добавить/обновить [(ru_name, slug)] и отметить базу как загруженную."""
    with sqlite3.connect(DB_PATH) as con:
        _ensure_meta(con)
        con.executemany(
            """INSERT INTO items (ru_name, en_market_url_name) VALUES (?, ?)
               ON CONFLICT(en_market_url_name) DO UPDATE SET ru_name=excluded.ru_name""",
            rows,
        )
        con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('synced', '1')")
