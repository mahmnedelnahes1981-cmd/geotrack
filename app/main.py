from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import PACKAGE_DIR, get_settings
from app.routers import field, handover, projects, quotes, web

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")
app.include_router(web.router)
app.include_router(quotes.router)
app.include_router(projects.router)
app.include_router(handover.router)
app.include_router(field.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}
