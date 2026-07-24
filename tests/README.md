# Offline test baseline

These tests use only the compact files under `tests/fixtures`. Network access by
the AUSL data module is blocked by an autouse fixture.

From the project root, run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

`pytest.ini` disables pytest's cache and keeps temporary test data in the
ignored, workspace-local `.pytest-tmp` directory. Tests never touch the
application's manual-note or lineup files.

The Phase 0 baseline intentionally states the Phase 1 acceptance behavior. A
test may fail against the pre-Phase-1 source until its corresponding reviewable
implementation unit is complete.
