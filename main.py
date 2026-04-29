from pathlib import Path

from src.solver.csp_algorithm import solve_csp
from src.utils.excel_parser import ExcelParser


def build_timetable_grid(solution):
	grid = {}
	if not solution:
		return grid

	timeslot_order = []
	for assignment in solution.values():
		label = f"{assignment.timeslot.start_time.strftime('%H:%M')}-{assignment.timeslot.end_time.strftime('%H:%M')}"
		if label not in timeslot_order:
			timeslot_order.append(label)

	timeslot_order.sort()
	day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
	for day in day_order:
		grid[day] = {label: "" for label in timeslot_order}

	for course, assignment in solution.items():
		time_label = f"{assignment.timeslot.start_time.strftime('%H:%M')}-{assignment.timeslot.end_time.strftime('%H:%M')}"
		cell = f"{course.code} {course.section} | {assignment.room.room_name}"
		grid[assignment.timeslot.day][time_label] = cell

	return grid


def print_timetable_grid(grid):
	if not grid:
		print("No timetable data to display.")
		return

	time_columns = list(next(iter(grid.values())).keys())
	headers = ["Day"] + time_columns
	widths = {header: len(header) for header in headers}

	for day, row in grid.items():
		widths["Day"] = max(widths["Day"], len(day))
		for label, value in row.items():
			widths[label] = max(widths[label], len(value))

	header_line = " | ".join(header.ljust(widths[header]) for header in headers)
	separator = "-+-".join("-" * widths[header] for header in headers)
	print(header_line)
	print(separator)

	for day, row in grid.items():
		line = [day.ljust(widths["Day"])]
		for label in time_columns:
			line.append(row[label].ljust(widths[label]))
		print(" | ".join(line))


def main() -> None:
	root = Path(__file__).resolve().parent
	parser = ExcelParser(root / "data" / "raw")

	rooms = parser.load_rooms("rooms.xlsx")
	courses = parser.load_course_sessions("fcse.xlsx")
	timeslots = parser.generate_timeslots()

	solution = solve_csp(courses, rooms, timeslots, use_lcv=False)

	print("Course | Section | Teacher | Room | Day | Time")
	print("-" * 72)

	if solution is None:
		print("No valid timetable found.")
		return

	grid = build_timetable_grid(solution)
	print_timetable_grid(grid)


if __name__ == "__main__":
	main()