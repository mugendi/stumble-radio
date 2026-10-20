import runpy
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def release():
    namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/release.py"))
    # Functions share their globals; patch those to keep GitHub calls offline.
    return SimpleNamespace(**namespace)


def git(root, *args):
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
        cwd=root, check=True, capture_output=True, text=True,
    ).stdout.strip()


def commit(root, subject, body=None):
    git(root, "add", ".")
    args = ["commit", "--allow-empty", "-m", subject]
    if body:
        args += ["-m", body]
    git(root, *args)
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path, release, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", str(remote))
    git(root, "init")
    git(root, "config", "user.email", "release@example.test")
    git(root, "config", "user.name", "Release test")
    git(root, "config", "tag.gpgsign", "false")
    git(root, "remote", "add", "origin", str(remote))
    (root / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    commit(root, "feat: initial release")
    git(root, "tag", "-a", "v0.1.0", "-m", "First release")
    git(root, "push", "origin", "refs/tags/v0.1.0")
    (root / "pyproject.toml").write_text('[project]\nversion = "0.2.0"\n')
    commit(root, "build: bump version")
    monkeypatch.setitem(release.main.__globals__, "repository", lambda root: "owner/radio")
    return root


def fake_github(release, monkeypatch, *, fail_create=False, listed="", fail_list=False):
    calls = []
    original = release.run

    def run(root, *command):
        if command[0] != "gh":
            return original(root, *command)
        calls.append(command)
        if command[1] == "api":
            if fail_list:
                raise SystemExit("GitHub unavailable")
            return listed
        assert command[1:3] == ("release", "create")
        calls.append(Path(command[command.index("--notes-file") + 1]).read_text())
        if fail_create:
            raise SystemExit("GitHub release creation failed")
        return "https://github.com/owner/radio/releases/tag/v0.2.0"

    monkeypatch.setitem(release.main.__globals__, "run", run)
    return calls


def test_prepare_groups_commits_preserves_bodies_and_excludes_previous_release(
    repo, release, monkeypatch, tmp_path, capsys
):
    feature = commit(repo, "feat(voice): play WAV clips", "Supports generated announcements.")
    commit(repo, "fix: restore radio volume")
    commit(repo, "docs: explain Podmoro")
    commit(repo, "build(deps): add Piper")
    commit(repo, "feat(config)!: change library layout", "Move clips to the new folder.")
    commit(repo, "fix: migrate profiles", "BREAKING CHANGE: old profiles require migration.")
    commit(repo, "Handle [brackets] and <tags>")
    old = "# Changelog\n\nRelease history.\n\n## v0.1.0\n\nHandwritten first release.\n"
    (repo / "CHANGELOG.md").write_text(old)
    monkeypatch.chdir(tmp_path)
    release.main([], root=repo)
    text = (repo / "CHANGELOG.md").read_text()
    notes = release.release_notes(text, "v0.2.0")
    assert text.startswith("# Changelog\n\nRelease history.\n\n## v0.2.0 - ")
    for heading in release.SECTIONS:
        assert f"### {heading}" in notes
    assert "Supports generated announcements." in notes
    assert "Move clips to the new folder." in notes
    assert "BREAKING CHANGE: old profiles require migration." in notes
    assert f"https://github.com/owner/radio/commit/{feature}" in notes
    assert "compare/v0.1.0...v0.2.0" in notes
    assert "initial release" not in notes
    assert r"Handle \[brackets\] and &lt;tags&gt;" in notes
    assert text.endswith("## v0.1.0\n\nHandwritten first release.\n")
    assert "Preview: v0.2.0" in capsys.readouterr().out
    assert git(repo, "tag", "--list", "v0.2.0") == ""
    edited = text.replace("play WAV clips", "Play your generated voice announcements")
    (repo / "CHANGELOG.md").write_text(edited)
    release.main([], root=repo)
    assert (repo / "CHANGELOG.md").read_text() == edited


def test_first_release_uses_full_history(repo, release):
    git(repo, "push", "origin", ":refs/tags/v0.1.0")
    release.main([], root=repo)
    notes = (repo / "CHANGELOG.md").read_text()
    assert "initial release" in notes
    assert "[Commit history]" in notes and "compare/" not in notes


def test_backfill_uses_existing_tag_not_newer_head(repo, release, monkeypatch):
    tagged = commit(repo, "feat: included feature")
    git(repo, "tag", "v0.2.0")
    git(repo, "push", "origin", "refs/tags/v0.2.0")
    commit(repo, "feat: unreleased work")
    release.main([], root=repo)
    notes = (repo / "CHANGELOG.md").read_text()
    assert "included feature" in notes and "unreleased work" not in notes
    commit(repo, "docs: release notes")
    calls = fake_github(release, monkeypatch)
    release.main(["--publish"], root=repo)
    assert git(repo, "rev-parse", "v0.2.0") == tagged
    assert release.release_notes(notes, "v0.2.0") + "\n" == calls[-1]


def test_publish_retries_after_tag_push_and_does_not_duplicate_release(
    repo, release, monkeypatch, capsys
):
    commit(repo, "fix: repeated announcements")
    release.main([], root=repo)
    head = commit(repo, "docs: reviewed release notes")
    notes = release.release_notes((repo / "CHANGELOG.md").read_text(), "v0.2.0")
    original = release.run
    calls = fake_github(release, monkeypatch, fail_create=True)
    with pytest.raises(SystemExit, match="creation failed"):
        release.main(["--publish", "--title", "Voice announcements"], root=repo)
    assert git(repo, "rev-parse", "v0.2.0^{commit}") == head
    assert "v0.2.0" in release.remote_tags(repo)
    assert "--verify-tag" in calls[-2] and "Voice announcements" in calls[-2]
    assert calls[-1] == notes + "\n"
    monkeypatch.setitem(release.main.__globals__, "run", original)
    fake_github(release, monkeypatch)
    release.main(["--publish"], root=repo)
    assert git(repo, "rev-parse", "v0.2.0^{commit}") == head
    monkeypatch.setitem(release.main.__globals__, "run", original)
    calls = fake_github(release, monkeypatch, listed="v0.2.0\tfalse")
    release.main(["--publish"], root=repo)
    assert len(calls) == 1
    assert "Already published:" in capsys.readouterr().out


def test_publish_requires_reviewed_committed_notes(repo, release):
    with pytest.raises(SystemExit, match="prepare notes"):
        release.main(["--publish"], root=repo)
    release.main([], root=repo)
    with pytest.raises(SystemExit, match="Commit your reviewed"):
        release.main(["--publish"], root=repo)
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## v0.2.0\n\n")
    commit(repo, "docs: empty notes")
    with pytest.raises(SystemExit, match="no release notes"):
        release.main(["--publish"], root=repo)


def test_github_failure_does_not_create_tag(repo, release, monkeypatch):
    release.main([], root=repo)
    commit(repo, "docs: release notes")
    fake_github(release, monkeypatch, fail_list=True)
    with pytest.raises(SystemExit, match="GitHub unavailable"):
        release.main(["--publish"], root=repo)
    assert git(repo, "tag", "--list", "v0.2.0") == ""
    assert "v0.2.0" not in release.remote_tags(repo)


def test_conflicting_local_tag_is_not_moved(repo, release, monkeypatch):
    git(repo, "tag", "v0.2.0")
    release.main([], root=repo)
    commit(repo, "docs: release notes")
    fake_github(release, monkeypatch)
    with pytest.raises(SystemExit, match="different commit"):
        release.main(["--publish"], root=repo)
    assert "v0.2.0" not in release.remote_tags(repo)


def test_duplicate_entries_are_rejected(release):
    with pytest.raises(SystemExit, match="multiple entries"):
        release.release_notes("## v0.2.0\nFirst\n## v0.2.0 - today\nSecond", "v0.2.0")


@pytest.mark.parametrize("origin", [
    "https://github.com/owner/radio.git",
    "git@github.com:owner/radio.git",
    "ssh://git@github.com/owner/radio.git",
])
def test_github_remote_urls(release, monkeypatch, tmp_path, origin):
    monkeypatch.setitem(release.repository.__globals__, "run", lambda *args: origin)
    assert release.repository(tmp_path) == "owner/radio"


def test_publish_retry_after_failed_tag_push(repo, release, monkeypatch):
    release.main([], root=repo)
    head = commit(repo, "docs: release notes")
    calls = fake_github(release, monkeypatch)
    original = release.main.__globals__["run"]

    def fail_push(root, *command):
        if command[:2] == ("git", "push"):
            raise SystemExit("Tag push failed")
        return original(root, *command)

    monkeypatch.setitem(release.main.__globals__, "run", fail_push)
    with pytest.raises(SystemExit, match="Tag push failed"):
        release.main(["--publish"], root=repo)
    assert git(repo, "rev-parse", "v0.2.0^{commit}") == head
    assert "v0.2.0" not in release.remote_tags(repo)
    assert len(calls) == 1
    monkeypatch.setitem(release.main.__globals__, "run", original)
    release.main(["--publish"], root=repo)
    assert "v0.2.0" in release.remote_tags(repo)


def test_existing_draft_is_not_overwritten(repo, release, monkeypatch):
    release.main([], root=repo)
    commit(repo, "docs: release notes")
    calls = fake_github(release, monkeypatch, listed="v0.2.0\ttrue")
    with pytest.raises(SystemExit, match="draft release already exists"):
        release.main(["--publish"], root=repo)
    assert len(calls) == 1
    assert "v0.2.0" not in release.remote_tags(repo)


def test_no_changes_and_invalid_or_older_versions_do_not_write_changelog(repo, release):
    target = release.fetch_commit(repo, "v0.1.0")
    with pytest.raises(SystemExit, match="No commits"):
        release.generate_notes(repo, "owner/radio", "v0.2.0", "v0.1.0", target)
    for version, error in (("invalid", "not numeric"), ("0.0.1", "older")):
        (repo / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
        with pytest.raises(SystemExit, match=error):
            release.main([], root=repo)
    assert not (repo / "CHANGELOG.md").exists()


def test_remote_tag_must_match_committed_project_version(repo, release, monkeypatch):
    old = git(repo, "rev-parse", "v0.1.0^{commit}")
    git(repo, "tag", "v0.2.0", old)
    git(repo, "push", "origin", "refs/tags/v0.2.0")
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## v0.2.0\n\nReviewed notes.\n")
    commit(repo, "docs: release notes")
    calls = fake_github(release, monkeypatch)
    with pytest.raises(SystemExit, match="different pyproject.toml version"):
        release.main(["--publish"], root=repo)
    assert len(calls) == 1
    assert git(repo, "rev-parse", "v0.2.0") == old


def test_numeric_previous_tag_selection_and_annotated_tags(repo, release):
    commit(repo, "feat: older feature")
    git(repo, "tag", "v0.2.0")
    commit(repo, "feat: newer released feature")
    git(repo, "tag", "-a", "v0.10.0", "-m", "Newer")
    git(repo, "push", "origin", "--tags")
    (repo / "pyproject.toml").write_text('[project]\nversion = "0.11.0"\n')
    commit(repo, "feat: next release feature")
    release.main([], root=repo)
    notes = (repo / "CHANGELOG.md").read_text()
    assert "next release feature" in notes
    assert "released feature" not in notes and "older feature" not in notes
    assert "compare/v0.10.0...v0.11.0" in notes
    assert all(not tag.endswith("^{}") for tag in release.remote_tags(repo))


def test_ignored_changelog_is_not_treated_as_committed(repo, release):
    (repo / ".gitignore").write_text("CHANGELOG.md\n")
    commit(repo, "build: ignore changelog")
    release.main([], root=repo)
    assert git(repo, "status", "--porcelain") == ""
    with pytest.raises(SystemExit, match="HEAD:CHANGELOG.md failed"):
        release.main(["--publish"], root=repo)
