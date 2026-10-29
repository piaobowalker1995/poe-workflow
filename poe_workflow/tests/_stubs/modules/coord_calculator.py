# -*- coding: utf-8 -*-
"""Stub of poe-mapmaker's modules.coord_calculator.CoordCalculator.

Only the four anchor-resolution branch behaviours exercised by
test_workflow_engine_phase_d.py are implemented. The full real calculator needs
a CoordinateEngine + DualStorage + WindowDetector, which we deliberately do not
pull in; the tests construct the class with __new__ and monkeypatch the leaf
methods, so the default leaf methods just return (0, 0).
"""
import re  # noqa: F401  (kept for parity; not used by the stub branches)


class CoordCalculator:
    DERIVED_STASH_PREFIX = "仓库页"
    CURRENCY_ANCHOR_PREFIX = "通货:"
    INVENTORY_ANCHOR_PREFIX = "背包:"

    def __init__(self, engine=None):
        self._engine = engine

    def get_absolute_position(self, point_name):
        name = point_name or ""
        if name.startswith(self.DERIVED_STASH_PREFIX):
            suffix = name[len(self.DERIVED_STASH_PREFIX):]
            if suffix.isdigit():
                return self.stash_tab_position(int(suffix))
            return (0, 0)
        if name.startswith(self.CURRENCY_ANCHOR_PREFIX):
            return self._resolve_plain(name[len(self.CURRENCY_ANCHOR_PREFIX):])
        if name.startswith(self.INVENTORY_ANCHOR_PREFIX):
            parts = name[len(self.INVENTORY_ANCHOR_PREFIX):].split(",")
            if len(parts) == 2 and all(p.strip().lstrip("-").isdigit() for p in parts):
                try:
                    return self.inventory_cell_position(
                        int(parts[0].strip()), int(parts[1].strip()))
                except Exception:
                    return (0, 0)
            return (0, 0)
        return self._resolve_plain(name)

    def stash_tab_position(self, tab_index):
        return (0, 0)

    def inventory_cell_position(self, row, col):
        return (0, 0)

    def _resolve_plain(self, point_name):
        return (0, 0)
