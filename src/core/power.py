"""Windows power state management to keep screen awake during music playback."""
import ctypes
import sys


class PowerManager:
    """Manages thread execution states on Windows to prevent screen dimming/sleeping."""

    # Windows kernel32 execution state flags
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_DISPLAY_REQUIRED = 0x00000002

    def __init__(self):
        self._is_inhibited = False
        self._is_windows = sys.platform == "win32"

    @property
    def is_inhibited(self) -> bool:
        return self._is_inhibited

    def prevent_sleep(self, enable: bool) -> bool:
        """Enables or disables screen keep-awake state."""
        if not self._is_windows:
            self._is_inhibited = enable
            return True

        try:
            if enable:
                flags = self.ES_CONTINUOUS | self.ES_DISPLAY_REQUIRED | self.ES_SYSTEM_REQUIRED
                result = ctypes.windll.kernel32.SetThreadExecutionState(flags)
                self._is_inhibited = (result != 0)
                return self._is_inhibited
            else:
                result = ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)
                self._is_inhibited = False
                return True
        except Exception:
            self._is_inhibited = False
            return False

    def __del__(self):
        # Reset state upon cleanup
        if self._is_inhibited:
            self.prevent_sleep(False)

