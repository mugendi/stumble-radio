"""Tag and push a release when pyproject.toml is ahead of the newest remote v* tag."""

import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stumble_radio import updates


def latest_remote_tag() -> tuple[int, ...] | None:
    ls = subprocess.run(
        ["git", "ls-remote", "--tags", "origin", "v*"], check=False, capture_output=True, text=True
    )
    if ls.returncode != 0:
        sys.exit(f"Could not list remote tags: {ls.stderr.strip()}")
    newest = None
    for line in ls.stdout.splitlines():
        name = line.split("refs/tags/", 1)[1].removeprefix("v")
        if line.lstrip().endswith("^{}"):  # annotated tag peeled object, compare the same version
            continue
        version = updates.parse_version(name)
        if version and (not newest or version > newest):
            newest = version
    return newest


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    with open(root / "pyproject.toml", "rb") as fh:
        version = tomllib.load(fh)["project"]["version"]

    local = updates.parse_version(version)
    if not local:
        sys.exit(f"pyproject.toml version is not numeric: {version!r}")

    newest = latest_remote_tag()
    latest_text = f"v{'.'.join(map(str, newest))}" if newest else "none"
    if not local > (newest or ()):
        print(f"pyproject ({version}) is not ahead of the latest remote tag ({latest_text}).")
        return

    tag = f"v{version}"
    print(f"Tagging {tag} (latest remote tag: {latest_text}).")
    for command in (["git", "tag", tag], ["git", "push", "origin", tag]):
        print(f"+ {' '.join(command)}")
        if subprocess.run(command, check=False).returncode != 0:
            sys.exit(f"Command failed: {' '.join(command)}")
    print(f"Released {tag}.")


if __name__ == "__main__":
    main()
