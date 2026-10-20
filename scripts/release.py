"""Prepare editable changelog entries, then publish reviewed notes with --publish."""

import argparse
import html
import re
import subprocess
import sys
import tempfile
import tomllib
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stumble_radio import updates

SECTIONS = (
    "Breaking changes",
    "New features",
    "Bug fixes",
    "Documentation",
    "Dependencies and maintenance",
    "Other changes",
)
KINDS = {
    "feat": "New features",
    "fix": "Bug fixes",
    "docs": "Documentation",
    **dict.fromkeys(
        ("build", "chore", "ci", "deps", "perf", "refactor", "revert", "style", "test"),
        "Dependencies and maintenance",
    ),
}


def run(root: Path, *command: str) -> str:
    try:
        result = subprocess.run(
            command, cwd=root, check=True, capture_output=True, text=True
        )
    except OSError as error:
        sys.exit(f"Could not run {command[0]}: {error}")
    except subprocess.CalledProcessError as error:
        sys.exit(f"{' '.join(command)} failed: {error.stderr.strip() or error.stdout.strip()}")
    return result.stdout.strip()


def remote_tags(root: Path) -> dict[str, tuple[int, ...]]:
    tags = {}
    for line in run(root, "git", "ls-remote", "--tags", "origin", "v*").splitlines():
        name = line.split("refs/tags/", 1)[1]
        version = updates.parse_version(name)
        if version:  # Peeled annotated tags and nonnumeric versions are excluded.
            tags[name] = version
    return tags


def repository(root: Path) -> str:
    origin = run(root, "git", "remote", "get-url", "origin").rstrip("/").removesuffix(".git")
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
        r"([\w.-]+/[\w.-]+)",
        origin,
    )
    if not match:
        sys.exit("origin must be a GitHub HTTPS or SSH repository URL.")
    return match[1]


def fetch_commit(root: Path, tag: str) -> str:
    # Fetch the object without creating or moving a local tag.
    run(root, "git", "fetch", "--no-tags", "origin", f"refs/tags/{tag}")
    return run(root, "git", "rev-parse", "FETCH_HEAD^{commit}")


def markdown(text: str) -> str:
    return re.sub(r"([\\`*_\[\]])", r"\\\1", html.escape(text, quote=False))


def generate_notes(root: Path, repo: str, tag: str, previous: str | None, target: str) -> str:
    start = fetch_commit(root, previous) if previous else None
    if start:
        run(root, "git", "merge-base", "--is-ancestor", start, target)
    revision = f"{start}..{target}" if start else target
    log = run(root, "git", "log", "--reverse", "--no-merges", "--format=%H%x00%B%x00", revision)
    fields = log.split("\0")
    groups = {section: [] for section in SECTIONS}
    for index in range(0, len(fields) - 1, 2):
        sha, message = fields[index].strip(), fields[index + 1].strip()
        subject, _, body = message.partition("\n")
        match = re.fullmatch(r"([a-z]+)(?:\(([^)]+)\))?(!)?:\s*(.+)", subject)
        section = "Other changes"
        if match:
            kind, scope, breaking, subject = match.groups()
            section = KINDS.get(kind, "Other changes")
            if scope:
                subject = f"{scope}: {subject}"
            if breaking:
                section = "Breaking changes"
        if re.search(r"(?m)^BREAKING[ -]CHANGE:", body):
            section = "Breaking changes"
        entry = f"- {markdown(subject)} ([{sha[:7]}](https://github.com/{repo}/commit/{sha}))"
        if body.strip():
            entry += "\n\n" + "\n".join(f"  {markdown(line)}" for line in body.strip().splitlines())
        groups[section].append(entry)
    if not any(groups.values()):
        sys.exit("No commits to describe since the previous release.")
    sections = [
        f"### {section}\n\n" + "\n".join(entries)
        for section, entries in groups.items()
        if entries
    ]
    if previous:
        sections.append(f"[Full comparison](https://github.com/{repo}/compare/{previous}...{tag})")
    else:
        sections.append(f"[Commit history](https://github.com/{repo}/commits/{target})")
    return "\n\n".join(sections)


def release_notes(changelog: str, tag: str) -> str | None:
    headings = list(re.finditer(rf"(?m)^## {re.escape(tag)}(?:[ \t].*)?$", changelog))
    if len(headings) > 1:
        sys.exit(f"CHANGELOG.md contains multiple entries for {tag}.")
    if not headings:
        return None
    following = changelog[headings[0].end():]
    return re.split(r"(?m)^## ", following, maxsplit=1)[0].strip()


def publish(root: Path, repo: str, tag: str, notes: str, tags: dict, title: str) -> None:
    if not notes:
        sys.exit(f"CHANGELOG.md has no release notes for {tag}.")
    if run(root, "git", "status", "--porcelain"):
        sys.exit("Commit your reviewed CHANGELOG.md, version bump, and other changes before publishing.")
    committed = run(root, "git", "show", "HEAD:CHANGELOG.md")
    if release_notes(committed, tag) != notes:
        sys.exit("The release notes must match the committed CHANGELOG.md entry.")
    # A successful read distinguishes a missing release from an authentication/network failure.
    releases = run(
        root, "gh", "api", "--paginate", f"repos/{repo}/releases",
        "--jq", ".[] | [.tag_name, .draft] | @tsv",
    )
    url = f"https://github.com/{repo}/releases/tag/{tag}"
    for line in releases.splitlines():
        name, draft = line.split("\t")
        if name == tag:
            if draft == "true":
                sys.exit(f"A draft release already exists for {tag}. Review and publish it on GitHub.")
            print(f"Already published: {url}")
            return

    head = run(root, "git", "rev-parse", "HEAD")
    target = fetch_commit(root, tag) if tag in tags else head
    tagged_project = tomllib.loads(run(root, "git", "show", f"{target}:pyproject.toml"))
    if f"v{tagged_project['project']['version']}" != tag:
        sys.exit(f"The commit for {tag} has a different pyproject.toml version.")
    local_tag = run(root, "git", "tag", "--list", tag)
    if local_tag and run(root, "git", "rev-parse", f"refs/tags/{tag}^{{commit}}") != target:
        sys.exit(f"Local tag {tag} points to a different commit; it will not be moved.")
    if tag not in tags:
        if not local_tag:
            run(root, "git", "tag", "-a", tag, target, "-m", title)
        run(root, "git", "push", "origin", f"refs/tags/{tag}")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".md") as file:
        file.write(notes + "\n")
        file.flush()
        run(
            root, "gh", "release", "create", tag, "--repo", repo, "--verify-tag",
            "--title", title, "--notes-file", file.name,
        )
    print(f"Published: {url}")


def main(argv=None, *, root: Path | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true", help="Publish the committed changelog entry")
    parser.add_argument("--title", help="GitHub release title (used with --publish)")
    args = parser.parse_args(argv)
    root = root or Path(__file__).resolve().parent.parent
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    local = updates.parse_version(version)
    if not local:
        sys.exit(f"pyproject.toml version is not numeric: {version!r}")
    tag = f"v{version}"
    repo, tags = repository(root), remote_tags(root)
    if tags and local < max(tags.values()):
        sys.exit("The project version is older than the newest remote version tag.")
    path = root / "CHANGELOG.md"
    changelog = path.read_text(encoding="utf-8") if path.exists() else "# Changelog\n\n"
    notes = release_notes(changelog, tag)
    if args.publish:
        if notes is None:
            sys.exit(f"Run scripts/release.py first to prepare notes for {tag}.")
        publish(root, repo, tag, notes, tags, args.title or f"Stumble Radio {tag}")
        return
    if notes is None:
        previous = max(
            (name for name in tags if tags[name] < local), key=tags.get, default=None
        )
        target = fetch_commit(root, tag) if tag in tags else run(root, "git", "rev-parse", "HEAD")
        notes = generate_notes(root, repo, tag, previous, target)
        entry = f"## {tag} - {date.today().isoformat()}\n\n{notes}\n\n"
        first = re.search(r"(?m)^## ", changelog)
        position = first.start() if first else len(changelog)
        changelog = changelog[:position].rstrip() + "\n\n" + entry + changelog[position:]
        path.write_text(changelog, encoding="utf-8")
    elif not notes:
        sys.exit(f"CHANGELOG.md has an empty entry for {tag}; add release notes before publishing.")
    print(f"Preview: {tag}\n\n{notes}\n")
    print("Edit CHANGELOG.md, commit it with your changes, then run scripts/release.py --publish.")


if __name__ == "__main__":
    main()
