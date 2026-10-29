# -*- coding: utf-8 -*-
"""Stub of poe-mapmaker's modules.config_manager.ConfigManager.

Implements the subset of the API the poe-workflow test suite touches:
  - ConfigManager(path): loads existing file or starts empty
  - get(section, key, default="")
  - set(section, key, value)
  - flush() / _atomic_save(): persist to disk (atomic)
  - _config_path: absolute path of the backing file
  - get_affix_entries(section): list of {"keyword","is_regex","tier"} dicts

Behaviour mirrors the real implementation closely enough for the tests:
section/option case is preserved, writes are atomic, and reload-from-disk
reflects previously flushed values.
"""
import configparser
import os
import tempfile


class ConfigManager:
    def __init__(self, config_path=None):
        self._config_path = os.path.abspath(config_path) if config_path else None
        self._cfg = configparser.ConfigParser()
        self._cfg.optionxform = str  # preserve option-name case
        if config_path and os.path.isfile(config_path):
            self._load()

    def _load(self):
        with open(self._config_path, "r", encoding="utf-8") as f:
            text = f.read()
        # The real ConfigManager strips raw affix sections before handing the
        # remaining text to configparser (affix lines are not key=value). Mirror
        # that defensively so a poe_config.txt copy with affix sections still
        # parses instead of raising ParsingError.
        text = self._strip_affix_sections(text)
        try:
            self._cfg.read_string(text)
        except configparser.Error:
            self._cfg = configparser.ConfigParser()
            self._cfg.optionxform = str

    @staticmethod
    def _strip_affix_sections(text):
        out, skipping = [], False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                name = stripped[1:-1].strip()
                if name.lower().startswith("affix"):
                    skipping = True
                    continue
                skipping = False
            if skipping:
                continue
            out.append(line)
        return "\n".join(out)

    def get(self, section, key, default=""):
        try:
            return self._cfg.get(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError, KeyError):
            return default

    def set(self, section, key, value):
        if not self._cfg.has_section(section):
            self._cfg.add_section(section)
        self._cfg.set(section, key, str(value))

    def flush(self):
        self._atomic_save()

    def _atomic_save(self):
        if not self._config_path:
            return
        directory = os.path.dirname(self._config_path) or "."
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                self._cfg.write(f)
            os.replace(tmp, self._config_path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def get_affix_entries(self, section):
        if not self._cfg.has_section(section):
            return []
        entries = []
        regex_special = set(r"\.^$*+?{}[]|()")
        for key, _val in self._cfg.items(section):
            entries.append({
                "keyword": key,
                "is_regex": any(c in key for c in regex_special),
                "tier": "ALL",
            })
        return entries
