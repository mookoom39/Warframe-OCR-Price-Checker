"""Поиск предметов из БД в распознанном тексте (быстрый нечёткий поиск)."""
import difflib
import re

import config

_LAT2CYR = str.maketrans("abcehkmoptxy", "авсенкмортху")
_CYR2LAT = str.maketrans("авсенкмортху", "abcehkmoptxy")
_TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё]+")
MIN_FUZZY_LEN = 7      # короткие названия принимаем только при точном совпадении
LEN_WINDOW = 3         # сравниваем только ключи близкой длины
MAX_RESULTS = 15


def _edits(a: str, b: str) -> int:
    """Сколько символов нужно исправить, чтобы a превратилось в b."""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(max(i2 - i1, j2 - j1)
               for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")


def _max_edits(n: int) -> int:
    """Допустимое число ошибок распознавания в зависимости от длины названия."""
    return 1 if n < 12 else 2 if n < 26 else 3


def norm_ru(s: str) -> str:
    s = s.lower().replace("ё", "е").replace("й", "и").translate(_LAT2CYR)
    return re.sub(r"[^а-я0-9]", "", s)


def norm_en(s: str) -> str:
    s = s.lower().translate(_CYR2LAT)
    return re.sub(r"[^a-z0-9]", "", s)


_PRIME = norm_ru("Прайм")
_BLUEPRINT = norm_ru("Чертёж")


class _Index:
    """Ключи, сгруппированные по числу слов; внутри — по длине."""

    def __init__(self):
        self.maps = {}      # n -> {ключ: (ru, slug)}
        self.by_len = {}    # n -> {длина: [ключи]}

    def add(self, n, key, value):
        if not key or n == 0:
            return
        m = self.maps.setdefault(n, {})
        if key not in m:
            self.by_len.setdefault(n, {}).setdefault(len(key), []).append(key)
        m[key] = value

    def lookup(self, n, window, cutoff):
        m = self.maps[n]
        if window in m:
            return m[window], 1.0
        if len(window) < MIN_FUZZY_LEN:
            return None
        sm = difflib.SequenceMatcher(None)
        sm.set_seq2(window)
        limit = _max_edits(len(window))
        best, best_key = None, None
        lens = self.by_len[n]
        for L in range(len(window) - LEN_WINDOW, len(window) + LEN_WINDOW + 1):
            for key in lens.get(L, ()):
                sm.set_seq1(key)
                if sm.real_quick_ratio() < cutoff or sm.quick_ratio() < cutoff:
                    continue
                r = sm.ratio()
                if r < cutoff:
                    continue
                e = _edits(key, window)
                if e > limit:           # слишком много отличий: это другой предмет
                    continue
                rank = (e, -r)
                if best is None or rank < best:
                    best, best_key = rank, key
        if best_key is None:
            return None
        return m[best_key], difflib.SequenceMatcher(None, window, best_key).ratio()


class Matcher:
    def __init__(self, items):
        ru_ord, ru_sorted, en_ord, ru_np = _Index(), _Index(), _Index(), _Index()
        for _id, ru, slug in items:
            rt = [t for t in (norm_ru(x) for x in _TOKEN.findall(ru)) if t]
            if rt:
                ru_ord.add(len(rt), "".join(rt), (ru, slug))
                ru_sorted.add(len(rt), "".join(sorted(rt)), (ru, slug))
                # вариант без слова «Прайм» (OCR иногда его теряет), но только если
                # остались как минимум название и часть
                np_ = [t for t in rt if t != _PRIME]
                if len(np_) < len(rt) and len(np_) >= 2 and _BLUEPRINT not in rt:
                    ru_np.add(len(np_), "".join(sorted(np_)), (ru, slug))
            et = [t for t in (norm_en(x) for x in re.findall(r"[a-z]+", slug)) if t]
            if et:
                en_ord.add(len(et), "".join(et), (ru, slug))
        # (индекс, нормализатор, сортировать ли слова). Сортировка нужна, когда OCR
        # перепутал порядок слов ("Акариус ТВОЛ Прайм" вместо "Акариус Прайм Ствол").
        self.names = [(norm_ru(ru), ru) for _id, ru, _slug in items]
        self.indexes = [(ru_ord, norm_ru, False), (ru_sorted, norm_ru, True),
                        (ru_np, norm_ru, True), (en_ord, norm_en, False)]

    def find(self, lines, cutoff=config.FUZZY_CUTOFF):
        """[{'ru_name','slug','score','source'}] без дублей, в порядке появления."""
        def clean(tokens):
            # одиночные "x"/"х" остаются от множителя "x2"
            return [t for t in tokens if t.lower() not in ("x", "х")]

        token_lines = [clean(_TOKEN.findall(ln)) for ln in lines]

        # Подпись может занимать 1-3 строки: смотрим одиночные строки и склейки
        # из 2-3 соседних (окно обязано начинаться в первой и кончаться в последней).
        spans = [(i, i) for i in range(len(token_lines))]
        for length in (2, 3):
            spans += [(i, i + length - 1) for i in range(len(token_lines) - length + 1)]

        cands = []   # (score, n, end, positions, ru, slug, source)
        for first, last in spans:
            tokens, pos = [], []
            for li in range(first, last + 1):
                for k, t in enumerate(token_lines[li]):
                    tokens.append(t)
                    pos.append((li, k))
            if not tokens:
                continue
            for index, norm, do_sort in self.indexes:
                for n in index.maps:
                    for j in range(len(tokens) - n + 1):
                        wp = pos[j:j + n]
                        if last > first and not (wp[0][0] == first and wp[-1][0] == last):
                            continue
                        parts = [norm(t) for t in tokens[j:j + n]]
                        if not all(parts):
                            continue
                        window = "".join(sorted(parts) if do_sort else parts)
                        res = index.lookup(n, window, cutoff)
                        if res:
                            (ru, slug), score = res
                            cands.append((score, n, max(wp), wp, ru, slug,
                                          " ".join(tokens[j:j + n])))

        # Жадный выбор: точнее -> длиннее -> ближе к концу подписи
        # (в начале бывает приставка «Чертёж:», которая не часть названия)
        used, accepted = set(), []
        for score, n, end, wp, ru, slug, src in sorted(
                cands, key=lambda c: (-c[0], -c[1], tuple(-x for x in c[2]))):
            if used & set(wp):
                continue
            used |= set(wp)
            accepted.append((min(wp), score, ru, slug, src))

        found = {}
        for order, (_start, score, ru, slug, src) in enumerate(sorted(accepted)):
            prev = found.get(slug)
            if prev is None:
                found[slug] = {"ru_name": ru, "slug": slug, "score": score,
                               "source": src, "order": order}
            elif score > prev["score"]:
                prev["score"], prev["source"] = score, src
        # слова надписи, которые не вошли ни в одно найденное название (например «Умбра»)
        left = [t for li, toks in enumerate(token_lines) for k, t in enumerate(toks)
                if (li, k) not in used and len(norm_ru(t)) >= 4]
        for m in found.values():
            m["leftover"] = left
        return sorted(found.values(), key=lambda m: m["order"])[:MAX_RESULTS]

    def suggest(self, base_name, words, limit=3):
        """Названия из базы, где есть и найденное имя, и оставшиеся слова."""
        need = [norm_ru(t) for t in _TOKEN.findall(base_name) if norm_ru(t)]
        need += [norm_ru(w) for w in words]
        hits = [ru for key, ru in self.names if all(n in key for n in need)]
        return sorted(hits, key=len)[:limit]

    def find_labels(self, labels, cutoff=config.FUZZY_CUTOFF):
        """labels: [[строка, ...], ...] — по одной подписи на предмет.
        Возвращает (найденные предметы, подписи без совпадения)."""
        per_label = [self.find(lines, cutoff) for lines in labels]
        consumed = set()

        # Иконка может «разорвать» подпись на два куска («Чертёж Заку» и «Прайм
        # Нейрооптика»). Пробуем склеить пары ненайденных кусков; принимаем только
        # если получилось полное настоящее название.
        missing = [i for i, r in enumerate(per_label) if not r]
        if 2 <= len(missing) <= 14:
            for x, i in enumerate(missing):
                if i in consumed or per_label[i]:
                    continue
                for j in missing[x + 1:]:
                    if j in consumed or per_label[j]:
                        continue
                    for lines in (list(labels[i]) + list(labels[j]),
                                  list(labels[j]) + list(labels[i])):
                        res = self.find(lines, cutoff)
                        if res:
                            per_label[i] = res
                            consumed.add(j)
                            break
                    if per_label[i]:
                        break

        # то же для трёх кусков (название в 3 строки, разорванное иконкой)
        rest = [i for i in missing if i not in consumed and not per_label[i]]
        if 3 <= len(rest) <= 10:
            from itertools import combinations
            for trio in combinations(rest, 3):
                if any(per_label[i] or i in consumed for i in trio):
                    continue
                lines = [ln for i in trio for ln in labels[i]]
                res = self.find(lines, cutoff)
                if res:
                    per_label[trio[0]] = res
                    consumed.update(trio[1:])

        found, unmatched, order = {}, [], 0
        for idx, (lines, res) in enumerate(zip(labels, per_label)):
            if idx in consumed:
                continue
            if not res:
                unmatched.append(" ".join(lines))
            meta = getattr(lines, "meta", None) or {}
            rank, qty = meta.get("rank"), 1
            for m in res:
                key = (m["slug"], rank)
                prev = found.get(key)
                if prev is None:
                    found[key] = dict(m, order=order, meta={"rank": rank, "qty": qty})
                    order += 1
                else:   # такой же предмет повторился — показываем один раз
                    if m["score"] > prev["score"]:
                        prev["score"], prev["source"] = m["score"], m["source"]
        matches = sorted(found.values(), key=lambda m: m["order"])[: MAX_RESULTS * 4]
        return matches, unmatched
