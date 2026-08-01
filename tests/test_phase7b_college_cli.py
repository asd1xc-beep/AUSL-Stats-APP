from __future__ import annotations

from tools.validate_college_data import main

from test_phase7b_college_serialization import envelope
from ausl_college import serialize_envelope


def test_validator_accepts_only_explicit_valid_file(tmp_path, capsys):
    path = tmp_path / "synthetic-college.json"
    path.write_bytes(serialize_envelope(envelope()))
    assert main([str(path)]) == 0
    assert capsys.readouterr().out.startswith("VALID: players=1 sources=1")


def test_validator_returns_nonzero_for_invalid_file(tmp_path, capsys):
    path = tmp_path / "invalid.json"
    path.write_text("{}", encoding="utf-8")
    assert main([str(path)]) == 1
    assert capsys.readouterr().out.startswith("INVALID:")
