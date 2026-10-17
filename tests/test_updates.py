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


class FakeClient:
    def __init__(self, payload=None, error=False, headers=None):
        self.payload = payload if payload is not None else [{"name": "v0.1.4"}, {"name": "v0.1.3"}]
        self.error = error
        self.headers = headers

    async def __aenter__(self):
        if self.error:
            raise OSError("offline")
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, headers=None):
        if headers is not None:
            self.headers = headers
        if self.error:
            raise RuntimeError("boom")
        return FakeResponse(self.payload)


class FakeResponse:
    def __init__(self, hidden):
        self._hidden = hidden

    def raise_for_status(self):
        return None

    def json(self):
        return self._hidden


def test_fetch_latest_version_returns_newest_numeric_tag(monkeypatch):
    client = FakeClient([{"name": "cron-runner"}, {"name": "v0.2.0"}, {"name": "v0.1.3"}])

    def fake_async_client(*args, **kwargs):
        client.headers = kwargs.get("headers")
        return client

    monkeypatch.setattr(updates.httpx, "AsyncClient", fake_async_client)
    assert updates.fetch_latest_version() == "0.2.0"
    assert client.headers == {"Accept": "application/vnd.github+json"}


def test_fetch_latest_version_fails_silently(monkeypatch):
    monkeypatch.setattr(
        updates.httpx, "AsyncClient", lambda *a, **kw: FakeClient(error=True)
    )
    assert updates.fetch_latest_version() is None
    monkeypatch.setattr(
        updates.httpx, "AsyncClient", lambda *a, **kw: FakeClient([])
    )
    assert updates.fetch_latest_version() is None
