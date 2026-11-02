"""Run the Incidents page JavaScript tests through Node.

The tests live in `frontend/src/test/js/uji_insiden.js`; the reason for this
wrapper is documented in `jalankan_uji_js.py`.

Run: py uji_insiden_js.py
"""
import sys

from jalankan_uji_js import jalankan

if __name__ == "__main__":
    sys.exit(jalankan("uji_insiden.js", "Insiden"))
