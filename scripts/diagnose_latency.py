"""Read-only latency report; also works when copied into the pre-optimization checkout.

From the repository root:
    cd backend && uv run --no-sync python ../scripts/diagnose_latency.py --scan
"""

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.attachments import file_snapshot
from app.config import Settings


STATUS_PHASES = {
    "Waiting for workspace availability": "workspace_wait_then_scan_before",
    "Saving a workspace checkpoint": "checkpoint_before_start",
    "Starting sandbox": "sandbox_start",
    "Deciding the next action": "model_wait",
    "Compacting conversation context": "context_compaction",
    "Checking workspace files": "workspace_scan_start",
}


def recent_runs(database: Path, limit=3):
    if not database.exists():
        return []
    # Do not construct Store: its constructor creates/migrates the database.
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        runs = db.execute(
            "SELECT r.id,r.status,r.created_at,c.workspace_id FROM runs r "
            "JOIN conversations c ON c.id=r.conversation_id "
            "ORDER BY r.created_at DESC LIMIT ?", (limit,),
        ).fetchall()
        report = []
        for run in runs:
            origin = previous = datetime.fromisoformat(run["created_at"])
            markers, checkpoint_events, first_output = [], 0, False
            rows = db.execute(
                "SELECT type,created_at,CASE WHEN type IN ('text_delta','reasoning_delta') "
                "THEN '{}' ELSE data END AS data FROM events WHERE run_id=? "
                "AND type IN ('status','round','checkpoint','workspace_scan','response','artifacts',"
                "'text_delta','reasoning_delta') ORDER BY seq", (run["id"],),
            )
            for row in rows:
                kind, data = row["type"], json.loads(row["data"])
                if kind == "status":
                    phase = STATUS_PHASES.get(data.get("label"), "status:" + data.get("status", "unknown"))
                elif kind == "round":
                    first_output = False
                    phase = "model_request"
                elif kind in {"text_delta", "reasoning_delta"}:
                    if first_output:
                        continue
                    first_output = True
                    phase = "first_model_output"
                elif kind == "checkpoint":
                    checkpoint_events += 1
                    name = data.get("name") if data.get("name") in {"before", "after"} else "unknown"
                    phase = "checkpoint_" + name + ("_failed" if "error" in data else "_done")
                elif kind == "workspace_scan":
                    name = data.get("name") if data.get("name") in {"before", "after"} else "unknown"
                    phase = "workspace_scan_" + name + "_done"
                elif kind == "response":
                    phase = "model_response_with_tools" if data.get("continues") else "model_response_final"
                else:
                    phase = "sandbox_close_and_scan_after_done"
                stamp = datetime.fromisoformat(row["created_at"])
                markers.append(dict(
                    phase=phase,
                    elapsed_seconds=round((stamp - origin).total_seconds(), 3),
                    since_previous_seconds=round((stamp - previous).total_seconds(), 3),
                ))
                if kind in {"workspace_scan", "checkpoint"}:
                    for key in ("duration_ms", "files", "hashed_files"):
                        if isinstance(data.get(key), (int, float)):
                            markers[-1][key] = data[key]
                previous = stamp
            report.append(dict(run_id=run["id"], workspace_id=run["workspace_id"],
                               status=run["status"], checkpoint_events=checkpoint_events,
                               timeline=markers))
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="store_true", help="Measure one metadata scan per configured workspace")
    parser.add_argument("--workspace", help="Restrict the metadata scan to this workspace ID")
    parser.add_argument("--runs", type=int, default=3, help="Number of recent runs (1–20)")
    args = parser.parse_args()
    if not 1 <= args.runs <= 20:
        parser.error("--runs must be between 1 and 20")
    settings = Settings()
    print(json.dumps(dict(
        checkpoint_setting_in_this_process=settings.checkpoints,
        note="This reads this process's environment; it does not query the running server's settings. "
             "Timeline intervals can include multiple operations, e.g. Docker shutdown plus the final scan.",
        recent_runs=recent_runs(settings.data_dir / "agent.db", args.runs),
    ), ensure_ascii=False, indent=2), flush=True)
    if args.scan:
        workspaces = settings.load_runtime().workspaces
        if args.workspace:
            workspaces = [w for w in workspaces if w.id == args.workspace]
            if not workspaces:
                parser.error("Unknown workspace ID")
        for workspace in workspaces:
            print(f"Scanning workspace {workspace.id} ...", flush=True)
            started = perf_counter()
            try:
                files = file_snapshot(workspace.path)
            except OSError as error:
                print(json.dumps(dict(workspace_id=workspace.id, scan_error=type(error).__name__)), flush=True)
                continue
            print(json.dumps(dict(
                workspace_id=workspace.id, scan_seconds=round(perf_counter() - started, 3),
                files=len(files), total_gib=round(sum(s[0] for s in files.values()) / 1024**3, 3),
            )), flush=True)
            del files


if __name__ == "__main__":
    main()
