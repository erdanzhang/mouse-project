"""Multi-camera recorder: camera manager, clip writers, recording sessions."""
from .config import load_config
from .manager import CameraManager
from .session import RecordingSession

__all__ = ["CameraManager", "RecordingSession", "load_config"]
