"""Reply shapes shared by more than one router.
`balas_ditolak` is shared so the 409 code cannot drift between command dispatch and SoT.
"""
import json

from fastapi import Response


def balas_ditolak(e):
    """A deliberate NSM refusal: 409, not 500. Java treats 500 as "NSM is broken" and 409 as
    "NSM refused, and the reason can be shown to the user".
    """
    return Response(content=json.dumps({"ok": False, "ditolak": str(e)}),
                    media_type="application/json", status_code=409)
