"""Local web UI for camera preview and one-click recording."""
from .app import RecorderApp, make_server, serve

__all__ = ["RecorderApp", "make_server", "serve"]
