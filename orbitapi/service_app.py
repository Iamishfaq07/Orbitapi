"""The OrbitAPI core service.

Runs on the internal network behind the gateway. It reads the caller's identity
from the `X-Orbit-*` headers the gateway injects and serves the domain APIs.
"""
import copy
import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import config, core, seed
from .security import is_internal, login_limiter
from .routers import (admin, apikeys, billing, collab, commerce, files, integrations,
                      legacy, reports, users, workspace)

app = FastAPI(title="OrbitAPI Core", version=config.VERSION,
              description="Internal core service. Reached through the OrbitAPI gateway.")


@app.on_event("startup")
def _startup() -> None:
    seed.seed()


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={
        "error": type(exc).__name__, "message": str(exc),
        "trace": traceback.format_exception(type(exc), exc, exc.__traceback__),
    })


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": "core", "version": config.VERSION}


@app.post("/internal/reset", tags=["internal"], include_in_schema=False)
def reset_demo_data(request: Request):
    """Reload the sample dataset. Restricted to the internal network."""
    if not is_internal(request):
        raise HTTPException(status_code=404, detail="Not Found")
    seed.seed()
    login_limiter.hits.clear()
    return {"message": "Sample data reloaded"}


app.include_router(core.router)
for r in (users, workspace, commerce, files, integrations, reports,
          apikeys, collab, billing, admin):
    app.include_router(r.router)
app.include_router(legacy.v1)
app.include_router(legacy.internal)
app.include_router(legacy.misc)
