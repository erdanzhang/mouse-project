"""Mouse nose-scratch video analyzer (POC).

Pipeline: detect mice -> track (stable IDs) -> flag candidate scratch windows
by motion -> confirm with a vision LLM -> render annotated video + JSON report.
"""

__version__ = "0.1.0"
