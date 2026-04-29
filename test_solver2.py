from src.utils.excel_parser import ExcelParser
from src.solver.csp_algorithm import solve_csp, SolveTimeoutError
from pathlib import Path
import time

p = ExcelParser(Path('data/raw'))
rooms = p.load_rooms('rooms.xlsx')
courses = p.load_course_sessions('fcse.xlsx')
ts = p.generate_timeslots()

sections = sorted(set(c.section for c in courses if c.section and c.section.strip() != ''))
print(f"All sections: {sections}")
print(f"Timeslots per day: {len(ts)//5}, Total: {len(ts)}")

print("\n--- Per-section course counts ---")
for sec in sections:
    sc = [c for c in courses if c.section == sec]
    print(f"  Section {sec}: {len(sc)} sessions")

print("\n--- Testing each section individually (max 15s each) ---")
failed = []
succeeded = []
for sec in sections:
    sc = [c for c in courses if c.section == sec]
    start = time.monotonic()
    try:
        sol = solve_csp(sc, rooms, ts, use_lcv=True, max_seconds=15)
        elapsed = time.monotonic() - start
        if sol:
            print(f"  Section {sec}: FOUND ({len(sol)} assignments, {elapsed:.1f}s)")
            succeeded.append(sec)
        else:
            print(f"  Section {sec}: NO SOLUTION ({elapsed:.1f}s)")
            failed.append(sec)
    except SolveTimeoutError:
        elapsed = time.monotonic() - start
        print(f"  Section {sec}: TIMEOUT ({elapsed:.1f}s)")
        failed.append(sec)

print(f"\nSucceeded: {succeeded}")
print(f"Failed/Timeout: {failed}")

# Check the meeting_index expansion issue in define_variables
from src.solver.constraints import define_variables
all_vars = define_variables(courses)
print(f"\nVariables after define_variables: {len(all_vars)}")
print(f"Original courses: {len(courses)}")
# meeting_index=1 courses should be expanded
mi1 = [c for c in courses if c.meeting_index == 1]
mi_other = [c for c in courses if c.meeting_index != 1]
print(f"Courses with meeting_index=1: {len(mi1)} (these get re-expanded!)")
print(f"Courses with meeting_index>1: {len(mi_other)}")
