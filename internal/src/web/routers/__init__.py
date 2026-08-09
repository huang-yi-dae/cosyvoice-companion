"""Route modules for the web app (architecture review §4 — app.py slimming).

Each module exposes ``build_router(cfg, ...)`` returning a configured
``fastapi.APIRouter``. app.py stays the composition root: it constructs cfg /
services / jobs and includes these routers. Passing dependencies in explicitly
(instead of importing app.py) keeps the modules import-cycle-free and testable.
"""
