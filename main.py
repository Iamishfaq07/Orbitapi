# Default entrypoint runs the public gateway:  uvicorn main:app
from orbitapi.gateway_app import app  # noqa: F401
