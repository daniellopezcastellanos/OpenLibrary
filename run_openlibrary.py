"""Arranca la app OpenLibrary desde el código fuente:  python run_openlibrary.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from openlibrary import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
