# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for the CLI entry point (apysource.cli.__main__) and config loading."""

import sys

import pytest

import apysource._defaults
from apysource.cli.__main__ import main


# ── Fakes ──────────────────────────────────────────────────────────────────

class _FakeCommand:
    """Records how it was run; opts in to graph input."""

    accepts_graph = True

    def __init__(self):
        self.calls = []

    def run(self, graph=None, args=None):
        self.calls.append({"graph": graph, "args": args})


class _NoGraphCommand:
    """A command that does not accept a graph; run() takes only args."""

    def __init__(self):
        self.calls = []

    def run(self, args=None):
        self.calls.append({"args": args})


class _FakeWiring:
    """Mimics the compiled wiring object: attribute access returns a factory."""

    def __init__(self, **commands):
        self._commands = commands

    def __getattr__(self, name):
        try:
            return lambda: self._commands[name]
        except KeyError:
            raise AttributeError(name)


def _run(monkeypatch, argv, wiring):
    monkeypatch.setattr(sys, "argv", ["apysource", *argv])
    monkeypatch.setattr(apysource._defaults, "compiled", wiring)
    try:
        main()
        return None
    except SystemExit as exc:
        return exc.code


# ── help / usage ─────────────────────────────────────────────────────────

def test_no_args_prints_usage(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["apysource"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Usage:" in out
    # The hidden alias must not be advertised.
    assert "check-sources" not in out


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_flag(monkeypatch, capsys, flag):
    monkeypatch.setattr(sys, "argv", ["apysource", flag])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert "Usage:" in capsys.readouterr().out


def test_unknown_command(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["apysource", "frobnicate"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Unknown command: frobnicate" in err


# ── dispatch ───────────────────────────────────────────────────────────────

def test_dispatch_passes_args(monkeypatch):
    cmd = _NoGraphCommand()
    wiring = _FakeWiring(locate_cmd=cmd)
    code = _run(monkeypatch, ["locate", "http://x", "snippet"], wiring)
    assert code is None or code == 0  # _NoGraphCommand.run doesn't sys.exit
    assert cmd.calls == [{"args": ["http://x", "snippet"]}]


def test_yaml_autodetected_for_graph_command(monkeypatch, tmp_path):
    yaml_file = tmp_path / "sources.yaml"
    yaml_file.write_text(
        "sources:\n  - label: S\n    url: http://x\n    fragments: []\n",
        encoding="utf-8",
    )
    cmd = _FakeCommand()
    wiring = _FakeWiring(check_sources_cmd=cmd)
    _run(monkeypatch, ["check", str(yaml_file), "--flag"], wiring)
    assert len(cmd.calls) == 1
    call = cmd.calls[0]
    assert call["graph"] is not None        # YAML was loaded into a graph
    assert call["args"] == ["--flag"]        # graph path consumed, rest passed


def test_yaml_autodetected_after_a_flag(monkeypatch, tmp_path):
    """The sources file is found even when a flag precedes it (e.g. --refresh)."""
    yaml_file = tmp_path / "sources.yaml"
    yaml_file.write_text(
        "sources:\n  - label: S\n    url: http://x\n    fragments: []\n",
        encoding="utf-8",
    )
    cmd = _FakeCommand()
    wiring = _FakeWiring(check_sources_cmd=cmd)
    _run(monkeypatch, ["check", "--refresh", str(yaml_file)], wiring)
    assert len(cmd.calls) == 1
    call = cmd.calls[0]
    assert call["graph"] is not None          # YAML still loaded
    assert call["args"] == ["--refresh"]       # flag passed through to the command


def test_yaml_not_consumed_when_command_opts_out(monkeypatch, tmp_path):
    """A non-graph command keeps a .yaml arg as a plain positional."""
    yaml_file = tmp_path / "sources.yaml"
    yaml_file.write_text("sources: []\n", encoding="utf-8")
    cmd = _NoGraphCommand()
    wiring = _FakeWiring(add_cmd=cmd)
    _run(monkeypatch, ["add", str(yaml_file), "http://x", "snip"], wiring)
    assert cmd.calls[0]["args"] == [str(yaml_file), "http://x", "snip"]


# ── -c / --config ────────────────────────────────────────────────────────

def test_config_flag_invokes_get_wiring(monkeypatch):
    captured = {}
    cmd = _NoGraphCommand()

    def fake_get_wiring(path):
        captured["path"] = path
        return _FakeWiring(validate_cmd=cmd)

    import apysource.config
    monkeypatch.setattr(apysource.config, "get_wiring", fake_get_wiring)
    monkeypatch.setattr(sys, "argv", ["apysource", "-c", "custom.toml", "validate"])
    main()
    assert captured["path"] == "custom.toml"
    assert cmd.calls == [{"args": []}]
