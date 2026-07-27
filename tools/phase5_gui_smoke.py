"""Manual no-network Windows GUI smoke for cancelled/replacement refreshes."""

from __future__ import annotations

import argparse
import copy
import json
import platform
import sys
import threading
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import ausl_stats_app  # noqa: E402


_real_load_database = ausl_stats_app.load_database
_call_lock = threading.Lock()
_call_count = 0
_cancelled_worker_done = threading.Event()
_replacement_ready = threading.Event()


def _smoke_update_all_data(
    progress,
    *,
    include_enrichment: bool,
    cancel_token=None,
):
    global _call_count
    assert include_enrichment is False
    with _call_lock:
        _call_count += 1
        call_number = _call_count

    if call_number == 1:
        progress("GUI smoke: first refresh blocked; cancel it now.")
        while cancel_token is not None and not cancel_token.cancelled:
            time.sleep(0.02)
        progress("GUI smoke: cancelled worker is resolving safely...")
        time.sleep(2.0)
        _cancelled_worker_done.set()
        raise ausl_stats_app.RefreshCancelled()

    progress("GUI smoke: replacement queued; waiting for cancelled worker...")
    if not _cancelled_worker_done.wait(8):
        raise TimeoutError("GUI smoke cancelled worker did not resolve")
    progress("GUI smoke: replacement refresh committing coherent snapshot...")
    time.sleep(0.4)
    _replacement_ready.set()


def _smoke_load_database(*, include_enrichment: bool):
    data = _real_load_database(include_enrichment=include_enrichment)
    if _replacement_ready.is_set():
        data = copy.deepcopy(data)
        data["manifest"] = dict(data.get("manifest", {}))
        data["manifest"]["phase5_gui_smoke"] = "replacement-refresh"
    return data


def _run_automated_smoke(root, app, result_path: Path) -> None:
    started_at = time.monotonic()
    deadline = started_at + 20
    telemetry = {
        "platform": platform.platform(),
        "responsive_ticks": 0,
        "dialogs": 0,
        "queued_status_seen": False,
        "first_blocked_status_seen": False,
    }

    def heartbeat():
        telemetry["responsive_ticks"] += 1
        root.after(20, heartbeat)

    def fail(message):
        telemetry["result"] = "failed"
        telemetry["error"] = message
        result_path.write_text(
            json.dumps(telemetry, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        root.destroy()

    def wait_for_initial_load():
        if time.monotonic() > deadline:
            fail("initial database load timed out")
            return
        if getattr(app, "_initial_load_in_flight", False):
            root.after(25, wait_for_initial_load)
            return
        app.update_button.invoke()
        root.after(100, cancel_and_replace)

    def cancel_and_replace():
        telemetry["first_blocked_status_seen"] = (
            "first refresh blocked" in app.status_var.get().lower()
        )
        ticks_before_cancel = telemetry["responsive_ticks"]
        app.cancel_update_button.invoke()
        if telemetry["responsive_ticks"] <= 0:
            fail("Tk event loop did not remain responsive while blocked")
            return
        app.update_button.invoke()
        telemetry["ticks_before_cancel"] = ticks_before_cancel
        root.after(50, wait_for_replacement)

    def wait_for_replacement():
        if time.monotonic() > deadline:
            fail("replacement refresh timed out")
            return
        status = app.status_var.get().lower()
        telemetry["queued_status_seen"] = (
            telemetry["queued_status_seen"]
            or "replacement queued" in status
        )
        if getattr(app, "_data_update_in_flight", False):
            root.after(50, wait_for_replacement)
            return
        root.after(250, finish)

    def finish():
        manifest_path = (
            PROJECT_ROOT / "data" / "exports" / "update_manifest.json"
        )
        disk_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        app_manifest = app.db.get("manifest", {})
        checks = {
            "first_blocked_status_seen": telemetry["first_blocked_status_seen"],
            "queued_status_seen": telemetry["queued_status_seen"],
            "responsive": telemetry["responsive_ticks"] > 5,
            "two_refreshes_started": _call_count == 2,
            "cancelled_worker_resolved": _cancelled_worker_done.is_set(),
            "replacement_loaded": _replacement_ready.is_set(),
            "no_dialogs": telemetry["dialogs"] == 0,
            "update_button_enabled": app.update_button.instate(["!disabled"]),
            "cancel_button_disabled": app.cancel_update_button.instate(["disabled"]),
            "in_memory_manifest_matches_disk": (
                app_manifest.get("updated_at") == disk_manifest.get("updated_at")
            ),
            "replacement_marker_loaded": (
                app_manifest.get("phase5_gui_smoke") == "replacement-refresh"
            ),
        }
        telemetry["checks"] = checks
        telemetry["final_status"] = app.status_var.get()
        telemetry["result"] = "passed" if all(checks.values()) else "failed"
        result_path.write_text(
            json.dumps(telemetry, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        root.destroy()

    ausl_stats_app.messagebox.showerror = (
        lambda *_args, **_kwargs: telemetry.__setitem__(
            "dialogs", telemetry["dialogs"] + 1
        )
    )
    heartbeat()
    root.after(25, wait_for_initial_load)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--automated", action="store_true")
    parser.add_argument("--result", type=Path)
    args = parser.parse_args(argv)
    if args.automated and args.result is None:
        parser.error("--result is required with --automated")

    ausl_stats_app.update_all_data = _smoke_update_all_data
    ausl_stats_app.load_database = _smoke_load_database
    root = ausl_stats_app.tk.Tk()
    app = ausl_stats_app.AUSLStatsApp(root)
    root.title("AUSL Broadcast Stats - Phase 5 GUI Smoke")
    if args.automated:
        _run_automated_smoke(root, app, args.result)
    root.mainloop()


if __name__ == "__main__":
    main()
