import importlib.metadata
import runpy
import tomllib
from pathlib import Path

import stumble_radio


def test_module_version_uses_installed_metadata(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "9.2.1")
    assert runpy.run_path(stumble_radio.__file__)["__version__"] == "9.2.1"


def test_source_version_matches_project_version(monkeypatch):
    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    project = tomllib.loads(Path("pyproject.toml").read_text())
    assert runpy.run_path(stumble_radio.__file__)["__version__"] == project["project"]["version"]
