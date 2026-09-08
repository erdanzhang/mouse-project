"""Platform-specific backends, each behind a small interface.

* frame_source — where frames come from (File / Webcam for dev, GenICam for real cameras)
* encoder      — how frames are written (NVENC / VideoToolbox / x265 / OpenCV)
* device       — which compute device torch models run on (cuda / mps / cpu)

Nothing here is imported at package import time; each backend lazily imports its
heavy/platform dependency so the base install stays cross-platform.
"""
