"""Media types of export files (Excel/Word report exports and per-device exports).
Defined once: one wrong letter makes the browser download a file Excel refuses to open, with no error.
"""
XLSX = ("application/vnd.openxmlformats-officedocument."
        "spreadsheetml.sheet")
DOCX = ("application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document")
