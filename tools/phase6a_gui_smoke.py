"""Deterministic no-network Windows source-app smoke for Phase 6A."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import ausl_stats_app  # noqa: E402


REAL_LOAD_DATABASE = ausl_stats_app.load_database


def _write_result(path: Path, telemetry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(telemetry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _network_blocker(calls, name):
    def blocked(*_args, **_kwargs):
        calls.append(name)
        raise AssertionError(f"GUI smoke attempted forbidden network route: {name}")

    return blocked


def _wait_for_initial_load(root, app, deadline, on_ready, on_fail):
    if time.monotonic() > deadline:
        on_fail("initial local database load timed out")
        return
    if getattr(app, "_initial_load_in_flight", False):
        root.after(
            25,
            lambda: _wait_for_initial_load(
                root, app, deadline, on_ready, on_fail
            ),
        )
        return
    on_ready()


def _run_first_window(work_dir: Path, telemetry: dict, hold_ms: int) -> None:
    root = ausl_stats_app.tk.Tk()
    app = ausl_stats_app.AUSLStatsApp(root)
    root.geometry("1120x720")
    root.title("AUSL Broadcast Stats - Phase 6A GUI Smoke")
    deadline = time.monotonic() + 20
    responsive_ticks = 0
    heartbeat_id = None
    closing = False

    def heartbeat():
        nonlocal responsive_ticks, heartbeat_id
        if closing:
            return
        responsive_ticks += 1
        heartbeat_id = root.after(20, heartbeat)

    def close_window():
        nonlocal closing
        closing = True
        if heartbeat_id is not None:
            try:
                root.after_cancel(heartbeat_id)
            except ausl_stats_app.tk.TclError:
                pass
        app._on_close()

    def fail(message):
        telemetry["errors"].append(message)
        close_window()

    def exercise():
        try:
            root.update_idletasks()
            telemetry["minimum_window"] = {
                "width": root.winfo_width(),
                "height": root.winfo_height(),
            }
            app._apply_custom_game_context()
            telemetry["no_game_state"] = app.game_day_readiness.overall_state

            games = [
                game
                for game in ausl_stats_app.official_selected_games(
                    app.db["schedule_results"]
                )
                if game.season == ausl_stats_app.CURRENT_YEAR
            ]
            if len(games) < 2:
                raise AssertionError("two current-season official games are required")
            first, second = games[:2]
            app.on_game_changed(first)
            telemetry["selected_game"] = first.game_id
            telemetry["selected_game_state"] = app.game_day_readiness.overall_state

            app.load_projected_lineups_into_editor()
            app.lock_lineups_from_editor()
            first_lock = app._current_lineup_lock()
            telemetry["projected_lineup_saved"] = bool(
                first_lock
                and first_lock.get("source") == "projected"
                and first_lock.get("game_id") == first.game_id
            )
            telemetry["projected_lineup_state"] = (
                app.game_day_readiness.overall_state
            )

            app.generate_pregame_report()
            packet = app._latest_packet_metadata()
            telemetry["packet_current"] = bool(
                packet
                and packet.get("game_id") == first.game_id
                and packet.get("lineup_revision") == first_lock.get("revision")
            )

            calls_before = list(telemetry["network_calls"])
            app.set_local_offline_mode(True)
            app.update_data()
            app.refresh_live()
            app.auto_var.set(True)
            app._schedule_live()
            telemetry["offline_blocks_network"] = (
                telemetry["network_calls"] == calls_before
                and app.update_button.instate(["disabled"])
                and app.live_refresh_button.instate(["disabled"])
                and app._live_timer_id is None
            )

            app.on_game_changed(second)
            telemetry["second_game"] = second.game_id
            telemetry["old_context_cleared"] = bool(
                app.selected_game.game_id == second.game_id
                and not app._current_lineup_lock()
                and app._latest_packet_metadata() is None
                and app.live_game is None
                and app.game_day_readiness.selected_game_id == second.game_id
            )

            app.set_local_offline_mode(False)
            telemetry["offline_disable_did_not_fetch"] = (
                telemetry["network_calls"] == calls_before
                and app._offline_mode is False
            )
            telemetry["first_window_responsive"] = responsive_ticks > 5
            telemetry["first_window_status"] = app.game_day_overall_var.get()
            telemetry["first_game_id_for_relaunch"] = first.game_id
        except Exception as exc:
            fail(f"{type(exc).__name__}: {exc}")
            return
        root.after(max(hold_ms, 50), close_window)

    heartbeat()
    root.after(
        25,
        lambda: _wait_for_initial_load(
            root, app, deadline, exercise, fail
        ),
    )
    root.mainloop()


def _run_relaunch_window(telemetry: dict) -> None:
    if telemetry["errors"]:
        return
    root = ausl_stats_app.tk.Tk()
    app = ausl_stats_app.AUSLStatsApp(root)
    root.geometry("1120x720")
    root.title("AUSL Broadcast Stats - Phase 6A Relaunch Smoke")
    deadline = time.monotonic() + 20

    def fail(message):
        telemetry["errors"].append(message)
        root.destroy()

    def verify():
        try:
            game_id = telemetry["first_game_id_for_relaunch"]
            selected = next(
                game
                for game in ausl_stats_app.official_selected_games(
                    app.db["schedule_results"]
                )
                if game.game_id == game_id
            )
            app.on_game_changed(selected)
            lock = app._current_lineup_lock()
            packet = app._latest_packet_metadata()
            telemetry["relaunch"] = {
                "offline_defaults_off": (
                    app._offline_mode is False
                    and app.offline_mode_var.get() is False
                ),
                "lineup_reloaded_for_exact_game": bool(
                    lock and lock.get("game_id") == game_id
                ),
                "packet_reloaded_for_exact_game": bool(
                    packet and packet.get("game_id") == game_id
                ),
                "dashboard_rendered": isinstance(
                    app.game_day_readiness,
                    ausl_stats_app.GameDayReadiness,
                ),
            }
        except Exception as exc:
            fail(f"{type(exc).__name__}: {exc}")
            return
        root.after(100, app._on_close)

    root.after(
        25,
        lambda: _wait_for_initial_load(
            root, app, deadline, verify, fail
        ),
    )
    root.mainloop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--hold-ms", type=int, default=0)
    parser.add_argument(
        "--stage",
        choices=("first", "relaunch"),
        required=True,
    )
    args = parser.parse_args(argv)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    exports = args.work_dir / "exports"
    exports.mkdir(parents=True, exist_ok=True)

    if args.stage == "relaunch" and args.result.exists():
        telemetry = json.loads(args.result.read_text(encoding="utf-8"))
    else:
        telemetry = {
            "platform": platform.platform(),
            "app_type": "Windows source app / real Tk loop / offline fixtures",
            "network_calls": [],
            "dialogs": {"info": 0, "warning": 0, "error": 0},
            "errors": [],
        }
    ausl_stats_app.export_dir = lambda: exports
    ausl_stats_app.load_database = REAL_LOAD_DATABASE
    ausl_stats_app.update_all_data = _network_blocker(
        telemetry["network_calls"], "core_refresh"
    )
    ausl_stats_app.fetch_live_game = _network_blocker(
        telemetry["network_calls"], "live_refresh"
    )
    ausl_stats_app.messagebox.askyesno = lambda *_args, **_kwargs: True
    ausl_stats_app.messagebox.showinfo = (
        lambda *_args, **_kwargs: telemetry["dialogs"].__setitem__(
            "info", telemetry["dialogs"]["info"] + 1
        )
    )
    ausl_stats_app.messagebox.showwarning = (
        lambda *_args, **_kwargs: telemetry["dialogs"].__setitem__(
            "warning", telemetry["dialogs"]["warning"] + 1
        )
    )
    ausl_stats_app.messagebox.showerror = (
        lambda *_args, **_kwargs: telemetry["dialogs"].__setitem__(
            "error", telemetry["dialogs"]["error"] + 1
        )
    )

    if args.stage == "first":
        _run_first_window(args.work_dir, telemetry, args.hold_ms)
        telemetry["result"] = "first-stage-passed" if not telemetry["errors"] else "failed"
        _write_result(args.result, telemetry)
        if telemetry["errors"]:
            raise SystemExit(1)
        return

    _run_relaunch_window(telemetry)
    checks = {
        "no_game_not_ready": telemetry.get("no_game_state") == "not-ready",
        "projected_lineup_saved": telemetry.get("projected_lineup_saved") is True,
        "projected_never_ready": telemetry.get("projected_lineup_state")
        != "ready",
        "packet_current": telemetry.get("packet_current") is True,
        "offline_blocks_network": telemetry.get("offline_blocks_network") is True,
        "old_context_cleared": telemetry.get("old_context_cleared") is True,
        "offline_disable_did_not_fetch": telemetry.get(
            "offline_disable_did_not_fetch"
        )
        is True,
        "responsive": telemetry.get("first_window_responsive") is True,
        "minimum_size": telemetry.get("minimum_window")
        == {"width": 1120, "height": 720},
        "no_network_calls": telemetry["network_calls"] == [],
        "no_routine_dialogs": telemetry["dialogs"]
        == {"info": 0, "warning": 0, "error": 0},
        "relaunch": bool(telemetry.get("relaunch"))
        and all(telemetry["relaunch"].values()),
        "no_errors": telemetry["errors"] == [],
    }
    telemetry["checks"] = checks
    telemetry["result"] = "passed" if all(checks.values()) else "failed"
    _write_result(args.result, telemetry)
    if telemetry["result"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
