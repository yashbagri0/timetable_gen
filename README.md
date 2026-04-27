# Timetable Generator

A constraint-based university timetable generator that runs locally as a small web app — define teachers, subjects, and preferences in the browser, the OR-Tools CP-SAT solver builds a clash-free schedule, and the result downloads as Excel + per-teacher / per-room / per-course PDFs.

## Quick Start

```bash
git clone <repo-url>
cd timetable-generator
python setup_venv.py

# Activate venv:
#   Windows:    venv\Scripts\activate
#   Mac/Linux:  source venv/bin/activate

cd project
python run.py
# opens http://localhost:5000 in your browser automatically
```

Stop with `Ctrl+C`.

## Using the App

The sidebar walks you through a one-time setup, then a Generate run.

1. **Configuration** — college name, department, academic year, semester (odd/even), per-rank weekly hour caps, solver time limit, optional constraints.
2. **Teachers** — name + initials (auto-derived from full name) + rank (Assistant / Associate / Professor) + department.
3. **Subjects** — course, semester, subject, section, teacher(s), hours (Le / Tu / Pr), department, type (DSC / DSE / GE / SEC / VAC / AEC), and a Has-Lab toggle. Teaching mode picks Normal / Co-teaching / Split.
4. **Preferences** *(optional, soft constraints)* — off days + preferred / avoid time-of-day per teacher.
5. **Generate** — pre-flight checklist gates the buttons. Click **Build Excel from Config**, then **Run Solver**. Logs stream live and a 5-step progress bar lights up green as each pipeline stage completes.
6. **Results** — three tabs (Teacher / Room / Course Timetables) with an interactive grid, a per-teacher preference summary, and download buttons for the master Excel + a zip of all PDFs.

Configuration is persisted to `project/config/user_data.json` after every save, so it's a one-time setup unless your inputs change.

## Input Excel Format

If you'd rather skip the UI and feed the solver directly, drop an `.xlsx` into `project/inputs/` and call the pipeline programmatically (or wire `DataLoader` against your own file). Three sheets are required:

**Subjects** — one row per (course, subject, section).

| Column | Notes |
|---|---|
| `Course` | short form (e.g. `CS(H)`) or full name; can be blank for GE/SEC/VAC/AEC |
| `Semester` | `1`–`8` |
| `Subject` | display name |
| `Section` | `A` / `B` / `C` …; required when a subject repeats in the same semester |
| `Teacher` | full name; for **co-teaching** join with `,` (`Alice, Bob`); for **split-teaching** join with `\|` (`Alice \| Bob`) |
| `Hours Taught(Le,Tu,Pr)` | `3,0,2` — for split-teaching match the `\|` count: `1,0,1 \| 2,0,1` |
| `Department` | must match a department in your Teachers sheet |
| `Subject_type` | `DSC` / `DSE` / `GE` / `SEC` / `VAC` / `AEC` |
| `Has_Lab` | `yes` / `no` |
| `Notes` | optional |

**Teachers** — one row per teacher; initials must be unique.

| Column | Notes |
|---|---|
| `Full Name` | exact match required everywhere this teacher is referenced |
| `Initials` | 2–4 chars, unique |
| `Rank` | `Assistant` / `Associate` / `Professor` (case-insensitive) |

**Teacher Preferences** *(optional)* — soft constraints that shape the objective but never make the model infeasible.

| Column | Notes |
|---|---|
| `Full Name` | must exist in the Teachers sheet |
| `Off Days` | comma-separated day names (`Monday, Wednesday`) |
| `Preferred Time` | `Morning` / `Afternoon` / `Evening` |
| `Avoid Time` | `Morning` / `Afternoon` / `Evening` |

## Configuration

Two files control behavior:

- **`project/config/user_data.json`** — UI settings (college name, rank caps, semester type, optional constraints, plus all teacher/subject/preference rows). Edit through the app or directly; the API rewrites it on every Save.
- **`project/src/config.py`** — advanced/static tuning. Look here for:
  - `FIXED_SLOTS` — when GE / SEC / VAC / AEC classes can be scheduled (per year)
  - `ROOMS` — every classroom and lab with capacity and department mapping
  - `PENALTY_WEIGHTS` — soft-constraint costs (oversized room, undersized room, isolated practical, theory in lab, etc.)
  - **`TEACHER_RANK_HOUR_CAPS`** — weekly hour limit per rank, e.g. `{"assistant": 14, "associate": 14, "professor": 16}`. The data loader and CP-SAT model both look up each teacher's cap by their stored rank.
  - **`TEACHER_PREF_WEIGHTS`** — objective coefficients for soft preference terms. Defaults: `off_day = 200`, `avoid_time = 150`, `preferred_time_bonus = 50`. Tuned to dominate the routine soft constraints (50 – 100) without overriding worst-case room-fit penalties (~2400) so a real conflict still wins.
- `config/timetable_config.yml` is auto-generated and only carries solver run-time settings (currently `solver.time_limit_seconds`).

## Architecture

```
project/
├── api.py              ← Flask app, all REST + SSE endpoints
├── run.py              ← localhost:5000 launcher (opens the browser)
├── src/                ← solver pipeline (data_loader → feasibility_checker
│                          → constraint_builder → solver_engine →
│                          excel_generator + pdf_generator)
├── static/             ← vanilla HTML / CSS / JS SPA
│   └── api.js          ← BASE_URL = "http://localhost:5000"
├── config/user_data.json
├── inputs/             ← user-supplied or UI-generated .xlsx files
└── output/             ← generated PDFs and Excel
```

- The Flask layer (`api.py`) imports the solver modules directly — no subprocesses, no IPC. The pipeline runs in a worker thread; stdout is captured and forwarded as SSE so the browser sees the same logs `main.py` would print.
- The UI is a single-page vanilla-JS app — no build step, no bundler. To point at a remote backend, change one line in **`static/api.js`**: `const BASE_URL = "https://your-backend.example";`.
- The solver itself (everything in `src/`) doesn't know about HTTP; you can still drive it from a script if you prefer.

## Troubleshooting

**Solver returns INFEASIBLE.** Common causes:
- A teacher is loaded above their per-rank cap (`Configuration → Teacher Hour Caps`). Bump the cap or split the load.
- A VAC / SEC / AEC subject is in a year that has no fixed slots configured (`VAC` is only valid for Sem 1–4; `SEC` for Sem 1–6; `AEC` is universal). The Feasibility Check step in the Generate page surfaces this with the exact subject + semester.
- A practical is using a department lab that's too small for its student count — see the `room_penalty` numbers in the solver log; if they're huge, either grow the lab in `Config.ROOMS` or split the section.

**Port 5000 already in use.**
```bash
# Mac / Linux
lsof -ti:5000 | xargs kill

# Windows
netstat -ano | findstr :5000
taskkill /PID <pid> /F
```

**`ModuleNotFoundError`.** The venv isn't active or the deps are stale:
```bash
pip install -r requirements.txt
```

**`/api/results` returns 404.** The cached solution lives in process memory only — restarting the Flask server clears it. Re-run the solver.

## Requirements

- Python 3.9+
- Dependencies pinned in `requirements.txt` (OR-Tools 9+, pandas, openpyxl, reportlab, Flask).
