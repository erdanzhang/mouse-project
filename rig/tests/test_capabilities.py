"""M0 smoke test — must pass on macOS, Windows, or Linux."""
from mouse_rig.capabilities import format_report, probe


def test_probe_reports_platform():
    caps = probe()
    assert caps.os and caps.machine and caps.python
    assert isinstance(caps.ffmpeg_encoders, list)
    assert caps.recommended_device in ("cuda", "mps", "cpu")
    assert caps.recommended_encoder  # some encoder is always recommended


def test_report_is_nonempty_text():
    text = format_report(probe())
    assert isinstance(text, str)
    assert "platform capabilities" in text
    assert "encoder" in text
