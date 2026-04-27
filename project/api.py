"""
Flask API wrapping the existing timetable pipeline.

Designed so this stays the only HTTP layer: the existing src/ modules are
imported and orchestrated programmatically, exactly mirroring main.py's
sequence (DataLoader → FeasibilityChecker → ConstraintBuilder → SolverEngine
→ output generators). Nothing in the existing codebase is modified.

Endpoints
---------
GET  /                          → static/index.html (the SPA shell)
GET  /static/<path>             → CSS / JS / assets
GET  /api/config                → user_data.json (creates a template if missing)
POST /api/config                → overwrite user_data.json with the request body
POST /api/generate-excel        → build inputs/generated_input.xlsx from user_data.json
POST /api/solve                 → SSE stream of pipeline log lines; cache the solution
GET  /api/results               → JSON-serialized last solution
GET  /api/download/zip          → output/ tree zipped
GET  /api/download/excel        → output/master_timetable.xlsx
"""
from __future__ import annotations

import io
import json
import os
import queue
import sys
import threading
import zipfile
from contextlib import redirect_stdout, redirect_stderr
from datetime import date
from pathlib import Path
from typing import Any, Dict

import pandas as pd
from flask import Flask, Response, jsonify, request, send_file, send_from_directory

# Existing pipeline components — imported, never modified.
sys.path.insert(0, str(Path(__file__).parent))
from src.config import Config
from src.constraint_builder import ConstraintBuilder
from src.data_loader import DataLoader
from src.excel_generator import ExcelGenerator
from src.feasibility_checker import FeasibilityChecker
from src.pdf_generator import PDFGenerator
from src.solver_engine import SolverEngine

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_DIR          = Path(__file__).parent
USER_DATA_PATH       = PROJECT_DIR / "config" / "user_data.json"
GENERATED_INPUT_PATH = PROJECT_DIR / "inputs" / "generated_input.xlsx"
OUTPUT_DIR           = PROJECT_DIR / "output"
STATIC_DIR           = PROJECT_DIR / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")

# In-memory cache of the last solve so /api/results doesn't have to rerun.
# A simple lock guards both the cache and the redirected-stdout machinery —
# only one solve can run at a time on this single-user local server.
_solve_lock = threading.Lock()
_last_solution_json: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# user_data.json helpers
# ---------------------------------------------------------------------------
def _empty_user_data() -> Dict[str, Any]:
    """Default template: same shape as project/config/user_data.json."""
    return {
        "college": {
            "name": "Your College Name",
            "department": "Computer Science",
            "academic_year": f"{date.today().year}-{date.today().year + 1}",
        },
        "semester_type": "odd",
        "rank_caps": dict(Config.TEACHER_RANK_HOUR_CAPS),
        "solver_time_limit_seconds": Config.SOLVER_TIME_LIMIT,
        "constraints": {
            "practical_consecutive": True,
            "max_consecutive_classes": True,
            "max_daily_hours": True,
            "max_daily_teacher_hours": True,
            "early_completion": True,
        },
        "limits": {
            "max_consecutive_classes": 3,
            "max_daily_hours": 6,
            "max_daily_teacher_hours": 6,
        },
        "teachers": [],
        "subjects": [],
        "preferences": [],
    }


def _load_user_data() -> Dict[str, Any]:
    USER_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not USER_DATA_PATH.exists():
        data = _empty_user_data()
        _save_user_data(data)
        return data
    return json.loads(USER_DATA_PATH.read_text(encoding="utf-8"))


def _save_user_data(data: Dict[str, Any]) -> None:
    USER_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_DATA_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Adapter the existing ConstraintBuilder expects (mirrors main.py.ConfigAdapter)
# ---------------------------------------------------------------------------
class _ConstraintAdapterFromUserData:
    def __init__(self, ud: Dict[str, Any]):
        self.constraints = ud.get("constraints", {}) or {}
        self.limits = ud.get("limits", {}) or {}

    def is_enabled(self, key: str) -> bool:
        if key in Config.CORE_CONSTRAINTS:
            return True
        return bool(self.constraints.get(key, True))

    def get_max_consecutive_hours(self) -> int:
        return int(self.limits.get("max_consecutive_classes", 3))

    def get_max_daily_hours_students(self) -> int:
        return int(self.limits.get("max_daily_hours", 6))

    def get_max_daily_hours_teachers(self) -> int:
        return int(self.limits.get("max_daily_teacher_hours", 6))


# ---------------------------------------------------------------------------
# Excel synthesis (write inputs/generated_input.xlsx in DataLoader's expected shape)
# ---------------------------------------------------------------------------
def _write_input_xlsx(ud: Dict[str, Any]) -> Path:
    GENERATED_INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Subjects sheet
    subj_rows = []
    for s in ud.get("subjects", []) or []:
        subj_rows.append({
            "Course":                s.get("course", "") or "",
            "Semester":              s.get("semester"),
            "Subject":               s.get("subject", "") or "",
            "Section":               s.get("section", "") or "",
            "Teacher":               s.get("teacher", "") or "",
            "Hours Taught(Le,Tu,Pr)": s.get("hours", "") or "",
            "Department":            s.get("department", "") or "",
            "Subject_type":          s.get("subject_type", "") or "",
            "Has_Lab":               "yes" if s.get("has_lab") else "no",
            "Notes":                 s.get("notes", "") or "",
        })
    df_subjects = pd.DataFrame(subj_rows, columns=[
        "Course", "Semester", "Subject", "Section", "Teacher",
        "Hours Taught(Le,Tu,Pr)", "Department", "Subject_type", "Has_Lab", "Notes",
    ])

    # Teachers sheet
    teacher_rows = []
    for t in ud.get("teachers", []) or []:
        teacher_rows.append({
            "Full Name": t.get("full_name", "") or "",
            "Initials":  t.get("initials", "") or "",
            "Rank":      (t.get("rank", "") or "Assistant").title(),
        })
    df_teachers = pd.DataFrame(teacher_rows, columns=["Full Name", "Initials", "Rank"])

    # Optional Teacher Preferences sheet
    pref_rows = []
    for p in ud.get("preferences", []) or []:
        off_days = p.get("off_days", []) or []
        if isinstance(off_days, list):
            off_days_str = ", ".join(off_days)
        else:
            off_days_str = str(off_days)
        pref_rows.append({
            "Full Name":      p.get("full_name", "") or "",
            "Off Days":       off_days_str,
            "Preferred Time": p.get("preferred_time", "") or "",
            "Avoid Time":     p.get("avoid_time", "") or "",
        })
    df_prefs = pd.DataFrame(pref_rows, columns=[
        "Full Name", "Off Days", "Preferred Time", "Avoid Time",
    ])

    with pd.ExcelWriter(str(GENERATED_INPUT_PATH), engine="openpyxl") as w:
        df_subjects.to_excel(w, sheet_name="Subjects",  index=False)
        df_teachers.to_excel(w, sheet_name="Teachers", index=False)
        if not df_prefs.empty:
            df_prefs.to_excel(w, sheet_name="Teacher Preferences", index=False)

    return GENERATED_INPUT_PATH


# ---------------------------------------------------------------------------
# Solution serialization
# ---------------------------------------------------------------------------
def _serialize_solution(sol: Dict[str, Any]) -> Dict[str, Any]:
    """Strip the CpSolver/CpModel internals; keep only JSON-friendly schedule data."""
    schedule = {}
    for day, slots in sol.get("master_schedule", {}).items():
        schedule[day] = {}
        for slot, classes in slots.items():
            schedule[day][slot] = []
            for c in classes:
                schedule[day][slot].append({
                    "subject":         c.get("subject"),
                    "teacher":         c.get("teacher"),
                    "teachers_list":   list(c.get("teachers_list", [])),
                    "course_semester": c.get("course_semester"),
                    "type":            c.get("type"),
                    "room":            c.get("room"),
                    "room_type":       c.get("room_type"),
                    "subject_type":    c.get("subject_type"),
                    "section":         c.get("section"),
                    "is_continuation": bool(c.get("is_continuation", False)),
                })
    return {
        "master_schedule": schedule,
        "time_slots":      [list(t) for t in sol.get("time_slots", [])],
        "slots":           list(sol.get("slots", [])),
        "max_used_slot":   int(sol.get("max_used_slot", -1)),
    }


def _build_teacher_report(sol: Dict[str, Any], loader) -> list:
    """
    Per-teacher summary used by the Results UI:
      teacher, rank, cap, scheduled_hours, satisfaction (0..100 or None),
      violations (string), and a structured details block for the UI to
      render badges with.
    """
    days  = list(Config.DAYS)
    slots = list(sol.get("slots", []))

    # Tally each teacher's scheduled (day_idx, in_day_slot_idx) tuples.
    tallies: Dict[str, list] = {name: [] for name in loader.teacher_initials.keys()}
    for day, day_sched in sol.get("master_schedule", {}).items():
        if day not in days:
            continue
        d_idx = days.index(day)
        for slot, classes in day_sched.items():
            if slot not in slots:
                continue
            s_idx = slots.index(slot)
            for c in classes:
                for full in c.get("teachers_list", []):
                    if full in tallies:
                        tallies[full].append((d_idx, s_idx))

    rows = []
    full_to_ini = loader.teacher_initials
    ini_to_pref = loader.teacher_preferences or {}

    for name in sorted(loader.teacher_initials.keys()):
        rank_lower = (loader.teacher_ranks or {}).get(name, Config.DEFAULT_TEACHER_RANK)
        cap        = Config.get_teacher_hour_cap(rank_lower)
        ini        = full_to_ini.get(name)
        pref       = ini_to_pref.get(ini, {}) if ini else {}

        scheduled = tallies.get(name, [])
        total     = len(scheduled)

        off_days        = set(pref.get("off_days", []) or [])
        avoid_slots     = set(pref.get("avoid_slots", []) or [])
        preferred_slots = set(pref.get("preferred_slots", []) or [])

        on_off  = [(d, s) for d, s in scheduled if d in off_days]
        in_avoid = [(d, s) for d, s in scheduled
                    if d not in off_days and s in avoid_slots]
        in_pref  = [(d, s) for d, s in scheduled
                    if d not in off_days and s not in avoid_slots and s in preferred_slots]

        violations_parts = []
        if on_off:
            day_names_hit = sorted({days[d] for d, _ in on_off})
            violations_parts.append(
                f"{len(on_off)} on off-day ({', '.join(day_names_hit)})"
            )
        if in_avoid:
            violations_parts.append(f"{len(in_avoid)} in avoid-time")

        if preferred_slots and total > 0:
            satisfaction = round(len(in_pref) / total * 100.0, 1)
        else:
            satisfaction = None  # no preferred-time set or no classes

        rows.append({
            "teacher":         name,
            "initials":        ini or "",
            "rank":            rank_lower.title(),
            "cap":             cap,
            "scheduled_hours": total,
            "satisfaction":    satisfaction,
            "violations":      "; ".join(violations_parts) if violations_parts else "",
            "has_preferences": bool(off_days or avoid_slots or preferred_slots),
        })
    return rows


# ---------------------------------------------------------------------------
# Pipeline runner (used by /api/solve)
# ---------------------------------------------------------------------------
def _run_pipeline(ud: Dict[str, Any], log_queue: "queue.Queue[str | None]"):
    """
    Mirror of main.py's orchestration. Streams progress via stdout; the SSE
    generator drains log_queue. On success caches the solution in
    `_last_solution_json`. Exceptions become a final ❌ ERROR log line.
    """
    class _StreamCapture(io.TextIOBase):
        def write(self, s: str) -> int:
            if s:
                for line in s.splitlines():
                    if line.strip():
                        log_queue.put(line)
            return len(s)
        def flush(self) -> None:
            pass

    try:
        # Apply user-configured rank caps and solver time limit BEFORE building.
        rc = ud.get("rank_caps", {}) or {}
        for k in ("assistant", "associate", "professor"):
            if k in rc:
                Config.TEACHER_RANK_HOUR_CAPS[k] = int(rc[k])
        Config.SOLVER_TIME_LIMIT = int(ud.get("solver_time_limit_seconds", Config.SOLVER_TIME_LIMIT))

        adapter = _ConstraintAdapterFromUserData(ud)
        semester_type = (ud.get("semester_type") or "odd").lower()
        college = ud.get("college", {}) or {}

        cap = _StreamCapture()
        with redirect_stdout(cap), redirect_stderr(cap):
            print("📋 STEP 1: DATA LOADING AND VALIDATION")
            loader = DataLoader(str(GENERATED_INPUT_PATH))
            loader.semester_type = semester_type
            if not loader.validate_data():
                raise RuntimeError("Data validation failed — see messages above.")
            if not loader.validate_config_match():
                raise RuntimeError("Config-match validation failed — see messages above.")

            subjects         = loader.get_subjects()
            teachers         = loader.get_teachers()
            rooms            = loader.get_rooms()
            course_semesters = loader.get_course_semesters()
            room_caps        = loader.get_room_capacities()

            print("\n📋 STEP 2: PRE-SOLVER FEASIBILITY CHECK")
            fc = FeasibilityChecker(subjects, room_caps, loader.teacher_ranks)
            ok, issues, _, _ = fc.check_feasibility()
            if not ok:
                for i in issues:
                    print(i)
                raise RuntimeError("Feasibility check failed — fix the issues above.")

            print("\n📋 STEP 3: BUILDING CP-SAT MODEL")
            cb = ConstraintBuilder(
                subjects, teachers, rooms, course_semesters, room_caps,
                adapter, loader.teacher_initials,
                loader.teacher_preferences, loader.teacher_ranks,
            )
            model, variables = cb.build_model()

            print("\n📋 STEP 4: SOLVING")
            se = SolverEngine(
                model, variables, subjects,
                loader.teacher_initials, loader.teacher_preferences, loader.teacher_ranks,
            )
            sol = se.solve()
            if not sol:
                raise RuntimeError("Solver returned no feasible solution.")

            print("\n📋 STEP 5: GENERATING OUTPUTS")
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            ExcelGenerator(sol, subjects).generate_master_timetable(
                str(OUTPUT_DIR / "master_timetable.xlsx")
            )
            pg = PDFGenerator(
                sol, subjects, teachers, rooms, course_semesters,
                teacher_ranks=loader.teacher_ranks,
                teacher_initials=loader.teacher_initials,
                college_name=college.get("name"),
                department=college.get("department"),
                academic_year=college.get("academic_year"),
            )
            pg.generate_teacher_timetables(str(OUTPUT_DIR / "teachers"))
            pg.generate_room_timetables(str(OUTPUT_DIR / "rooms"))
            pg.generate_course_semester_timetables(str(OUTPUT_DIR / "courses"))

            se.print_summary()

            global _last_solution_json
            _last_solution_json = _serialize_solution(sol)
            _last_solution_json["teacher_report"] = _build_teacher_report(sol, loader)
            print("\n✅ DONE — outputs written to ./output/")

    except Exception as exc:
        log_queue.put(f"❌ ERROR: {exc}")
    finally:
        log_queue.put(None)  # sentinel for the SSE generator


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    if not (STATIC_DIR / "index.html").exists():
        return "<h1>Frontend not built</h1>", 500
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    """
    Returns user_data.json plus a derived `last_generated_at` field. Derivation
    keeps the source-of-truth file untouched (no risk of clobbering user edits)
    while letting the dashboard surface the timestamp.
    """
    data = _load_user_data()
    master = OUTPUT_DIR / "master_timetable.xlsx"
    if master.exists():
        from datetime import datetime
        data["last_generated_at"] = datetime.fromtimestamp(master.stat().st_mtime).isoformat()
    else:
        data["last_generated_at"] = None
    return jsonify(data)


@app.route("/api/config", methods=["POST"])
def post_config():
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({"ok": False, "error": "JSON body required"}), 400
    body.pop("last_generated_at", None)  # derived field, never persist back
    _save_user_data(body)
    return jsonify({"ok": True})


@app.route("/api/generate-excel", methods=["POST"])
def generate_excel():
    ud = _load_user_data()
    try:
        path = _write_input_xlsx(ud)
        return jsonify({"ok": True, "path": str(path.relative_to(PROJECT_DIR))})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/solve", methods=["POST"])
def solve():
    """
    SSE streaming pipeline. Each pipeline log line is yielded as
    `data: <line>\\n\\n` so any client (browser fetch+stream reader,
    `curl --no-buffer`, EventSource-style parser) sees it immediately.
    """
    if not _solve_lock.acquire(blocking=False):
        return Response(
            "data: ❌ ERROR: another solve is already running\n\n",
            mimetype="text/event-stream",
            status=409,
        )

    ud = _load_user_data()
    log_queue: "queue.Queue[str | None]" = queue.Queue()
    worker = threading.Thread(
        target=_run_pipeline, args=(ud, log_queue), daemon=True,
    )

    def event_stream():
        worker.start()
        try:
            while True:
                item = log_queue.get()
                if item is None:
                    yield "event: done\ndata: \n\n"
                    return
                # Escape any embedded newlines (paranoia; we already split lines)
                safe = item.replace("\r", "").replace("\n", " ")
                yield f"data: {safe}\n\n"
        finally:
            _solve_lock.release()

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering when fronted
        },
    )


@app.route("/api/results", methods=["GET"])
def results():
    if not _last_solution_json:
        return jsonify({"error": "No solution yet — run /api/solve first."}), 404
    return jsonify(_last_solution_json)


@app.route("/api/download/zip", methods=["GET"])
def download_zip():
    if not OUTPUT_DIR.exists() or not any(OUTPUT_DIR.rglob("*")):
        return jsonify({"error": "No output yet — run /api/solve first."}), 404
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in OUTPUT_DIR.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(OUTPUT_DIR)))
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="timetable_output.zip",
    )


@app.route("/api/download/excel", methods=["GET"])
def download_excel():
    path = OUTPUT_DIR / "master_timetable.xlsx"
    if not path.exists():
        return jsonify({"error": "master_timetable.xlsx not generated yet."}), 404
    return send_file(
        str(path),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="master_timetable.xlsx",
    )


# Permissive CORS for the browser-only local case so swapping BASE_URL to a
# remote backend later is just a one-line change in static/api.js.
@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
