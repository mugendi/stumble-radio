import pytest

from stumble_radio import cli


def test_version_flag_uses_package_version(monkeypatch, capsys):
    monkeypatch.setattr(cli, "__version__", "9.2.1")
    monkeypatch.setattr(cli.sys, "argv", ["stumble-radio", "--version"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "Stumble Radio 9.2.1"


def test_relaunch_execs_new_binary(monkeypatch):
    seen = []

    monkeypatch.setattr(cli.os, "execv", lambda path, argv: seen.append((path, argv)))
    cli.relaunch_process(["/usr/local/bin/stumble-radio", "--offline"])
    assert seen == [("/usr/local/bin/stumble-radio", ["/usr/local/bin/stumble-radio", "--offline"])]


def test_relaunch_failure_exits_cleanly(monkeypatch, capsys):
    def boom(path, argv):
        raise OSError("no such file")

    monkeypatch.setattr(cli.os, "execv", boom)
    with pytest.raises(SystemExit) as exc:
        cli.relaunch_process(["/gone/stumble-radio"])
    assert exc.value.code == 1
    assert "relaunch" in capsys.readouterr().err.lower() or "relaunch" in capsys.readouterr().out.lower()
