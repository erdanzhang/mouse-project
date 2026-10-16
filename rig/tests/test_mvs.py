"""MVS backend configuration against a fake camera handle (no SDK or camera needed)."""
from types import SimpleNamespace

from mouse_rig.cameras.base import CameraInfo, CameraSettings
from mouse_rig.cameras.mvs import MvsCamera

MV_E_PARAMETER = 0x80000004


class FakeHandle:
    """Accepts every node except the enum values in ``reject`` (like a real camera)."""

    def __init__(self, reject=()):
        self.reject = set(reject)
        self.values = {}

    def _set(self, key, value):
        if (key, value) in self.reject:
            return MV_E_PARAMETER
        self.values[key] = value
        return 0

    def MV_CC_SetEnumValueByString(self, key, value):
        return self._set(key, value)

    def MV_CC_SetFloatValue(self, key, value):
        return self._set(key, value)

    def MV_CC_SetBoolValue(self, key, value):
        return self._set(key, value)

    def MV_CC_SetIntValueEx(self, key, value):
        return self._set(key, value)

    def MV_CC_GetIntValueEx(self, key, out):
        out.nCurValue = self.values.get(key, 1)
        return 0


def _camera(handle, trigger="line0"):
    cam = object.__new__(MvsCamera)
    cam.info = CameraInfo(backend="mvs", serial="DB0000001", model="MV-CS016-10UC", is_color=True)
    cam.settings = CameraSettings(trigger=trigger)
    cam.warnings = []
    cam._cam = handle
    cam._sdk = SimpleNamespace(MVCC_INTVALUE_EX=lambda: SimpleNamespace(nCurValue=0))
    cam._configure()
    return cam


def test_frame_start_trigger():
    cam = _camera(FakeHandle())
    assert cam.warnings == []
    assert cam._cam.values["TriggerSelector"] == "FrameStart"
    assert cam._cam.values["TriggerSource"] == "Line0"


def test_cs_series_falls_back_to_frame_burst_start():
    # MV-CS016-10UC: TriggerSelector only offers FrameBurstStart
    cam = _camera(FakeHandle(reject={("TriggerSelector", "FrameStart")}))
    assert cam.warnings == []
    assert cam._cam.values["TriggerSelector"] == "FrameBurstStart"
    assert cam._cam.values["AcquisitionBurstFrameCount"] == 1
    assert cam._cam.values["TriggerMode"] == "On"


def test_no_frame_trigger_selector_warns():
    cam = _camera(FakeHandle(reject={("TriggerSelector", "FrameStart"), ("TriggerSelector", "FrameBurstStart")}))
    assert any("TriggerSelector" in w for w in cam.warnings)
