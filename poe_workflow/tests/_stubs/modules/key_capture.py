# -*- coding: utf-8 -*-
"""Stub of poe-mapmaker's modules.key_capture (InputCaptureHook + _user32).

Only what test_workflow_presskey_capture.py exercises:
  - the module-level `_user32` handle (monkeypatched by the test)
  - InputCaptureHook._held_modifiers(cls, *args) -> list of held modifier labels
"""
# Module-level handle to the Windows user32 API. The test monkeypatches this
# attribute on the `kc` module object.
_user32 = None


class InputCaptureHook:
    # VK code -> modifier label (matches the real key_capture mapping).
    _VK_MODIFIERS = {
        0x11: "Ctrl", 0xA2: "Ctrl", 0xA3: "Ctrl",
        0xA4: "Alt", 0xA5: "Alt",
        0xA0: "Shift", 0xA1: "Shift",
    }

    def __init__(self, *args, **kwargs):
        self._capturing = False

    def start(self):
        self._capturing = True

    def stop(self):
        self._capturing = False

    @classmethod
    def _held_modifiers(cls, *args, **kwargs):
        result = []
        u = _user32
        if u is None:
            return result
        for vk, label in cls._VK_MODIFIERS.items():
            try:
                state = u.GetAsyncKeyState(vk)
            except Exception:
                continue
            if state & 0x8000 and label not in result:
                result.append(label)
        return result
