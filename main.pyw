"""Запуск без чёрного окна: двойной клик по этому файлу."""
import os
import sys
import traceback

os.chdir(os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
         else os.path.dirname(os.path.abspath(__file__)))
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

try:
    import main
    main.main()
except Exception:
    with open("error.log", "w", encoding="utf-8") as f:
        f.write(traceback.format_exc())
