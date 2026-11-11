"""Переключатель языка RU/EN: перевод сообщений программы и названий предметов."""
import os
import re

import config

_PATH = os.path.join(config.BASE_DIR, "lang.txt")
LANG = "ru"

# (русский текст, английский). Подстановка идёт от длинных фраз к коротким.
PAIRS = [
    ("Сделай скриншот (Win+Shift+S) -> Кликни сюда -> Ctrl+V",
     "Take a screenshot (Win+Shift+S) -> Click here -> Ctrl+V"),
    ("Копить результаты (не очищать окно между сканами)", "Keep results (don't clear between scans)"),
    ("Готов к работе. Вставьте скриншот через Ctrl+V.", "Ready. Paste a screenshot with Ctrl+V."),
    ("Первый запуск: загружаю полный список предметов Market...",
     "First run: downloading the full Market item list..."),
    ("Загружаю список предметов с Warframe.Market...", "Downloading the item list from Warframe.Market..."),
    ("Часть надписей не распознана — пробую ещё раз (другой масштаб и контраст)...",
     "Some labels were not recognized — trying again (different scale and contrast)..."),
    ("Предметы из базы не найдены. Попробуйте выделить область точнее или нажмите «Обновить базу».",
     "No items from the database found. Try selecting a tighter area or press “Update database”."),
    ("Текст не распознан. Попробуйте выделить область крупнее.",
     "No text recognized. Try selecting a larger area."),
    ("Tesseract не найден. Установите его и проверьте путь TESSERACT_CMD в config.py.",
     "Tesseract not found. Install it and check TESSERACT_CMD in config.py."),
    ("Проверьте, что установлен русский язык (rus), а если вы клали rus.traineddata в папку tessdata — что файл не повреждён.",
     "Make sure the Russian language (rus) is installed; if you put rus.traineddata into the tessdata folder, check the file is not corrupted."),
    ("Сервер вернул HTTP 403 (доступ запрещён). Возможно, блокировка защиты сайта: попробуйте позже, другую сеть или VPN.",
     "Server returned HTTP 403 (access denied). The site protection may be blocking you: try later, another network or a VPN."),
    ("Таймаут: сервер Warframe.Market не ответил вовремя.", "Timeout: Warframe.Market did not respond in time."),
    ("Нет соединения с интернетом или сервер недоступен.", "No internet connection or the server is unavailable."),
    ("Слишком много запросов (429). Подождите пару секунд.", "Too many requests (429). Wait a couple of seconds."),
    ("Неожиданный формат списка предметов.", "Unexpected item list format."),
    ("Неожиданный формат ответа API.", "Unexpected API response format."),
    ("Распознавание: RapidOCR (нейросеть) готово.", "Recognition: RapidOCR (neural network) ready."),
    ("RapidOCR ничего не нашёл — пробую Tesseract.", "RapidOCR found nothing — trying Tesseract."),
    ("— возможно, это другой предмет, цена может быть неверной.",
     "— this may be a different item, the price may be wrong."),
    ("В буфере обмена нет изображения.", "There is no image in the clipboard."),
    ("Сделайте скриншот через Win+Shift+S.", "Take a screenshot with Win+Shift+S."),
    ("Нет активных продавцов в игре (ingame).", "No active sellers in game (ingame)."),
    ("Предмет не найден на Market (404).", "Item not found on Market (404)."),
    ("Не найдено в базе (пропущено):", "Not found in the database (skipped):"),
    ("Во втором проходе найдено ещё:", "Found in the second pass:"),
    ("Нет языкового пакета Tesseract:", "Missing Tesseract language pack:"),
    ("Tesseract не найден по пути:", "Tesseract not found at:"),
    ("Скопировано в буфер обмена", "Copied to clipboard"),
    ("Подождите, идёт обработка...", "Please wait, processing..."),
    ("В буфере нет изображения!", "No image in the clipboard!"),
    ("ВНИМАНИЕ: в надписи остались слова", "WARNING: leftover words in the label"),
    ("Не удалось обновить базу:", "Could not update the database:"),
    ("Ошибка обновления базы:", "Database update error:"),
    ("Не удалось запустить", "Could not start"),
    ("Второй проход не удался:", "Second pass failed:"),
    ("Распознавание: Tesseract.", "Recognition: Tesseract."),
    ("Распознавание заняло", "Recognition took"),
    ("Непредвиденная ошибка:", "Unexpected error:"),
    ("Ошибка чтения буфера:", "Clipboard error:"),
    ("Минимальная цена :", "Min price        :"),
    ("Медиана          :", "Median           :"),
    ("Продавцов ingame :", "Sellers ingame   :"),
    ("Среднее (топ-", "Average (top-"),
    ("Вставить из буфера", "Paste from clipboard"),
    ("Запрашиваю цены:", "Requesting prices:"),
    ("Распознанный текст:", "Recognized text:"),
    ("Пока использую Tesseract.", "Using Tesseract for now."),
    ("Использую Tesseract.", "Using Tesseract."),
    ("RapidOCR не установлен", "RapidOCR is not installed"),
    ("Сервер вернул HTTP", "Server returned HTTP"),
    ("Положите", "Put"),
    ("в папку tessdata.", "into the tessdata folder."),
    ("Распознаю текст...", "Recognizing text..."),
    ("Копировать всё", "Copy all"),
    ("Обновить базу", "Update database"),
    ("База обновлена:", "Database updated:"),
    ("Ошибка Tesseract:", "Tesseract error:"),
    ("Ошибка RapidOCR", "RapidOCR error"),
    ("Похожие в базе:", "Similar in database:"),
    ("по надписи:", "from text:"),
    ("(совпадение", "(match"),
    ("ваш ранг", "your rank"),
    ("продавцов нет, показан ранг", "no sellers, showing rank"),
    ("не запустился", "failed to start"),
    ("Ошибка сети:", "Network error:"),
    ("ИТОГО за", "TOTAL for"),
    ("по минимуму :", "by minimum  :"),
    ("по медиане  :", "by median   :"),
    ("по топ-5    :", "by top-5    :"),
    ("(без цены:", "(no price:"),
    ("предметов.", "items."),
    ("предм....", "items..."),
    ("предм.:", "items:"),
    ("Готово за", "Done in"),
    ("Загрузка...", "Loading..."),
    ("Копировать", "Copy"),
    ("Очистить", "Clear"),
    ("Блокнот", "Notepad"),
    ("Движок:", "Engine:"),
    ("(макс.)", "(max)"),
    ("вариант", "variant"),
    ("ранг", "rank"),
]
PAIRS.sort(key=lambda p: -len(p[0]))
_SECONDS = re.compile(r"(\d) с(?=\s|$)")


def load():
    global LANG
    try:
        with open(_PATH, encoding="utf-8") as f:
            LANG = "en" if f.read().strip().lower() == "en" else "ru"
    except OSError:
        LANG = "ru"


def set_lang(lang):
    global LANG
    LANG = "en" if str(lang).lower() == "en" else "ru"
    try:
        with open(_PATH, "w", encoding="utf-8") as f:
            f.write(LANG)
    except OSError:
        pass


def tr(text):
    """Перевод текста на текущий язык (для русского возвращает как есть)."""
    if LANG != "en" or not text:
        return text
    for ru, en in PAIRS:
        if ru in text:
            text = text.replace(ru, en)
    return _SECONDS.sub(r"\1 s", text)


def item_name(m):
    """Название предмета: по-русски из базы, по-английски — из имени на сайте (slug)."""
    if LANG == "en":
        return " ".join(w.capitalize() for w in m["slug"].split("_"))
    return m["ru_name"]


load()
