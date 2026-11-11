"""Буфер обмена -> изображение -> текст (Tesseract)."""
import re
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageGrab, ImageOps, ImageFilter, ImageStat
import pytesseract

import config

pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD


def _safe_get_errors(raw):
    """Сообщения Tesseract на русской Windows бывают не в UTF-8 — читаем любую кодировку."""
    if isinstance(raw, str):
        return raw
    for enc in ("utf-8", "cp1251", "cp866"):
        try:
            return " ".join(raw.decode(enc).splitlines()).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


pytesseract.pytesseract.get_errors = _safe_get_errors

LAT2CYR = str.maketrans("aAbBcCeEhHkKmMoOpPtTxXyY", "аАвВсСеЕнНкКмМоОрРтТхХуУ")
CYR2LAT = str.maketrans("аАвВсСеЕнНкКмМоОрРтТхХуУ", "aAbBcCeEhHkKmMoOpPtTxXyY")

TYPO_FIXES = {
    "прайн": "Прайм", "праим": "Прайм", "прайи": "Прайм", "праиm": "Прайм",
    "чертёж": "Чертеж", "чертеи": "Чертеж",
}


def grab_image():
    """Возвращает PIL.Image из буфера или None, если там не картинка."""
    data = ImageGrab.grabclipboard()
    if isinstance(data, Image.Image):
        return data
    if isinstance(data, list):  # скопированные файлы
        for path in data:
            try:
                return Image.open(path)
            except Exception:
                continue
    return None


def _otsu(gray: Image.Image) -> int:
    hist = gray.histogram()
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    wb = sb = 0
    best, thr = 0.0, 128
    for t in range(256):
        wb += hist[t]
        if wb == 0:
            continue
        wf = total - wb
        if wf == 0:
            break
        sb += t * hist[t]
        var = wb * wf * (sb / wb - (sum_all - sb) / wf) ** 2
        if var > best:
            best, thr = var, t
    return thr


def _binarize(gray: Image.Image) -> Image.Image:
    """Чёрный текст на белом фоне, независимо от исходной темы."""
    t = _otsu(gray)
    b = gray.point(lambda p: 255 if p > t else 0)
    if b.histogram()[255] / (b.width * b.height) < 0.5:
        b = ImageOps.invert(b)
    return b


def _stroke_width(fg: Image.Image) -> float:
    """Примерная толщина штриха букв (пикселей) по коротким горизонтальным отрезкам."""
    w, h = fg.size
    runs = []
    for y in range(0, h, max(1, h // 120)):
        row = list(fg.crop((0, y, w, y + 1)).getdata())
        n = 0
        for v in row:
            if v:
                n += 1
            elif n:
                runs.append(n)
                n = 0
        if n:
            runs.append(n)
    runs = sorted(r for r in runs if r <= 12)
    return runs[len(runs) // 2] if runs else 3.0


def prepare(img: Image.Image, remove_icons: bool = True) -> Image.Image:
    """Серое -> контраст -> увеличение -> бинаризация -> (вырезание иконок)."""
    g0 = ImageOps.autocontrast(ImageOps.grayscale(img.convert("RGB")), cutoff=1)
    k = 3 if g0.width < 900 else 2 if g0.width < 2000 else 1
    g = g0.resize((g0.width * k, g0.height * k), Image.LANCZOS) if k > 1 else g0
    out = _binarize(g)
    if remove_icons:
        fg = ImageOps.invert(_binarize(g0))          # передний план = белый
        erode = max(5, int(_stroke_width(fg) * 2.4) | 1)
        blobs = fg.filter(ImageFilter.MinFilter(erode)).filter(
            ImageFilter.MaxFilter(erode * 2 + 3))     # толстые пятна = иконки
        out.paste(255, mask=blobs.resize(out.size, Image.NEAREST))
    return out


def preprocess(img: Image.Image) -> Image.Image:
    return prepare(img, remove_icons=False)


def _tess_config(psm: int) -> str:
    return f"--psm {psm}"


def extract_text(img: Image.Image) -> str:
    return pytesseract.image_to_string(
        preprocess(img), lang=config.OCR_LANG, config=_tess_config(6)
    )


def _fix_mixed_script(token: str) -> str:
    """Слова вроде 'Пpaйм' (латиница внутри кириллицы) приводим к одному алфавиту."""
    cyr = len(re.findall(r"[а-яА-ЯёЁ]", token))
    lat = len(re.findall(r"[a-zA-Z]", token))
    if cyr and lat:
        return token.translate(LAT2CYR) if cyr >= lat else token.translate(CYR2LAT)
    return token


def clean_text(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        line = re.sub(r"[^A-Za-zА-Яа-яЁё0-9\s]", " ", line)
        tokens = [_fix_mixed_script(t) for t in line.split()]
        tokens = [t for t in tokens if not t.isdigit()]   # цифры (стоимость, количество) не нужны
        tokens = [TYPO_FIXES.get(t.lower(), t) for t in tokens]
        line = " ".join(tokens).strip()
        if len(line) >= 3:
            lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Подписи предметов в сетке: слова с координатами -> строки -> подписи
# ---------------------------------------------------------------------------
def _group_words(words, gap_factor=1.3, boxes_out=None):
    """words: [(left, top, width, height, text)] -> [[строка1, строка2, ...], ...]
    Каждая внутренняя группа — одна подпись предмета (она может быть в 2-3 строки)."""
    if not words:
        return []
    # шум от иконок: слишком высокие/низкие «слова» отбрасываем по медианной высоте
    heights = sorted(w[3] for w in words)
    med = heights[len(heights) // 2]
    words = [w for w in words if 0.4 * med <= w[3] <= 2.2 * med]
    if not words:
        return []

    # 1) слова -> горизонтальные ряды по центру (допуск от медианной, а не максимальной высоты)
    words = sorted(words, key=lambda w: w[1] + w[3] / 2)
    tol = 0.45 * med
    rows = []
    for w in words:
        cy = w[1] + w[3] / 2
        for row in rows:
            if abs(row["cy"] - cy) <= tol:
                row["words"].append(w)
                row["cy"] += (cy - row["cy"]) / len(row["words"])
                break
        else:
            rows.append({"cy": cy, "h": med, "words": [w]})

    # 2) ряд -> сегменты: большой горизонтальный разрыв = другой предмет
    segs = []
    for row in rows:
        ws = sorted(row["words"], key=lambda w: w[0])
        h = sum(w[3] for w in ws) / len(ws)
        cur = [ws[0]]
        for prev, w in zip(ws, ws[1:]):
            if w[0] - (prev[0] + prev[2]) > gap_factor * med:
                segs.append(cur)
                cur = []
            cur.append(w)
        segs.append(cur)
    segments = []
    for ws in segs:
        left = min(w[0] for w in ws)
        right = max(w[0] + w[2] for w in ws)
        top = min(w[1] for w in ws)
        bottom = max(w[1] + w[3] for w in ws)
        segments.append({"text": " ".join(w[4] for w in ws), "left": left, "right": right,
                         "top": top, "bottom": bottom, "h": bottom - top,
                         "parent": None, "child": None})

    # 3) сегменты друг под другом (выровнены по центру) -> одна подпись
    segments.sort(key=lambda s: s["top"])
    for i, s in enumerate(segments):
        best, best_gap = None, None
        for p in segments[:i]:
            if p["child"] is not None:
                continue
            gap = s["top"] - p["bottom"]
            overlap = min(s["right"], p["right"]) - max(s["left"], p["left"])
            narrow = min(s["right"] - s["left"], p["right"] - p["left"])
            if -0.3 * s["h"] <= gap <= 1.6 * med and overlap > 0.2 * narrow:
                if best is None or gap < best_gap:
                    best, best_gap = p, gap
        if best is not None:
            best["child"] = s
            s["parent"] = best

    items = []
    for s in segments:
        if s["parent"] is None:
            chain, segs, cur = [], [], s
            while cur is not None:
                chain.append(cur["text"])
                segs.append(cur)
                cur = cur["child"]
            left = min(x["left"] for x in segs)
            right = max(x["right"] for x in segs)
            bbox = ((left + right) / 2, left, right, s["top"], segs[-1]["bottom"])
            items.append((segs[-1]["bottom"], s["left"], chain, bbox))

    # Порядок чтения как у человека: ряд за рядом сверху вниз, внутри ряда слева направо.
    # Подписи прижаты книзу карточки, поэтому ряд определяем по нижнему краю.
    items.sort(key=lambda x: x[0])
    rows, row, anchor = [], [], None
    for it in items:
        if anchor is None or it[0] - anchor > 1.5 * med:
            if row:
                rows.append(row)
            row, anchor = [it], it[0]
        else:
            row.append(it)
    if row:
        rows.append(row)
    ordered = [it for r in rows for it in sorted(r, key=lambda x: x[1])]
    if boxes_out is not None:
        boxes_out.extend(it[3] for it in ordered)
    return [it[2] for it in ordered]


def _labels_from(image: Image.Image, min_conf: float):
    data = pytesseract.image_to_data(
        image, lang=config.OCR_LANG, config=_tess_config(11),
        output_type=pytesseract.Output.DICT,
    )
    words = []
    for i, txt in enumerate(data["text"]):
        txt = (txt or "").strip()
        if not txt:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < min_conf:
            continue
        words.append((data["left"][i], data["top"][i], data["width"][i],
                      data["height"][i], txt))
    labels = []
    for chain in _group_words(words):
        lines = [clean_text(t) for t in chain]
        lines = [ln for ln in lines if ln]
        if lines:
            labels.append(lines)
    return labels


def _tesseract_labels(img: Image.Image, min_conf: float = 25.0):
    """Список подписей (каждая — список строк). Два варианта картинки — с вырезанием
    иконок и без — распознаются параллельно, результаты объединяются."""
    variants = [prepare(img, True), prepare(img, False)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda im: _labels_from(im, min_conf), variants))
    merged, seen = [], set()
    for labels in results:
        for lines in labels:
            key = " ".join(lines).lower()
            if key not in seen:
                seen.add(key)
                merged.append(lines)
    return merged


# ---------------------------------------------------------------------------
# RapidOCR (маленькая нейросеть, русский язык) + выбор движка
# ---------------------------------------------------------------------------
class EngineUnavailable(Exception):
    pass


_rapid = None
last_engine = "tesseract"   # какой движок реально отработал в последний раз
last_note = ""              # пояснение (например, почему RapidOCR не использован)


def _get_rapid():
    global _rapid
    if _rapid is not None:
        return _rapid
    try:
        from rapidocr import RapidOCR, LangRec, ModelType, OCRVersion
    except ImportError:
        raise EngineUnavailable("RapidOCR не установлен (pip install rapidocr onnxruntime).")
    try:
        from importlib.metadata import version as _v
        ver = _v("rapidocr")
    except Exception:
        ver = "?"
    import numpy as np
    dummy = np.full((64, 256, 3), 255, dtype=np.uint8)

    v5, v4 = getattr(OCRVersion, "PPOCRV5", None), getattr(OCRVersion, "PPOCRV4", None)
    mobile = ModelType.MOBILE
    cyr = LangRec.CYRILLIC
    combos = []
    if v5 is not None:   # русская модель PP-OCRv5 (нужен rapidocr >= 3.5)
        combos.append({"Det.ocr_version": v5, "Det.model_type": mobile,
                       "Rec.ocr_version": v5, "Rec.lang_type": cyr, "Rec.model_type": mobile})
        combos.append({"Rec.ocr_version": v5, "Rec.lang_type": cyr, "Rec.model_type": mobile})
    if v4 is not None:
        combos.append({"Det.ocr_version": v4, "Rec.ocr_version": v4,
                       "Rec.lang_type": cyr, "Rec.model_type": mobile})
        combos.append({"Rec.ocr_version": v4, "Rec.lang_type": cyr, "Rec.model_type": mobile})
    errors = []
    for i, params in enumerate(combos, 1):
        try:
            params = dict(params, **{"Global.text_score": 0.3})
            engine = RapidOCR(params=params)
            engine(dummy)                       # пробный прогон: ошибки конфигурации видны сразу
            _rapid = engine
            return _rapid
        except Exception as e:
            errors.append(f"вариант {i}: {str(e)[:90]}")
    raise EngineUnavailable(f"RapidOCR {ver} не запустился ({'; '.join(errors)}).")


def _parse_rapid(result):
    """Приводит ответ RapidOCR (новый и старый формат) к [(left, top, w, h, text)]."""
    triples = []
    boxes = getattr(result, "boxes", None)
    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is not None and txts is not None:
        scores = scores if scores is not None else [1.0] * len(txts)
        triples = list(zip(boxes, txts, scores))
    elif isinstance(result, tuple) and result and result[0]:
        triples = [(b, t, s) for b, t, s in result[0]]       # старый формат
    words = []
    for box, text, score in triples:
        text = (text or "").strip()
        if not text:
            continue
        try:
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
        except (TypeError, IndexError, ValueError):
            continue
        words.append((min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys), text))
    return words


def _enhance(img: Image.Image) -> Image.Image:
    """Второй проход: усиленный контраст и увеличение (помогает с блёклым текстом)."""
    g = ImageOps.autocontrast(img.convert("RGB"), cutoff=2)
    g = g.resize((int(g.width * 1.6), int(g.height * 1.6)), Image.LANCZOS)
    return g.filter(ImageFilter.SHARPEN)


class Label(list):
    """Строки подписи + дополнительные сведения: ранг и количество."""
    meta = None


def detect_rank(img: Image.Image, cx: float, bottom: float, unit: float):
    """Ранг по закрашенным ромбикам под подписью (мистификаторы, моды) или None."""
    gray = ImageOps.grayscale(img.convert("RGB"))
    x0, x1 = int(max(0, cx - 3.2 * unit)), int(min(gray.width, cx + 3.2 * unit))
    y0, y1 = int(bottom + 0.1 * unit), int(min(gray.height, bottom + 1.4 * unit))
    if x1 - x0 < 10 or y1 - y0 < 4:
        return None
    crop = gray.crop((x0, y0, x1, y1))
    w, h = crop.size
    px = list(crop.getdata())
    hot = [sum(1 for y in range(h) if px[y * w + x] > 140) >= 2 for x in range(w)]
    clusters, start, gap = [], None, 0
    for x, on in enumerate(hot + [False] * 6):
        if on:
            if start is None:
                start = x
            gap = 0
        elif start is not None:
            gap += 1
            if gap > 2:
                end = x - gap
                if end - start + 1 >= max(3, 0.2 * unit):
                    clusters.append((start, end))
                start = None
    return len(clusters) if len(clusters) <= 10 else None


_QTY = re.compile(r"^[xXхХ×]\s?(\d{1,3})$")


def _rapid_labels(img: Image.Image, variant: int = 0):
    import numpy as np
    if variant == 1:
        img = _enhance(img)
    engine = _get_rapid()
    arr = np.array(img.convert("RGB"))[:, :, ::-1]            # BGR, как принято в OpenCV
    words = _parse_rapid(engine(arr))
    if not words:
        return []
    unit = sorted(w[3] for w in words)[len(words) // 2]       # типичная высота строки

    qtys, text_words = [], []
    for w in words:
        mq = _QTY.match(w[4].strip())
        if mq:
            qtys.append((w[0] + w[2] / 2, w[1] + w[3] / 2, int(mq.group(1))))
        else:
            text_words.append(w)

    boxes = []
    chains = _group_words(text_words, gap_factor=0.6, boxes_out=boxes)
    labels = []
    for chain, (cx, _l, _r, top, bottom) in zip(chains, boxes):
        lines = [clean_text(t) for t in chain]
        lines = [ln for ln in lines if ln]
        if lines:
            lab = Label(lines)
            lab.meta = {"rank": None, "qty": None, "_pos": (cx, top)}   # ранги не учитываем
            labels.append(lab)

    # количество («x2») не учитываем: такие надписи просто отбрасываются выше
    return labels


def warm_up():
    """Заранее загрузить модель (чтобы первый скан не ждал). Возвращает пояснение."""
    if config.OCR_ENGINE in ("auto", "rapidocr"):
        try:
            _get_rapid()
            return "Распознавание: RapidOCR (нейросеть) готово."
        except EngineUnavailable as e:
            if config.OCR_ENGINE == "rapidocr":
                return f"{e} Использую Tesseract."
            return f"{e} Пока использую Tesseract."
    return "Распознавание: Tesseract."


def extract_labels(img: Image.Image, min_conf: float = 25.0, variant: int = 0):
    """Подписи предметов: [[строка, ...], ...]. Выбирает лучший доступный движок."""
    global last_engine, last_note
    last_note = ""
    if config.OCR_ENGINE in ("auto", "rapidocr"):
        try:
            labels = _rapid_labels(img, variant)
            last_engine = "rapidocr"
            if labels:
                return labels
            last_note = "RapidOCR ничего не нашёл — пробую Tesseract."
        except EngineUnavailable as e:
            last_note = str(e) + " Использую Tesseract."
        except Exception as e:                     # любая неожиданность не должна ломать скан
            last_note = f"Ошибка RapidOCR ({e}). Использую Tesseract."
    last_engine = "tesseract"
    return _tesseract_labels(img, min_conf)
