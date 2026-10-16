"""Hardware-trigger sync: give every frame a shared trigger index.

When all cameras run with ``trigger: "line0"``, the Arduino sends one pulse to every
camera at the same instant. Pulse p makes one frame in each camera. The recorder
cuts clips by trigger index, not by arrival time, so frame i of clip k is the same
instant in every camera::

    clip k, frame i  <->  trigger index  start + k * frames_per_clip + i

Each camera counts its own frames (``frame_id``), so the counters of two cameras
differ by an offset. ``TriggerClock`` finds the offset in one of two ways:

* Gated (exact): the recorder stops the Arduino over USB serial, opens the cameras,
  calls ``arm_gate()``, and starts the Arduino again. The first frame of every camera
  is then the same pulse, so it gets index 0.
* Arrival time (fallback, no serial link): frames of the same pulse arrive within a
  few milliseconds (one period at 60 fps is 16.7 ms). For its first 30 frames, a
  camera compares its arrival time with the newest frame of another camera and takes
  the most common answer.

After that, the index is ``frame_id + offset``. A frame lost on the USB link leaves a
gap in ``frame_id``, so the index stays correct. A missed trigger (no frame and no
counter step) shows up as a gap of about two periods in the camera timestamps; the
index then steps one more and ``corrections`` counts it.
"""
from __future__ import annotations

import collections
import statistics
import threading
from dataclasses import dataclass, field


@dataclass
class _CamState:
    index: int
    frame_id: int
    host_time: float
    device_ts: int
    frames: int = 1
    votes: collections.Counter = field(default_factory=collections.Counter)
    dev_intervals: collections.deque = field(default_factory=lambda: collections.deque(maxlen=240))


class TriggerClock:
    VOTE_FRAMES = 30

    def __init__(self, fps: float):
        self.nominal_period = 1.0 / max(1e-6, float(fps))
        self.gated = False                      # True after arm_gate(): offsets are exact
        self.corrections = 0                    # missed-trigger corrections (should stay 0)
        self._lock = threading.Lock()
        self._cams: dict[str, _CamState] = {}
        self._newest: int | None = None
        self._intervals: collections.deque = collections.deque(maxlen=240)

    @property
    def newest(self) -> int | None:
        """The highest trigger index seen so far on any camera."""
        return self._newest

    @property
    def period(self) -> float:
        """Measured trigger period in seconds (mean frame interval), or 1/fps at first.

        Arrival intervals are skewed (USB delivers some frames late, the next ones
        catch up), so their median is biased (16.8 ms for a 16.66 ms trigger on the
        lab PC). The mean is not, once stalls and catch-up bursts are left out.
        """
        if len(self._intervals) >= 30:
            median = statistics.median(self._intervals)
            kept = [x for x in self._intervals if 0.5 * median < x < 1.5 * median]
            return statistics.fmean(kept) if kept else median
        return self.nominal_period

    def arm_gate(self) -> None:
        """Call while the trigger is stopped: the next frame of every camera is index 0."""
        with self._lock:
            self._cams.clear()
            self._newest = None
            self.gated = True

    def index(self, cam_id: str, frame_id: int, host_time: float, device_ts: int = 0) -> int:
        with self._lock:
            period = self.period
            me = self._cams.get(cam_id)
            if me is None:
                if self.gated:
                    idx = 0
                else:
                    cross = self._from_other_camera(cam_id, host_time, period)
                    idx = cross if cross is not None else (0 if self._newest is None else self._newest + 1)
                me = self._cams[cam_id] = _CamState(idx, frame_id, host_time, device_ts)
                if frame_id >= 0 and not self.gated:
                    me.votes[idx - frame_id] += 1
            elif frame_id < 0 or frame_id <= me.frame_id:
                # no frame counter, or the counter restarted: use the arrival time only
                cross = self._from_other_camera(cam_id, host_time, period)
                own = me.index + max(1, round((host_time - me.host_time) / period))
                idx = cross if cross is not None else own
                me.votes.clear()
                me.frames = self.VOTE_FRAMES
            else:
                step = frame_id - me.frame_id
                if step == 1:
                    self._intervals.append(host_time - me.host_time)
                idx = me.index + step + self._missed(me, step, device_ts)
                if not self.gated and me.frames < self.VOTE_FRAMES:
                    cross = self._from_other_camera(cam_id, host_time, period)
                    if cross is not None:
                        me.votes[cross - frame_id] += 1
                        idx = frame_id + me.votes.most_common(1)[0][0]
            me.index, me.frame_id, me.host_time = idx, frame_id, host_time
            me.device_ts = device_ts
            me.frames += 1
            if self._newest is None or idx > self._newest:
                self._newest = idx
            return idx

    def _missed(self, me: _CamState, step: int, device_ts: int) -> int:
        """Missed triggers between two frames, from the camera timestamps (0 if unknown)."""
        if device_ts <= 0 or me.device_ts <= 0 or device_ts <= me.device_ts:
            return 0
        delta = device_ts - me.device_ts
        if step == 1:
            me.dev_intervals.append(delta)
        if len(me.dev_intervals) < 30:
            return 0
        extra = delta / statistics.median(me.dev_intervals) - step
        if 0.75 < extra < 2.5:          # a longer gap means the trigger stopped: no pulses, no frames
            self.corrections += 1
            return round(extra)
        return 0

    def _from_other_camera(self, cam_id: str, host_time: float, period: float) -> int | None:
        """Index predicted from the newest frame of another camera (within 2 periods)."""
        best = None
        for other_id, st in self._cams.items():
            if other_id == cam_id or abs(host_time - st.host_time) > 2 * period:
                continue
            if best is None or st.host_time > best.host_time:
                best = st
        if best is None:
            return None
        return best.index + round((host_time - best.host_time) / period)


@dataclass
class SyncPlan:
    """The trigger-index window of one recording, shared by the writers of all cameras."""
    frames_per_clip: int
    start: int | None = None        # first trigger index in the recording
    end: int | None = None          # first trigger index after the recording (set at stop)
    max_frames: int | None = None   # timed recording: number of trigger indices to record
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def resolve_start(self, index: int) -> int:
        """Return the start index; the first frame sets it if the trigger was not running at start."""
        with self._lock:
            if self.start is None:
                self.start = index
            return self.start

    def window_end(self) -> int | None:
        """First trigger index after the recording: from stop, or start + max_frames if timed."""
        ends = [self.end]
        if self.max_frames and self.start is not None:
            ends.append(self.start + self.max_frames)
        ends = [e for e in ends if e is not None]
        return min(ends) if ends else None

    def as_dict(self) -> dict:
        return {"frames_per_clip": self.frames_per_clip, "first_trigger_index": self.start,
                "end_trigger_index": self.window_end(), "timed_frames": self.max_frames}
