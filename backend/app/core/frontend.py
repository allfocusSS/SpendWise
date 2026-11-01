"""Serve the built React app (Vite `dist`) from FastAPI, for the single production container.

Only active when FRONTEND_DIST is set. In local development the Vite dev server serves the
frontend and proxies /api to the backend, so none of this runs.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.convertors import Convertor, register_url_convertor


class _ClientPathConvertor(Convertor[str]):
    """Any path except /api and /api/...

    The fallback route must not even partially match API paths: a partial match turns
    "POST /api/unknown" into 405 instead of 404, and would change the API's behaviour.
    """

    regex = r"(?!api(?:/|$)).*"

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return value


register_url_convertor("client_path", _ClientPathConvertor())


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve `dist`: hashed bundles under /assets, root files (favicon), index.html for the rest.

    Call after the API routers are included so /api, /docs and /openapi.json match first.
    """
    dist = dist.resolve()
    index = dist / "index.html"
    if not index.is_file():
        raise RuntimeError(f"FRONTEND_DIST={dist} has no index.html. Build the frontend first.")

    # A missing bundle is a 404 here, not index.html (which the browser would try to run as JS).
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="frontend-assets")

    @app.api_route("/{path:client_path}", methods=["GET", "HEAD"], include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist):
            return FileResponse(file)
        # Client-side routes (/transactions, /categories, ...) load the app, which routes itself.
        # no-cache: a new deploy's index.html (and its new bundle names) is picked up at once.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
