from src.utils.excel_parser import ExcelParser
from src.solver.csp_algorithm import solve_csp
from src.solver.constraints import build_domain, define_variables
from pathlib import Path
import time

p = ExcelParser(Path('data/raw'))
rooms = p.load_rooms('rooms.xlsx')
courses = p.load_course_sessions('fcse.xlsx')
ts = p.generate_timeslots()

print(f"Total rooms: {len(rooms)}")
print(f"Total courses (expanded): {len(courses)}")
print(f"Total timeslots: {len(ts)}")

# Check room types
lecture_rooms = [r for r in rooms if 'lab' not in (r.room_type or '').lower()]
lab_rooms = [r for r in rooms if 'lab' in (r.room_type or '').lower()]
print(f"Lecture rooms: {len(lecture_rooms)}, Lab rooms: {len(lab_rooms)}")

# Check course types
lecture_courses = [c for c in courses if c.course_type != 'lab']
lab_courses = [c for c in courses if c.course_type == 'lab']
print(f"Lecture course sessions: {len(lecture_courses)}, Lab course sessions: {len(lab_courses)}")

# Check capacity constraint (credit_hours vs room capacity)
problem_domains = 0
section_courses_A = [c for c in courses if c.section == 'A']
print(f"\nSection A courses: {len(section_courses_A)}")
for course in section_courses_A[:5]:
    domain = build_domain(course, rooms, ts)
    print(f"  {course.code} (type={course.course_type}, credit_hours={course.credit_hours}) -> domain size={len(domain)}")
    if len(domain) == 0:
        problem_domains += 1

print(f"\nTesting CSP for section A...")
start = time.monotonic()
sol = solve_csp(section_courses_A, rooms, ts, use_lcv=True, max_seconds=30)
elapsed = time.monotonic() - start
if sol:
    print(f"SOLUTION FOUND: {len(sol)} assignments in {elapsed:.2f}s")
else:
    print(f"NO SOLUTION found in {elapsed:.2f}s")

# Check constraints issue: room capacity uses credit_hours=1 (since sessions are split)
print("\n--- Capacity Check ---")
print("All sessions have credit_hours=1 after splitting:", all(c.credit_hours == 1 for c in courses))
print("Room capacity filter: room.capacity < course.credit_hours")
print("=> Since credit_hours=1, rooms with capacity >= 1 pass (almost all rooms)")
print("This constraint is MEANINGLESS. Rooms are never filtered by student enrollment.")
