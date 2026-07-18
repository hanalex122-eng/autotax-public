"""Single source of truth for the AutoTax product version.

Bump the version ONLY here. Consumers:
  - backend: FastAPI app metadata (OpenAPI /docs) and the /health endpoint import __version__ from here.
  - frontend: reads the version at runtime from /health (which comes from here), so no hardcoded UI version.

Not related: the ELSTER sub-app version (declaration.py) and the desktop-Watcher auto-update version
(WATCHER_LATEST_VERSION) are separate components and intentionally NOT sourced from here.
"""
__version__ = "5.5.5"
