from pathlib import Path

from stumble_radio import updates


def test_installed_version_reads_package_metadata(monkeypatch):
    monkeypatch.setattr(updates.importlib.metadata, "version", lambda _name: "9.2.1")
    assert updates.installed_version() == "9.2.1"
    monkeypatch.setattr(
        updates.importlib.metadata,
        "version",
        lambda _name: (_ for _ in ()).throw(updates.importlib.metadata.PackageNotFoundError),
    )
    assert updates.installed_version() != ""   # falls back to the module version


def test_parse_version_requires_numeric_segments():
    assert updates.parse_version("v0.1.3") == (0, 1, 3)
    assert updates.parse_version("1.2") == (1, 2)
    assert updates.parse_version("") is None
    assert updates.parse_version("prerelease") is None
    assert updates.parse_version("0.1.3b2") is None


def test_is_newer_compares_numerically():
    assert updates.is_newer("0.2", "0.1.9")
    assert updates.is_newer("0.1.4", "0.1.3")
    assert not updates.is_newer("0.1.3", "0.1.3")
    assert not updates.is_newer("0.1.2", "0.1.3")
    assert not updates.is_newer("garbage", "0.1.3")


def test_tag_constants_match_install_script():
    assert updates.SOURCE_ARCHIVE in Path("install.sh").read_text()
    assert updates.REPO_TAGS_URL.startswith("https://api.github.com/repos/")
