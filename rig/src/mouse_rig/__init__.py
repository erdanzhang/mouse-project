"""mouse-scratch-rig — multi-camera mouse nose-scratch capture + analysis.

Platform-neutral by design: the pipeline is pure Python/OpenCV, and the three
platform-specific concerns (camera capture, video encode, model compute) live
behind interfaces that are feature-detected at runtime. See docs/PLATFORM.md.
"""

__version__ = "0.0.1"
