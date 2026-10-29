# -*- coding: utf-8 -*-
"""Stub of poe-mapmaker's modules.coordinate_engine.CoordinateEngine.

Only needs a constructable object holding the config getter; the poe-workflow
suite never calls its methods (it is assembled by conftest.build_stack and passed
to the stub MainWindow, which ignores it).
"""
class CoordinateEngine:
    def __init__(self, config_getter, *args, **kwargs):
        self._get = config_getter

    def stop(self):
        pass
