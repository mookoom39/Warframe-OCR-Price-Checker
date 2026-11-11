"""Точка входа: python main.py"""
import customtkinter as ctk
import pytesseract

import config
import database
from gui import MainWindow


def check_tesseract():
    warnings = []
    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD
    try:
        langs = pytesseract.get_languages(config="")
        for needed in config.OCR_LANG.split("+"):
            if needed not in langs:
                warnings.append(f"Нет языкового пакета Tesseract: '{needed}'. "
                                f"Положите {needed}.traineddata в папку tessdata.")
    except Exception:
        warnings.append("Tesseract не найден по пути: " + config.TESSERACT_CMD)
    return warnings


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    database.init_db()
    app = MainWindow(database.load_items(), check_tesseract())
    app.mainloop()


if __name__ == "__main__":
    main()
