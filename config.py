"""Глобальные настройки приложения."""
import os
import sys

# в собранном exe файлы данных (база, заметки) лежат рядом с exe, а не во временной папке
BASE_DIR = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "items.db")
NOTES_PATH = os.path.join(BASE_DIR, "notes.txt")

# --- OCR ---
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
# Только русский распознаётся заметно чище, чем "rus+eng" (английская модель
# подсовывает мусорные слова). Для англоязычного клиента игры поставьте "eng".
# Движок распознавания: "auto" (RapidOCR, а если он не установлен — Tesseract),
# "rapidocr" или "tesseract".
OCR_ENGINE = "auto"
OCR_LANG = "rus"
# Необязательно: положите rus.traineddata из tessdata_best в папку tessdata рядом
# с программой — точность распознавания станет выше. Папка подхватится сама.


def _short_path(path):
    """Windows: путь с кириллицей -> короткий ASCII-путь (Tesseract плохо читает юникод)."""
    if os.name != "nt" or path.isascii():
        return path
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024)
        return buf.value if n else path
    except Exception:
        return path


_best = os.path.join(BASE_DIR, "tessdata")
if os.path.exists(os.path.join(_best, "rus.traineddata")):
    # через переменную окружения: так нет проблем с кавычками и пробелами в пути
    os.environ["TESSDATA_PREFIX"] = _short_path(_best)

# --- Warframe.Market ---
# Основное API — v2; если оно недоступно, программа пробует v1
API_V2 = "https://api.warframe.market/v2"
API_V1 = "https://api.warframe.market/v1"  # запасной вариант
SITE_BASE = "https://warframe.market/items"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WFClipboardPriceChecker/1.1",
    "Platform": "pc",
    "Language": "en",
    "Crossplay": "true",
    "Accept": "application/json",
}
REQUEST_TIMEOUT = 15      # секунд
REQUEST_DELAY = 0.35      # пауза между запросами (лимит API ~3 запроса/сек)
TOP_N_AVG = 5             # сколько самых дешёвых лотов усреднять

# --- Сопоставление названий ---
FUZZY_CUTOFF = 0.85
