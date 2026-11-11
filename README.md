# Warframe Clipboard OCR Price Checker

**🇬🇧 English** · [🇷🇺 Русский ниже](#-русский)

A small, safe companion tool for Warframe. Take a screenshot of your inventory, mods, arcanes, relic rewards or Prime parts, press **Ctrl+V** — and get live **Warframe.Market** prices for every item on the screenshot.

> **100% external and safe.** The tool never touches the game: no memory reading, no game files, no logs, no overlay. It only reads an image from your clipboard and talks to the public Warframe.Market API.

## Features
- Reads item names from a screenshot with a small neural network (**RapidOCR**, Tesseract as optional fallback).
- Works with the **Russian and English** game clients; the UI can be switched between **RU / EN**.
- Understands inventory grids: multi-line names, names split by icons, scrambled word order, OCR typos (fuzzy matching against the full Market item list, ~4000 items).
- Shows **minimum price, median and the average of the 5 cheapest** sellers who are *in game*; for mods/arcanes — both rank 0 and max rank.
- **Total** value of everything on the screenshot.
- Prices are requested in parallel (within the API rate limit).
- Click-to-copy block for every item, "Copy all", clickable Market links.
- Built-in **notepad** (auto-saved, clickable links).
- Warns when part of a label was not used (e.g. "Umbra" variants), so you don't trust a wrong price.

## Quick start (Windows)
1. Install **Python 3.10+** (tick *Add Python to PATH*).
2. In the project folder run:
   ```
   pip install -r requirements.txt
   ```
3. Start the app: double-click **`main.pyw`** (no console window) or run `python main.py`.
4. On first start it downloads the item list and the small OCR models (internet needed).
5. `Win+Shift+S` → select the area → click the app window → `Ctrl+V`.

Tips: larger text on the screenshot = better accuracy. Press **Update database** every few weeks to get new items.

Tesseract OCR is **optional** (used only if RapidOCR is unavailable): https://github.com/UB-Mannheim/tesseract/wiki

## Build an .exe
```
pip install pyinstaller
pyinstaller --noconsole --onedir --name WarframePriceChecker --collect-all rapidocr --collect-all customtkinter --collect-all onnxruntime main.pyw
```
Share the whole `dist\WarframePriceChecker` folder. Some antivirus programs flag PyInstaller builds (false positive).

## Project layout
| File | Purpose |
|---|---|
| `main.pyw` / `main.py` | launcher |
| `gui.py` | windows, buttons, output, notepad |
| `ocr_engine.py` | clipboard image → text, grouping of labels in grids |
| `matcher.py` | fuzzy matching of names against the item database |
| `market_api.py` | Warframe.Market API v2 (v1 fallback), price statistics |
| `database.py` | local SQLite item database |
| `i18n.py` | RU / EN switch |
| `config.py` | settings |

## Disclaimer
Unofficial fan-made tool. Not affiliated with or endorsed by Digital Extremes or Warframe.Market. Prices are a snapshot of current in-game sell orders — always double-check before a big trade. Please respect the Warframe.Market API rate limits.

---

# 🇷🇺 Русский

Небольшой безопасный помощник для Warframe. Сделайте скриншот инвентаря, модов, мистификаторов, наград реликвий или прайм-частей, нажмите **Ctrl+V** — и получите актуальные цены **Warframe.Market** на все предметы со скриншота.

> **Полностью внешняя и безопасная программа.** Она не вмешивается в игру: не читает память, файлы и логи игры, не рисует оверлей. Только берёт картинку из буфера обмена и обращается к публичному API Warframe.Market.

## Возможности
- Читает названия со скриншота нейросетью (**RapidOCR**, Tesseract — необязательный запасной вариант).
- Работает с **русским и английским** клиентом игры; интерфейс переключается **RU / EN**.
- Понимает сетки инвентаря: названия в несколько строк, надписи, разорванные иконками, перепутанный порядок слов, опечатки распознавания (нечёткий поиск по полному списку предметов Market, ~4000 шт.).
- Показывает **минимум, медиану и среднее по 5 самым дешёвым** продавцам, которые *в игре*; для модов и мистификаторов — цены без прокачки и максимального ранга.
- **Общий итог** по всем предметам на скриншоте.
- Цены запрашиваются параллельно (в рамках лимита API).
- Кнопка «Копировать» у каждого предмета, «Копировать всё», кликабельные ссылки на Market.
- Встроенный **блокнот** (автосохранение, кликабельные ссылки).
- Предупреждает, если часть надписи не использована (например, варианты «Умбра»), чтобы вы не доверились неверной цене.

## Быстрый старт (Windows)
1. Установите **Python 3.10+** (поставьте галочку *Add Python to PATH*).
2. В папке проекта выполните:
   ```
   pip install -r requirements.txt
   ```
3. Запустите: двойной клик по **`main.pyw`** (без чёрного окна) или `python main.py`.
4. При первом запуске скачаются список предметов и небольшие модели распознавания (нужен интернет).
5. `Win+Shift+S` → выделите область → кликните в окно программы → `Ctrl+V`.

Советы: чем крупнее текст на скриншоте, тем точнее результат. Раз в несколько недель нажимайте **«Обновить базу»**, чтобы подтянулись новые предметы.

Tesseract OCR **необязателен** (используется, только если RapidOCR недоступен).

## Сборка в .exe
Команда выше (раздел *Build an .exe*). Отдавайте другим всю папку `dist\WarframePriceChecker`. Антивирусы иногда ругаются на сборки PyInstaller — это ложное срабатывание.

## Отказ от ответственности
Неофициальный фанатский инструмент, не связан с Digital Extremes и Warframe.Market. Цены — снимок текущих заявок на продажу; перед крупной сделкой перепроверяйте. Соблюдайте лимиты API Warframe.Market.
