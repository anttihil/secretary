"""Cache policy for the built frontend."""

import os

from fastapi import Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope


class CacheControlledStaticFiles(StaticFiles):
    """Cache hashed build assets forever; always revalidate everything else.

    Starlette sets etag/last-modified but no Cache-Control, which lets browsers
    apply heuristic freshness and serve a stale index.html (and the old asset
    hashes it points at) long after a deploy.
    """

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        if scope["path"].startswith("/assets/"):
            response.headers["cache-control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["cache-control"] = "no-cache"
        return response
