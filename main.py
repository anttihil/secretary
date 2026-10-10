"""FastAPI entry point: assemble backend routers and serve the built frontend."""

from fastapi import FastAPI

from backend.paths import PROJECT_DIR
from backend.routes import (
    directories,
    glossary,
    migration,
    notes,
    recordings,
    settings,
    websocket,
)
from backend.static_files import CacheControlledStaticFiles
from backend.worker import lifespan

app = FastAPI(lifespan=lifespan)

for router in (
    recordings.router,
    settings.router,
    notes.router,
    migration.router,
    directories.router,
    glossary.router,
    websocket.router,
):
    app.include_router(router)

# Keep this mount last so API and WebSocket routes take precedence.
app.mount(
    "/",
    CacheControlledStaticFiles(directory=PROJECT_DIR / "static", html=True),
    name="static",
)
