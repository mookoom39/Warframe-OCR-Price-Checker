"""Два окна: сканер (CTk) и блокнот (CTkToplevel)."""
import os
import queue
import re
import threading
import tkinter as tk
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import customtkinter as ctk
import pytesseract

import config
import database
import i18n
import matcher
import ocr_engine
import market_api

def _mkey(m):
    """Ключ предмета: название + ваш ранг (у одного мистификатора разные ранги — разные цены)."""
    return (m["slug"], (m.get("meta") or {}).get("rank"))


INSTRUCTION = "Сделай скриншот (Win+Shift+S) -> Кликни сюда -> Ctrl+V"


# ----------------------------------------------------------------- Блокнот
class NotesWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title(i18n.tr("Блокнот"))
        self.geometry("360x480+40+60")
        self.textbox = ctk.CTkTextbox(self, wrap="word", font=("Segoe UI", 14), undo=True)
        self.textbox.pack(fill="both", expand=True, padx=8, pady=8)
        self._save_job = None
        self._load()
        inner = self.textbox._textbox
        inner.edit_modified(False)
        inner.bind("<<Modified>>", self._on_modified)
        inner.bind("<Control-Key>", self._on_ctrl)
        inner.tag_config("link", foreground="#4da6ff", underline=True)
        inner.tag_bind("link", "<Enter>", lambda e: inner.config(cursor="hand2"))
        inner.tag_bind("link", "<Leave>", lambda e: inner.config(cursor="xterm"))
        inner.tag_bind("link", "<ButtonRelease-1>", self._open_link)
        self._highlight_links()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(250, self.lift)

    def _load(self):
        if os.path.exists(config.NOTES_PATH):
            try:
                with open(config.NOTES_PATH, "r", encoding="utf-8") as f:
                    self.textbox.insert("1.0", f.read())
            except OSError:
                pass

    def _highlight_links(self):
        """Подсвечивает http(s)-ссылки в тексте; по клику они открываются в браузере."""
        tb = self.textbox._textbox
        tb.tag_remove("link", "1.0", "end")
        text = tb.get("1.0", "end-1c")
        for m in re.finditer(r"https?://[^\s<>\"']+", text):
            url = m.group(0).rstrip(".,;:!?)]}")
            tb.tag_add("link", f"1.0+{m.start()}c", f"1.0+{m.start() + len(url)}c")

    def _open_link(self, event):
        tb = self.textbox._textbox
        if tb.tag_ranges("sel"):          # выделяете текст — ссылку не открываем
            return
        idx = tb.index(f"@{event.x},{event.y}")
        rng = tb.tag_prevrange("link", f"{idx}+1c")
        if rng and tb.compare(rng[1], ">", idx):
            webbrowser.open(tb.get(*rng))

    def _on_ctrl(self, event):
        """Ctrl+C/V/X/A/Z/Y по коду клавиши — работает и на русской раскладке."""
        tb = self.textbox._textbox
        virtual = {86: "<<Paste>>", 67: "<<Copy>>", 88: "<<Cut>>"}.get(event.keycode)
        if virtual:
            tb.event_generate(virtual)
            return "break"
        if event.keycode == 65:
            tb.tag_add("sel", "1.0", "end-1c")
            return "break"
        if event.keycode in (90, 89):
            try:
                tb.edit_undo() if event.keycode == 90 else tb.edit_redo()
            except tk.TclError:
                pass
            return "break"

    def _on_modified(self, _event):
        inner = self.textbox._textbox
        if inner.edit_modified():
            inner.edit_modified(False)
            self._highlight_links()
            if self._save_job:
                self.after_cancel(self._save_job)
            self._save_job = self.after(500, self.save)

    def save(self):
        self._save_job = None
        try:
            with open(config.NOTES_PATH, "w", encoding="utf-8") as f:
                f.write(self.textbox.get("1.0", "end-1c"))
        except OSError:
            pass

    def close(self):
        self.save()
        self.destroy()


# ------------------------------------------------------------ Главное окно
class MainWindow(ctk.CTk):
    def __init__(self, items, startup_warnings=None):
        super().__init__()
        self.title("Warframe: OCR Price Checker")
        self.geometry("760x620+420+60")
        self.items = items
        self.matcher = matcher.Matcher(items)
        self.updating = False
        self.q = queue.Queue()
        self.busy = False
        self._link_id = 0
        self._rate_lock = threading.Lock()   # общий лимит запросов к Market
        self._next_slot = 0.0
        self._prefetch = {}
        self.totals = {}   # slug -> (мин, медиана, топ-5) для общего итога

        self.hint = ctk.CTkLabel(
            self, text=i18n.tr(INSTRUCTION), font=("Segoe UI", 16, "bold"),
            fg_color="#2b2b2b", corner_radius=8, height=48,
        )
        self.hint.pack(fill="x", padx=10, pady=(10, 6))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=10)
        for col in range(4):
            bar.grid_columnconfigure(col, weight=1, uniform="btn")
        opts = dict(height=34)
        self.paste_btn = ctk.CTkButton(bar, text=i18n.tr("Вставить из буфера"),
                                       command=self.on_paste, **opts)
        self.paste_btn.grid(row=0, column=0, padx=3, sticky="ew")
        self.update_btn = ctk.CTkButton(bar, text=i18n.tr("Обновить базу"), command=self.update_db, **opts)
        self.update_btn.grid(row=0, column=1, padx=3, sticky="ew")
        self.copy_btn = ctk.CTkButton(bar, text=i18n.tr("Копировать всё"), command=self.copy_all, **opts)
        self.copy_btn.grid(row=0, column=2, padx=3, sticky="ew")
        self.clear_btn = ctk.CTkButton(bar, text=i18n.tr("Очистить"), command=self.clear, **opts)
        self.clear_btn.grid(row=0, column=3, padx=3, sticky="ew")
        self.append_var = ctk.BooleanVar(value=False)
        self.switch = ctk.CTkSwitch(bar, text=i18n.tr("Копить результаты (не очищать окно между сканами)"),
                                    variable=self.append_var)
        self.switch.grid(row=1, column=0, columnspan=3, padx=3, pady=(8, 0), sticky="w")
        self.lang_btn = ctk.CTkSegmentedButton(bar, values=["RU", "EN"], width=90,
                                               command=self._on_lang_change)
        self.lang_btn.set(i18n.LANG.upper())
        self.lang_btn.grid(row=1, column=3, padx=3, pady=(8, 0), sticky="e")

        self.textbox = ctk.CTkTextbox(self, wrap="word", font=("Consolas", 14))
        self.textbox.pack(fill="both", expand=True, padx=10, pady=10)
        for tag, color in (("info", "#9aa0a6"), ("ok", "#6fdc8c"), ("warn", "#ffb454"),
                           ("err", "#ff6b6b"), ("head", "#ffffff")):
            self.textbox.tag_config(tag, foreground=color)
        self.textbox.tag_config("head", foreground="#ffffff", underline=False)

        # Ctrl+V: латинская и русская раскладки (keycode 86 = клавиша V в Windows)
        self.bind("<Control-v>", self.on_paste)
        self.bind("<Control-V>", self.on_paste)
        self.bind("<Control-Key>", self._on_ctrl_key)
        self.bind("<Button-1>", self._on_click, add="+")
        self.textbox._textbox.bind("<Key>", self._on_text_key)
        self.textbox._textbox.bind("<<Paste>>", lambda e: "break")

        self.notes = NotesWindow(self)
        self.protocol("WM_DELETE_WINDOW", self.close)

        for w in (startup_warnings or []):
            self._insert(w + "\n", "warn")
        self._insert("Готов к работе. Вставьте скриншот через Ctrl+V.\n", "info")
        self.focus_set()
        self.after(100, self._poll)
        threading.Thread(target=self._warmup, daemon=True).start()
        if not database.is_synced():
            self._insert("Первый запуск: загружаю полный список предметов Market...\n", "info")
            self.after(500, self.update_db)

    # --- служебное
    def close(self):
        try:
            self.notes.save()
        except Exception:
            pass
        self.destroy()

    def _on_ctrl_key(self, event):
        if event.keycode == 86:
            return self.on_paste()

    def _on_click(self, event):
        # клик по тексту не должен отбирать фокус (иначе нельзя выделять и копировать)
        if event.widget is not self.textbox._textbox:
            self.focus_set()

    def _on_text_key(self, event):
        """Поле только для чтения: копировать можно, печатать нельзя.
        Работает на любой раскладке (по коду клавиши Windows)."""
        tb = self.textbox._textbox
        ctrl = bool(event.state & 0x4)
        if ctrl and event.keycode == 86:      # Ctrl+V -> скан буфера
            self.on_paste()
            return "break"
        if ctrl and event.keycode == 67:      # Ctrl+C
            try:
                self.clipboard_clear()
                self.clipboard_append(tb.get("sel.first", "sel.last"))
            except Exception:
                pass
            return "break"
        if ctrl and event.keycode == 65:      # Ctrl+A
            tb.tag_add("sel", "1.0", "end-1c")
            return "break"
        if event.keysym in ("Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next"):
            return None
        return "break"

    def copy_all(self):
        self.clipboard_clear()
        self.clipboard_append(self.textbox._textbox.get("1.0", "end-1c"))
        self._flash_warning("Скопировано в буфер обмена")

    def clear(self):
        self.totals.clear()
        self.textbox._textbox.delete("1.0", "end")

    def _insert(self, text, tag=None):
        tb = self.textbox._textbox
        follow = tb.yview()[1] >= 0.98     # следим за концом, только если вы и так внизу
        tb.insert("end", i18n.tr(text), tag)
        if follow:
            tb.see("end")

    def _insert_link(self, url):
        self._link_id += 1
        tag = f"link_{self._link_id}"
        inner = self.textbox._textbox
        inner.tag_config(tag, foreground="#4da6ff", underline=True)
        inner.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))
        inner.tag_bind(tag, "<Enter>", lambda e: inner.config(cursor="hand2"))
        inner.tag_bind(tag, "<Leave>", lambda e: inner.config(cursor=""))
        self._insert(url, tag)
        self._insert("\n")

    def _copy_text(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self._flash_warning("Скопировано в буфер обмена")

    def _insert_copy_button(self, text):
        tb = self.textbox._textbox
        follow = tb.yview()[1] >= 0.98
        btn = tk.Button(tb, text=i18n.tr("Копировать"),
                        command=lambda t=i18n.tr(text): self._copy_text(t),
                        bg="#1f538d", fg="white", activebackground="#2a6cb5",
                        activeforeground="white", relief="flat", bd=0, padx=8, pady=1,
                        cursor="hand2", font=("Segoe UI", 9))
        tb.window_create("end", window=btn)
        tb.insert("end", "\n")
        if follow:
            tb.see("end")

    def _on_lang_change(self, value):
        i18n.set_lang(value)
        self.apply_language()

    def apply_language(self):
        self.hint.configure(text=i18n.tr(INSTRUCTION))
        self.paste_btn.configure(text=i18n.tr("Вставить из буфера"))
        if not self.updating:
            self.update_btn.configure(text=i18n.tr("Обновить базу"))
        self.copy_btn.configure(text=i18n.tr("Копировать всё"))
        self.clear_btn.configure(text=i18n.tr("Очистить"))
        self.switch.configure(text=i18n.tr("Копить результаты (не очищать окно между сканами)"))
        self.notes.title(i18n.tr("Блокнот"))

    def _flash_warning(self, text):
        self.hint.configure(text=i18n.tr(text), text_color="#ffb454")
        self.after(3000, lambda: self.hint.configure(text=i18n.tr(INSTRUCTION),
                                                     text_color=("gray10", "gray90")))

    def _poll(self):
        try:
            while True:
                kind, *rest = self.q.get_nowait()
                if kind == "text":
                    self._insert(rest[0], rest[1])
                elif kind == "link":
                    self._insert_link(rest[0])
                elif kind == "copybtn":
                    self._insert_copy_button(rest[0])
                elif kind == "busy":
                    self.busy = rest[0]
                elif kind == "updating":
                    self.updating = rest[0]
                    self.update_btn.configure(
                        state="disabled" if rest[0] else "normal",
                        text=i18n.tr("Загрузка...") if rest[0] else i18n.tr("Обновить базу"))
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _log(self, text, tag=None):
        self.q.put(("text", text + "\n", tag))

    # --- обработка Ctrl+V
    def on_paste(self, _event=None):
        if self.busy:
            self._flash_warning("Подождите, идёт обработка...")
            return "break"
        try:
            img = ocr_engine.grab_image()
        except Exception as e:
            img = None
            self._insert(f"Ошибка чтения буфера: {e}\n", "err")
        if img is None:
            self._flash_warning("В буфере нет изображения!")
            self._insert(f"[{datetime.now():%H:%M:%S}] В буфере обмена нет изображения. "
                         "Сделайте скриншот через Win+Shift+S.\n", "warn")
            return "break"
        if not self.append_var.get():
            self.clear()
        self.busy = True
        threading.Thread(target=self._worker, args=(img,), daemon=True).start()
        return "break"

    # --- фоновый поток (GUI не трогает напрямую)
    def _worker(self, img):
        try:
            self._log(f"[{datetime.now():%H:%M:%S}] Распознаю текст...", "info")
            t0 = time.monotonic()
            labels = ocr_engine.extract_labels(img)
            self._log(f"Распознавание заняло {time.monotonic() - t0:.1f} с", "info")
            if ocr_engine.last_note:
                self._log(ocr_engine.last_note, "warn")
            self._log(f"Движок: {ocr_engine.last_engine}", "info")
            if not labels:  # запасной вариант: обычное распознавание целиком
                cleaned = ocr_engine.clean_text(ocr_engine.extract_text(img))
                labels = [[ln] for ln in cleaned.splitlines()]
            if not labels:
                self._log("Текст не распознан. Попробуйте выделить область крупнее.", "warn")
                return
            self._log("Распознанный текст:", "head")
            self._log("\n".join(" ".join(l) for l in labels) + "\n", "info")

            matches, unmatched = self.matcher.find_labels(labels)
            if any(len(u) >= 10 for u in unmatched) and ocr_engine.last_engine == "rapidocr":
                self._log("Часть надписей не распознана — пробую ещё раз (другой масштаб и контраст)...",
                          "info")
                try:
                    m2, u2 = self.matcher.find_labels(ocr_engine.extract_labels(img, variant=1))
                    have = {_mkey(m) for m in matches}
                    extra = [m for m in m2 if _mkey(m) not in have]
                    if extra:
                        matches = matches + extra
                        self._log(f"Во втором проходе найдено ещё: {len(extra)}", "ok")
                    if len([u for u in u2 if len(u) >= 10]) < len([u for u in unmatched if len(u) >= 10]):
                        unmatched = u2
                except Exception as e:
                    self._log(f"Второй проход не удался: {e}", "warn")
            unmatched = [u for u in unmatched if len(u) >= 10]
            if unmatched:
                self._log("Не найдено в базе (пропущено):", "warn")
                self._log("\n".join("  - " + u for u in unmatched) + "\n", "warn")
            if not matches:
                self._log("Предметы из базы не найдены. Попробуйте выделить область точнее "
                          "или нажмите «Обновить базу».", "warn")
                return
            # цены запрашиваем параллельно (3 потока, но не чаще лимита Market),
            # а выводим по порядку — как только очередной предмет готов
            self._log(f"Запрашиваю цены: {len(matches)} предм....", "info")
            self._prefetch = {}
            with ThreadPoolExecutor(max_workers=3) as pool:
                for m in matches:
                    self._prefetch[m["slug"]] = pool.submit(self._fetch_limited, m["slug"])
                for m in matches:
                    self._report(m)
            self._print_total(matches)
            self._log(f"Готово за {time.monotonic() - t0:.1f} с", "info")
        except pytesseract.TesseractNotFoundError:
            self._log("Tesseract не найден. Установите его и проверьте путь "
                      "TESSERACT_CMD в config.py.", "err")
        except pytesseract.TesseractError as e:
            self._log(f"Ошибка Tesseract: {e}", "err")
            self._log("Проверьте, что установлен русский язык (rus), а если вы клали "
                      "rus.traineddata в папку tessdata — что файл не повреждён.", "warn")
        except Exception as e:
            self._log(f"Непредвиденная ошибка: {e}", "err")
        finally:
            self.q.put(("busy", False))

    def _fetch_limited(self, slug):
        """Запрос цен с общей паузой между стартами запросов (лимит API ~3 в секунду)."""
        with self._rate_lock:
            wait = self._next_slot - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._next_slot = time.monotonic() + config.REQUEST_DELAY
        return market_api.fetch_orders(slug)

    def _get_orders(self, slug):
        fut = self._prefetch.get(slug)
        return fut.result() if fut else market_api.fetch_orders(slug)

    def _report(self, m):
        slug, name = m["slug"], i18n.item_name(m)
        block = []

        def emit(text, tag=None):
            block.append(text)
            self._log(text, tag)

        def finish():
            self.q.put(("copybtn", "\n".join(block)))

        self._log("-" * 46, "info")
        pct = f"  (совпадение {m['score']:.0%})" if m["score"] < 0.995 else ""
        meta = m.get("meta") or {}
        own, qty = meta.get("rank"), meta.get("qty") or 1
        extra = (f"  ранг {own}" if own is not None else "") + (f"  ×{qty}" if qty > 1 else "")
        emit(f"{name}  [{slug}]{pct}{extra}", "head")
        emit(f"  по надписи: «{m['source']}»", "info")
        left = m.get("leftover")
        if left:
            emit("  ВНИМАНИЕ: в надписи остались слова «" + " ".join(left) +
                 "» — возможно, это другой предмет, цена может быть неверной.", "warn")
            sug = self.matcher.suggest(name, left)
            if sug:
                emit("  Похожие в базе: " + "; ".join(sug), "warn")
        try:
            orders = self._get_orders(slug)
        except market_api.ItemNotFound:
            emit("Предмет не найден на Market (404).", "warn")
            return finish()
        except market_api.MarketError as e:
            emit(str(e), "err")
            return finish()
        ranks = market_api.ranks_of(orders)
        if ranks and own is not None:      # цена для вашего ранга
            if market_api.analyze(orders, own) is not None:
                variants = [(f"ваш ранг {own}", own)]
            else:
                variants = [(f"ваш ранг {own}: продавцов нет, показан ранг {ranks[0]}", ranks[0])]
        elif ranks:  # ранг не определён: показываем ранг 0 и максимальный
            variants = [(f"ранг {r}" + (" (макс.)" if r == ranks[-1] and len(ranks) > 1 else ""), r)
                        for r in dict.fromkeys([ranks[0], ranks[-1]])]
        else:
            variants = [("", None)]
        for label, rank in variants:
            stats = market_api.analyze(orders, rank)
            if label:
                emit(f"  [{label}]", "head")
            if stats is None:
                emit("  Нет активных продавцов в игре (ingame).", "warn")
                continue
            emit(f"  Минимальная цена : {stats['min']:g} pl", "ok")
            emit(f"  Медиана          : {stats['median']:g} pl", "ok")
            emit(f"  Среднее (топ-{stats['top_n']})  : {stats['avg_top']:.1f} pl", "ok")
            emit(f"  Продавцов ingame : {stats['count']}", "info")
            if _mkey(m) not in self.totals:   # в общий итог идёт первый вариант
                self.totals[_mkey(m)] = (stats["min"], stats["median"], stats["avg_top"], qty)
        url = market_api.item_url(slug)
        block.append(url)
        self.q.put(("link", url))
        finish()

    def _print_total(self, matches):
        t = self.totals
        if not t:
            return
        mn = sum(v[0] * v[3] for v in t.values())
        md = sum(v[1] * v[3] for v in t.values())
        av = sum(v[2] * v[3] for v in t.values())
        pieces = sum(v[3] for v in t.values())
        lines = [f"ИТОГО за {len(t)} предм.:",
                 f"  по минимуму : {mn:g} pl",
                 f"  по медиане  : {md:g} pl",
                 f"  по топ-5    : {av:.1f} pl"]
        skipped = [m for m in matches if _mkey(m) not in t]
        if skipped:
            lines.append(f"  (без цены: {len(skipped)})")
        self._log("=" * 46, "info")
        self._log("\n".join(lines) + "\n", "ok")
        self.q.put(("copybtn", "\n".join(lines)))

    # --- обновление базы предметов
    def update_db(self):
        if self.updating:
            return
        self.q.put(("updating", True))
        self.updating = True
        self._log("Загружаю список предметов с Warframe.Market...", "info")
        threading.Thread(target=self._update_worker, daemon=True).start()

    def _update_worker(self):
        try:
            rows = market_api.fetch_all_items("ru")
            database.bulk_upsert(rows)
            items = database.load_items()
            self.matcher = matcher.Matcher(items)
            self.items = items
            self._log(f"База обновлена: {len(items)} предметов.", "ok")
        except market_api.MarketError as e:
            self._log(f"Не удалось обновить базу: {e}", "err")
        except Exception as e:
            self._log(f"Ошибка обновления базы: {e}", "err")
        finally:
            self.q.put(("updating", False))

    def _warmup(self):
        self._log(ocr_engine.warm_up(), "info")
