"""Run the JavaScript tests for the Wawasan/Agen/Tenant pages via Node.
The tests are in `frontend/src/test/js/uji_wawasan.js`; the reason for this wrapper is documented in `jalankan_uji_js.py`.
Run: py uji_wawasan_js.py
"""
import sys

from jalankan_uji_js import jalankan

if __name__ == "__main__":
    sys.exit(jalankan("uji_wawasan.js", "Wawasan"))
