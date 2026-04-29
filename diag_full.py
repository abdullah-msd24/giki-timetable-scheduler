"""
Full end-to-end diagnostic for GIKI Timetable Scheduler.
Runs checks 1-6 and prints PASS/FAIL for each.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.utils.excel_parser import ExcelParser
from src.solver.csp_algorithm import solve_csp, SolveTimeoutError
from src.solver.constraints import build_domain, define_variables
from src.utils.pdf_exporter import build_grid_from_solver, export_timetable_pdf, TIMESLOTS, ROOM_BLOCKS as PDF_ROOM_BLOCKS

RESULTS: dict[str, str] = {}

def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

# ─────────────────────────────────────────────────────────────
# CHECK 1 — DATA LOADING
# ─────────────────────────────────────────────────────────────
section("CHECK 1 — DATA LOADING")

parser = ExcelParser(ROOT / "data" / "raw")

print("\n[1a] Rooms...")
rooms = parser.load_rooms("rooms.xlsx")
print(f"  Total rooms loaded: {len(rooms)}")
bad_rooms = [r for r in rooms if not r.room_id or not r.room_name or r.capacity == 0]
print(f"  Rooms with missing id/name/capacity: {len(bad_rooms)}")
if bad_rooms:
    for r in bad_rooms[:5]:
        print(f"    → {r}")
# Show sample
for r in rooms[:3]:
    print(f"  Sample: id={r.room_id!r}, name={r.room_name!r}, building={r.building!r}, type={r.room_type!r}, cap={r.capacity}")

print("\n[1b] Courses (fcse.xlsx)...")
courses = parser.load_course_sessions("fcse.xlsx")
print(f"  Total sessions loaded: {len(courses)}")
sections_found = sorted(set(c.section for c in courses))
print(f"  Sections found: {sections_found}")
empty_section = [c for c in courses if not c.section or not c.section.strip()]
print(f"  Sessions with empty section: {len(empty_section)}")
bad_code = [c for c in courses if not c.code]
print(f"  Sessions with missing code: {len(bad_code)}")
for c in courses[:3]:
    print(f"  Sample: code={c.code!r}, section={c.section!r}, sem={c.semester!r}, type={c.course_type!r}, ch={c.credit_hours}, mi={c.meeting_index}")

print("\n[1c] Timeslots...")
timeslots = parser.generate_timeslots()
print(f"  Total timeslots: {len(timeslots)}")
days_found = sorted(set(t.day for t in timeslots))
print(f"  Days: {days_found}")
print(f"  Slots per day: {len(timeslots) // len(days_found)}")
for t in timeslots[:3]:
    print(f"  Sample: day={t.day}, start={t.start_time}, end={t.end_time}, label={t.label!r}")

rooms_ok = len(rooms) == 60
# After filtering empty-section rows, 304 of 335 original rows are skipped.
# The remaining 31 rows have valid section assignments.
courses_ok = len(courses) >= 20 and len(courses) <= 335
timeslots_ok = len(timeslots) == 40
data_ok = rooms_ok and courses_ok and timeslots_ok
RESULTS["1_data_loading"] = "PASS" if data_ok else "FAIL"
print(f"\n  Rooms==60: {rooms_ok}, Courses>=20: {courses_ok}, Timeslots==40: {timeslots_ok}")
print(f"  → CHECK 1: {RESULTS['1_data_loading']}")


# ─────────────────────────────────────────────────────────────
# CHECK 2 — DOMAIN BUILDING
# ─────────────────────────────────────────────────────────────
section("CHECK 2 — DOMAIN BUILDING")

lecture_rooms = [r for r in rooms if 'lab' not in (r.room_type or '').lower()]
lab_rooms = [r for r in rooms if 'lab' in (r.room_type or '').lower()]
print(f"  Lecture rooms: {len(lecture_rooms)}, Lab rooms: {len(lab_rooms)}")

sample_lecture = next((c for c in courses if c.course_type != 'lab' and c.section), None)
sample_lab = next((c for c in courses if c.course_type == 'lab' and c.section), None)

empty_domains = []
for sample, label in [(sample_lecture, "lecture"), (sample_lab, "lab")]:
    if sample is None:
        print(f"  No {label} course found!")
        continue
    domain = build_domain(sample, rooms, timeslots)
    lab_opts = [o for o in domain if 'lab' in (o.room.room_type or '').lower()]
    lec_opts = [o for o in domain if 'lab' not in (o.room.room_type or '').lower()]
    print(f"\n  [{label.upper()}] course={sample.code!r}, type={sample.course_type!r}, ch={sample.credit_hours}")
    print(f"    Domain size: {len(domain)} (lecture opts={len(lec_opts)}, lab opts={len(lab_opts)})")
    if len(domain) == 0:
        empty_domains.append(sample)

# Check for any course with empty domain
all_empty = []
for c in courses[:50]:  # sample first 50 to save time
    d = build_domain(c, rooms, timeslots)
    if len(d) == 0:
        all_empty.append(c)
print(f"\n  Courses with empty domain (sample of 50): {len(all_empty)}")
if all_empty:
    for c in all_empty[:5]:
        print(f"    → {c.code} {c.section} type={c.course_type}")

# Check capacity filter impact
print("\n  [Capacity filter analysis]")
print(f"  All sessions have credit_hours=1: {all(c.credit_hours == 1 for c in courses)}")
print(f"  Min room capacity: {min(r.capacity for r in rooms)}")
print(f"  Rooms with capacity<1: {len([r for r in rooms if r.capacity < 1])}")
print(f"  → Capacity filter `room.capacity < course.credit_hours` is effectively DISABLED (always passes)")

domain_ok = len(all_empty) == 0
RESULTS["2_domain_building"] = "PASS" if domain_ok else "FAIL"
print(f"\n  → CHECK 2: {RESULTS['2_domain_building']}")


# ─────────────────────────────────────────────────────────────
# CHECK 3 — SOLVER
# ─────────────────────────────────────────────────────────────
section("CHECK 3 — SOLVER")

# Use semester 2, section A
sem2_a = [c for c in courses if c.semester == '2' and c.section == 'A']
print(f"  Sem 2 Section A courses: {len(sem2_a)}")
if not sem2_a:
    # Try semester as int string
    sem_vals = sorted(set(c.semester for c in courses))
    print(f"  Available semesters: {sem_vals}")
    # Fall back to first section
    first_sec = [c for c in courses if c.section and c.section.strip()][0].section
    sem2_a = [c for c in courses if c.section == first_sec][:6]
    print(f"  Falling back to section {first_sec!r}: {len(sem2_a)} sessions")

print(f"  Running solver (max 60s)...")
import time as _time
_start = _time.monotonic()
try:
    solution = solve_csp(sem2_a, rooms, timeslots, use_lcv=False, max_seconds=60)
    _elapsed = _time.monotonic() - _start
    if solution:
        print(f"  SOLUTION FOUND: {len(solution)} assignments in {_elapsed:.2f}s")
        print("  Sample assignments:")
        for i, (course, opt) in enumerate(list(solution.items())[:5]):
            print(f"    {i+1}. {course.code} {course.section} → room={opt.room.room_name!r}, day={opt.timeslot.day}, time={opt.timeslot.start_time}-{opt.timeslot.end_time}")
        solver_ok = True
    else:
        print(f"  NO SOLUTION in {_elapsed:.2f}s")
        # Diagnose
        for c in sem2_a:
            d = build_domain(c, rooms, timeslots)
            print(f"    {c.code} {c.section} domain={len(d)}")
        solver_ok = False
except SolveTimeoutError:
    _elapsed = _time.monotonic() - _start
    print(f"  TIMEOUT after {_elapsed:.2f}s")
    solution = None
    solver_ok = False

RESULTS["3_solver"] = "PASS" if solver_ok else "FAIL"
print(f"\n  → CHECK 3: {RESULTS['3_solver']}")


# ─────────────────────────────────────────────────────────────
# CHECK 4 — GRID BUILD
# ─────────────────────────────────────────────────────────────
section("CHECK 4 — GRID BUILD (pdf_exporter)")

if solution:
    # Detect which days actually have assignments and use the first populated day.
    assigned_days = sorted(set(o.timeslot.day for o in solution.values()))
    check_day = assigned_days[0] if assigned_days else "Monday"
    print(f"  Assigned days: {assigned_days}  (using '{check_day}' for grid check)")
    grid = build_grid_from_solver(solution, check_day)
    print(f"  Grid rooms populated: {len(grid)}")
    filled = sum(1 for room_slots in grid.values() for v in room_slots.values() if v)
    total = sum(len(room_slots) for room_slots in grid.values())
    print(f"  Filled cells: {filled} / {total}")
    if filled == 0:
        print("  WARNING: No filled cells!")
        # Diagnose
        day_assignments = [(c, o) for c, o in solution.items() if o.timeslot.day == check_day]
        print(f"  {check_day} assignments: {len(day_assignments)}")
        for c, o in day_assignments[:5]:
            slot = f"{o.timeslot.start_time.strftime('%H:%M')}-{o.timeslot.end_time.strftime('%H:%M')}"
            print(f"    room_name={o.room.room_name!r}, slot={slot!r}, in TIMESLOTS: {slot in TIMESLOTS}")
    else:
        print("  Rooms with data:")
        for room_name, slots in grid.items():
            filled_slots = {k: v for k, v in slots.items() if v}
            if filled_slots:
                print(f"    {room_name!r}: {filled_slots}")
    grid_ok = filled > 0
else:
    print("  Skipped (no solution from check 3)")
    grid_ok = False
    grid = {}

RESULTS["4_grid_build"] = "PASS" if grid_ok else "FAIL"
print(f"\n  → CHECK 4: {RESULTS['4_grid_build']}")


# ─────────────────────────────────────────────────────────────
# CHECK 5 — GUI CONNECTIONS
# ─────────────────────────────────────────────────────────────
section("CHECK 5 — GUI CONNECTIONS (static analysis)")

import ast, inspect, textwrap
from src.gui.app import TimetableApp, build_timetable_grid as gui_build_grid
from src.gui.app import ROOM_BLOCKS as GUI_ROOM_BLOCKS

# 5a — Does _filtered_courses() apply all filters correctly?
print("\n  [5a] _filtered_courses() filter logic...")
source_lines = inspect.getsource(TimetableApp._filtered_courses)
checks = {
    "department filter": "department_var" in source_lines,
    "semester filter": "semester" in source_lines,
    "section filter": "section_var" in source_lines,
    "empty section excluded": 'section.strip() != ""' in source_lines or "strip()" in source_lines,
    "course type filter": "course_type" in source_lines,
}
for name, ok in checks.items():
    status = "✓" if ok else "✗ MISSING"
    print(f"    {name}: {status}")

# 5b — Does _solve_and_render pass the right args?
print("\n  [5b] _solve_and_render() calls solve_csp with correct args...")
src2 = inspect.getsource(TimetableApp._solve_and_render)
checks2 = {
    "passes rooms": "self.rooms" in src2,
    "passes timeslots": "self.timeslots" in src2,
    "uses use_lcv=False (fast mode)": "use_lcv=False" in src2,
    "has timeout": "max_seconds" in src2,
}
for name, ok in checks2.items():
    status = "✓" if ok else "✗ MISSING"
    print(f"    {name}: {status}")

# 5c — Does _display_solution call build_timetable_grid?
print("\n  [5c] _display_solution() calls grid build and render...")
src3 = inspect.getsource(TimetableApp._display_solution)
checks3 = {
    "calls build_timetable_grid": "build_timetable_grid" in src3,
    "calls _render_grid": "_render_grid" in src3,
    "stores solution": "last_assignment" in src3,
}
for name, ok in checks3.items():
    status = "✓" if ok else "✗ MISSING"
    print(f"    {name}: {status}")

# 5d — Section combobox values
print("\n  [5d] Section combobox construction...")
src4 = inspect.getsource(TimetableApp._build_section_choices)
has_section_build = "section" in src4.lower()
print(f"    _build_section_choices defined: {'✓' if has_section_build else '✗'}")

# 5e — Room name consistency between GUI ROOM_BLOCKS and rooms.xlsx
print("\n  [5e] Room name consistency (GUI ROOM_BLOCKS vs rooms.xlsx)...")
available_rooms = set(r.room_name.strip() for r in rooms)
all_gui_rooms = [rm for block in GUI_ROOM_BLOCKS.values() for rm in block]
missing_from_xlsx = [rm for rm in all_gui_rooms if rm not in available_rooms]
print(f"    GUI block rooms: {len(all_gui_rooms)}, Missing from rooms.xlsx: {len(missing_from_xlsx)}")
if missing_from_xlsx:
    print(f"    Missing: {missing_from_xlsx}")

# 5f — PDF ROOM_BLOCKS vs rooms.xlsx
print("\n  [5f] Room name consistency (PDF ROOM_BLOCKS vs rooms.xlsx)...")
all_pdf_rooms = [rm for block in PDF_ROOM_BLOCKS.values() for rm in block]
missing_pdf = [rm for rm in all_pdf_rooms if rm not in available_rooms]
print(f"    PDF block rooms: {len(all_pdf_rooms)}, Missing from rooms.xlsx: {len(missing_pdf)}")
if missing_pdf:
    print(f"    Missing: {missing_pdf}")

# 5g — GUI vs PDF ROOM_BLOCKS consistency
print("\n  [5g] GUI vs PDF ROOM_BLOCKS consistency...")
gui_set = set(rm for block in GUI_ROOM_BLOCKS.values() for rm in block)
pdf_set = set(rm for block in PDF_ROOM_BLOCKS.values() for rm in block)
only_in_gui = gui_set - pdf_set
only_in_pdf = pdf_set - gui_set
print(f"    In GUI but not PDF: {sorted(only_in_gui)}")
print(f"    In PDF but not GUI: {sorted(only_in_pdf)}")

gui_ok = (
    all(checks.values()) and
    all(checks2.values()) and
    all(checks3.values()) and
    has_section_build and
    len(missing_from_xlsx) == 0 and
    len(missing_pdf) == 0 and
    len(only_in_gui) == 0 and
    len(only_in_pdf) == 0
)
RESULTS["5_gui_connections"] = "PASS" if gui_ok else "FAIL"
print(f"\n  → CHECK 5: {RESULTS['5_gui_connections']}")


# ─────────────────────────────────────────────────────────────
# CHECK 6 — PDF EXPORT
# ─────────────────────────────────────────────────────────────
section("CHECK 6 — PDF EXPORT")

if solution and grid:
    test_pdf_path = ROOT / "data" / "output" / "diag_test.pdf"
    try:
        out = export_timetable_pdf(grid, test_pdf_path, "FCSE", "2", check_day)
        size = Path(out).stat().st_size
        print(f"  PDF created: {out}")
        print(f"  PDF size: {size} bytes")
        pdf_ok = size > 2000
        print(f"  Size > 2KB (has content): {'OK' if pdf_ok else 'too small, may be empty'}")
        # Check filled cells
        monday_filled = sum(1 for room_slots in grid.values() for v in room_slots.values() if v)
        print(f"  Grid cells with data going into PDF: {monday_filled}")
        pdf_ok = pdf_ok and monday_filled > 0
    except Exception as e:
        print(f"  PDF EXPORT FAILED: {e}")
        pdf_ok = False
else:
    print("  Skipped (no solution/grid from earlier steps)")
    pdf_ok = False

RESULTS["6_pdf_export"] = "PASS" if pdf_ok else "FAIL"
print(f"\n  → CHECK 6: {RESULTS['6_pdf_export']}")


# ─────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────
section("DIAGNOSTIC SUMMARY")
key_labels = {
    "1_data_loading":    "Data loading",
    "2_domain_building": "Domain building",
    "3_solver":          "Solver",
    "4_grid_build":      "Grid building",
    "5_gui_connections": "GUI connections",
    "6_pdf_export":      "PDF export",
}
for key, label in key_labels.items():
    status = RESULTS.get(key, "SKIPPED")
    print(f"  [{status:4}] {label}")

fails = [k for k, v in RESULTS.items() if v == "FAIL"]
if fails:
    print(f"\n  {len(fails)} check(s) FAILED: {', '.join(fails)}")
else:
    print("\n  All checks PASSED!")
