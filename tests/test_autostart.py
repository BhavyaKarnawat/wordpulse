import sys
import pytest
from src.core import autostart

TEST_KEY = r"Software\WordPulseTest\Run"  # throwaway key, never the real Run key


@pytest.fixture
def test_key():
    yield TEST_KEY
    if autostart.winreg:
        try:
            autostart.winreg.DeleteKey(autostart.winreg.HKEY_CURRENT_USER, TEST_KEY)
            autostart.winreg.DeleteKey(autostart.winreg.HKEY_CURRENT_USER, r"Software\WordPulseTest")
        except OSError:
            pass


def test_launch_command_points_at_this_app():
    cmd = autostart.launch_command()
    assert cmd.startswith('"')
    assert "run_wordpulse.py" in cmd or cmd.lower().endswith('.exe"')


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry only")
def test_toggle_round_trip(test_key):
    assert autostart.is_enabled(test_key) is False
    assert autostart.set_enabled(True, test_key) is True
    assert autostart.is_enabled(test_key) is True
    assert autostart.set_enabled(False, test_key) is False
    assert autostart.set_enabled(False, test_key) is False  # turning off twice is fine
