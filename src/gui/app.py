from __future__ import annotations

from datetime import datetime
import subprocess
import time
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from src.solver.csp_algorithm import SolveTimeoutError, solve_csp
from src.utils.excel_parser import ExcelParser
from src.utils.pdf_exporter import TIMESLOTS, build_grid_from_solver, export_full_week_pdf, export_timetable_pdf


DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
FULL_WEEK_LABEL = "Full Week"
DAY_VALUES = [FULL_WEEK_LABEL] + DAY_ORDER

# Room layout grouped by building block.
# Names MUST exactly match the room_name column in rooms.xlsx.
ROOM_BLOCKS = {
	"FCSE/FEE Block": [
		"CS LH1", "CS LH2", "CS LH3", "CS LH4",
		"EE LH1", "EE LH2", "EE LH3", "EE LH4", "EE Main",
		"FEE Quiz Hall",
	],
	"FES Block": ["ES LH1", "ES LH2", "ES LH3", "ES LH4", "ES Main", "FES - SE Lab", "FES - PH Lab", "FES - PH Lab 2", "FES Quiz Hall"],
	"Academic Block": [
		"AcB LH1",
		"AcB LH2",
		"AcB LH3",
		"AcB LH4",
		"AcB LH5",
		"AcB LH6",
		"AcB LH7",
		"AcB LH8",
		"AcB LH9",
		"AcB LH10",
		"AcB LH11",
		"AcB LH12",
		"AcB Main1",
		"AcB Main2",
		"AcB Main3",
		"ACB - AI Lab",
		"ACB - CYS Lab",
		"ACB - DA Lab",
	],
	"BB Block": ["BB Main", "BB LH2", "BB EH1", "BB EH2", "BB EH3", "BB EH4", "BB PC Lab"],
	"FME Block": ["ME LH1", "ME LH2", "ME LH3", "ME Main", "FME Lab", "FME Quiz Hall"],
	"FMCE Block": ["MCE LH1", "MCE LH2", "MCE LH3", "MCE LH4", "MCE Main", "FCME Quiz Hall", "FCME - CH Lab", "FCME - MM Lab"],
	"Other": ["FBS Lab", "TBA"],
}


def build_timetable_grid(solution: dict, selected_day: str) -> dict:
	"""Build a day-specific or full-week grid for the GUI."""
	if selected_day != FULL_WEEK_LABEL:
		return build_grid_from_solver(solution, selected_day)

	day_prefixes = {
		"Monday": "MON",
		"Tuesday": "TUE",
		"Wednesday": "WED",
		"Thursday": "THU",
		"Friday": "FRI",
	}

	def _prefix_cell(prefix: str, text: str) -> str:
		lines = [line for line in text.splitlines() if line.strip()]
		return "\n".join(f"{prefix}\n{line}" for line in lines)

	combined: dict[str, dict[str, str]] = {}
	for day in DAY_ORDER:
		day_grid = build_grid_from_solver(solution, day)
		prefix = day_prefixes.get(day, day[:3].upper())
		for room_name, slots in day_grid.items():
			room_row = combined.setdefault(room_name, {label: "" for label in TIMESLOTS})
			for label, cell_text in slots.items():
				if not cell_text:
					continue
				prefixed = _prefix_cell(prefix, cell_text)
				if room_row[label]:
					room_row[label] = f"{room_row[label]}\n{prefixed}"
				else:
					room_row[label] = prefixed

	return combined


def _find_teacher_conflicts(solution: dict) -> list[tuple]:
	"""Return a list of (course_a, course_b) pairs with a TRUE teacher clash.

	When per-section solutions are merged the inner solver never sees the
	combined assignment, so cross-section teacher conflicts are only caught
	here in a post-merge pass.

	A TRUE conflict means:
	  - Same instructor
	  - Same day + timeslot
	  - DIFFERENT course code  ← key distinction

	Same-course / different-section at the same slot is NOT a conflict —
	it models a shared lecture where one instructor teaches all sections
	simultaneously (e.g. CS101 taught to sections A, B, C at once).
	"""
	conflicts: list[tuple] = []
	items = list(solution.items())
	for i, (course_a, opt_a) in enumerate(items):
		instructor_a = (course_a.instructor or "").strip()
		if not instructor_a:
			continue
		for course_b, opt_b in items[i + 1:]:
			if (course_b.instructor or "").strip() != instructor_a:
				continue
			# Same course taught to multiple sections simultaneously → allowed.
			if course_a.code == course_b.code:
				continue
			if (
				opt_a.timeslot.day == opt_b.timeslot.day
				and opt_a.timeslot.start_time == opt_b.timeslot.start_time
				and opt_a.timeslot.end_time == opt_b.timeslot.end_time
			):
				conflicts.append((course_a, course_b))
	return conflicts


class TimetableApp:
	def __init__(self):
		self.root = tk.Tk()
		self.root.title("GIKI Timetable Scheduler")
		self.root.geometry("1400x800")
		self.root.state("zoomed")

		self.project_root = Path(__file__).resolve().parents[2]
		self.parser = ExcelParser(self.project_root / "data" / "raw")
		self.rooms = self.parser.load_rooms("rooms.xlsx")
		self.department_courses = self._load_department_courses()
		self.timeslots = self.parser.generate_timeslots()
		self.timeslot_labels = []
		seen_labels: set[str] = set()
		for slot in self.timeslots:
			label = f"{slot.start_time.strftime('%H:%M')}-{slot.end_time.strftime('%H:%M')}"
			if label in seen_labels:
				continue
			seen_labels.add(label)
			self.timeslot_labels.append(label)
		self.department_choices = sorted(self.department_courses.keys())
		self.department_var = tk.StringVar(value=self.department_choices[0])
		self.day_var = tk.StringVar(value=FULL_WEEK_LABEL)
		self.available_room_names = [room.room_name for room in self.rooms]
		self.room_layout = self._build_room_layout()
		self.semesters = self._build_semester_choices(self._selected_department_courses())
		self.semester_var = tk.StringVar(value=self.semesters[1] if len(self.semesters) > 1 else "All")
		self.section_var = tk.StringVar(value="All")
		self.course_type_var = tk.StringVar(value="All")
		initial_section_courses = [
			course
			for course in self._selected_department_courses()
			if self.semester_var.get() == "All" or course.semester == self.semester_var.get()
		]
		if self.course_type_var.get() == "Lab":
			initial_section_courses = [course for course in initial_section_courses if course.course_type == "lab"]
		elif self.course_type_var.get() == "Lecture":
			initial_section_courses = [course for course in initial_section_courses if course.course_type != "lab"]
		self.section_choices = self._build_section_choices(initial_section_courses)
		self.last_assignment = None
		self.last_solve_note = ""
		self.solve_in_progress = False

		self._build_styles()
		self._build_ui()

	def _load_department_courses(self) -> dict[str, list]:
		"""Load all course sessions grouped by program/department.

		Prefers the unified courses.csv (new format) if present.
		Falls back to per-department .xlsx files (old format) otherwise.
		"""
		courses_csv = self.parser.raw_data_dir / "courses.csv"
		if courses_csv.exists():
			courses_by_department = self.parser.load_all_courses_by_program("courses.csv")
			if courses_by_department:
				return courses_by_department

		# Legacy fallback: one .xlsx file per department.
		excluded_files = {"rooms", "list of offered courses"}
		courses_by_department: dict[str, list] = {}
		for file_path in sorted(self.parser.raw_data_dir.glob("*.xlsx")):
			if file_path.stem.strip().lower() in excluded_files:
				continue
			courses = self.parser.load_course_sessions(file_path.name)
			if not courses:
				continue
			courses_by_department[file_path.stem.strip().upper()] = courses

		if not courses_by_department:
			raise ValueError("No department course files found in data/raw.")

		return courses_by_department

	def _selected_department_courses(self):
		return list(self.department_courses.get(self.department_var.get(), []))

	def _build_semester_choices(self, courses):
		semesters = sorted({course.semester for course in courses if course.semester}, key=self._semester_sort_key)
		return ["All"] + semesters if semesters else ["All"]

	def _build_room_layout(self):
		available = set(self.available_room_names)
		layout: list[tuple[str, str]] = []
		used: set[str] = set()

		for block_name, block_rooms in ROOM_BLOCKS.items():
			present = [room_name for room_name in block_rooms if room_name in available]
			if not present:
				continue
			layout.append(("divider", block_name))
			for room_name in present:
				layout.append(("room", room_name))
				used.add(room_name)

		remaining = sorted(room_name for room_name in self.available_room_names if room_name not in used)
		if remaining:
			layout.append(("divider", "Other"))
			for room_name in remaining:
				layout.append(("room", room_name))

		return layout

	def _room_rows(self) -> list[str]:
		return [value for row_type, value in self.room_layout if row_type == "room"]

	def _build_section_choices(self, courses):
		sections = sorted(
			set(
				c.section
				for c in courses
				if c.section and str(c.section).strip() != ""
			)
		)
		return ["All"] + sections

	def _semester_sort_key(self, value: str):
		return (0, int(value)) if str(value).isdigit() else (1, str(value))

	def _build_styles(self):
		style = ttk.Style(self.root)
		style.theme_use("clam")
		style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
		style.configure("Status.TLabel", font=("Segoe UI", 10))

	def _build_ui(self):
		container = ttk.Frame(self.root, padding=12)
		container.pack(fill="both", expand=True)

		top = ttk.Frame(container)
		top.pack(fill="x", pady=(0, 12))

		title = ttk.Label(top, text="GIKI Timetable Scheduler", style="Title.TLabel")
		title.pack(side="left")

		self.export_button = ttk.Button(top, text="Export PDF", command=self.export_pdf, state="disabled")
		self.export_button.pack(side="right", padx=(8, 0))

		self.generate_button = ttk.Button(top, text="Generate Timetable", command=self.generate_timetable)
		self.generate_button.pack(side="right")

		filter_row = ttk.Frame(container)
		filter_row.pack(fill="x", pady=(0, 10))

		department_label = ttk.Label(filter_row, text="Department:", style="Status.TLabel")
		department_label.pack(side="left", padx=(0, 8))

		self.department_box = ttk.Combobox(
			filter_row,
			textvariable=self.department_var,
			values=self.department_choices,
			state="readonly",
			width=18,
		)
		self.department_box.pack(side="left")
		self.department_box.bind("<<ComboboxSelected>>", self._on_filter_change)

		semester_label = ttk.Label(filter_row, text="Semester:", style="Status.TLabel")
		semester_label.pack(side="left", padx=(16, 8))

		self.semester_box = ttk.Combobox(
			filter_row,
			textvariable=self.semester_var,
			values=self.semesters,
			state="readonly",
			width=18,
		)
		self.semester_box.pack(side="left")
		self.semester_box.bind("<<ComboboxSelected>>", self._on_filter_change)

		section_label = ttk.Label(filter_row, text="Section:", style="Status.TLabel")
		section_label.pack(side="left", padx=(16, 8))

		self.section_box = ttk.Combobox(
			filter_row,
			textvariable=self.section_var,
			values=self.section_choices,
			state="readonly",
			width=18,
		)
		self.section_box.pack(side="left")
		self.section_box.bind("<<ComboboxSelected>>", self._on_filter_change)

		type_label = ttk.Label(filter_row, text="Type:", style="Status.TLabel")
		type_label.pack(side="left", padx=(16, 8))

		self.course_type_box = ttk.Combobox(
			filter_row,
			textvariable=self.course_type_var,
			values=["All", "Lecture", "Lab"],
			state="readonly",
			width=12,
		)
		self.course_type_box.pack(side="left")
		self.course_type_box.bind("<<ComboboxSelected>>", self._on_filter_change)

		day_label = ttk.Label(filter_row, text="Day:", style="Status.TLabel")
		day_label.pack(side="left", padx=(16, 8))

		self.day_box = ttk.Combobox(
			filter_row,
			textvariable=self.day_var,
			values=DAY_VALUES,
			state="readonly",
			width=14,
		)
		self.day_box.pack(side="left")
		self.day_box.bind("<<ComboboxSelected>>", self._on_day_change)

		self.status_var = tk.StringVar(value="Load data and click Generate Timetable.")
		status = ttk.Label(container, textvariable=self.status_var, style="Status.TLabel")
		status.pack(fill="x", pady=(0, 10))

		table_area = ttk.Frame(container)
		table_area.pack(fill="both", expand=True)

		self.canvas = tk.Canvas(table_area, highlightthickness=0)
		h_scroll = ttk.Scrollbar(table_area, orient="horizontal", command=self.canvas.xview)
		v_scroll = ttk.Scrollbar(table_area, orient="vertical", command=self.canvas.yview)
		self.canvas.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

		self.canvas.grid(row=0, column=0, sticky="nsew")
		v_scroll.grid(row=0, column=1, sticky="ns")
		h_scroll.grid(row=1, column=0, sticky="ew")
		table_area.grid_rowconfigure(0, weight=1)
		table_area.grid_columnconfigure(0, weight=1)

		self.table_frame = ttk.Frame(self.canvas)
		self.table_window = self.canvas.create_window((0, 0), window=self.table_frame, anchor="nw")
		self.table_frame.bind("<Configure>", self._update_scroll_region)
		self.canvas.bind("<Configure>", self._resize_table_window)

		self._render_placeholder()
		self.status_var.set(
			f"Select a department/semester and click Generate Timetable. Loaded {sum(len(courses) for courses in self.department_courses.values())} total course sessions."
		)

	def _on_filter_change(self, event=None):
		department_courses = self._selected_department_courses()
		updated_semesters = self._build_semester_choices(department_courses)
		self.semesters = updated_semesters
		self.semester_box.configure(values=updated_semesters)
		if self.semester_var.get() not in updated_semesters:
			self.semester_var.set(updated_semesters[1] if len(updated_semesters) > 1 else "All")

		semester_filtered_courses = [
			course
			for course in department_courses
			if self.semester_var.get() == "All" or course.semester == self.semester_var.get()
		]
		selected_type = self.course_type_var.get()
		if selected_type == "Lab":
			semester_filtered_courses = [course for course in semester_filtered_courses if course.course_type == "lab"]
		elif selected_type == "Lecture":
			semester_filtered_courses = [course for course in semester_filtered_courses if course.course_type != "lab"]
		self.section_choices = self._build_section_choices(semester_filtered_courses)
		self.section_box.configure(values=self.section_choices)
		if self.section_var.get() not in self.section_choices:
			self.section_var.set("All")
		if event and event.widget == self.course_type_box:
			self.last_assignment = None
			self.export_button.config(state="disabled")
		self.last_assignment = None
		self.export_button.config(state="disabled")
		self._render_placeholder()
		selected_department = self.department_var.get()
		selected_semester = self.semester_var.get()
		selected_section = self.section_var.get()
		selected_type = self.course_type_var.get()
		filtered_count = len(self._filtered_courses())
		self.status_var.set(
			f"Ready. Department {selected_department}, semester {selected_semester}, section {selected_section}, type {selected_type} selected ({filtered_count} course sessions)."
		)

	def _on_day_change(self, event=None):
		if self.last_assignment is None:
			self._render_placeholder()
			return

		grid = build_timetable_grid(self.last_assignment, self.day_var.get())
		self._render_grid(grid)

	def _filtered_courses(self):
		from dataclasses import replace as _dc_replace
		selected_department = self.department_var.get()
		selected_semester = self.semester_var.get()
		selected_section = self.section_var.get()
		selected_type = self.course_type_var.get()

		all_courses = list(self.department_courses.get(selected_department, []))

		# Semester filter — normalize both sides to str to handle int/str mismatches.
		if selected_semester != "All":
			all_courses = [
				c for c in all_courses
				if str(c.semester).strip() == str(selected_semester).strip()
			]

		if selected_section != "All":
			# Courses explicitly assigned to this section.
			section_courses = [c for c in all_courses if c.section and c.section.strip() == selected_section]
			# Shared curriculum: courses with no section apply to every section.
			# Assign the target section so the section-conflict constraint works correctly.
			shared_courses = [
				_dc_replace(c, section=selected_section)
				for c in all_courses
				if not c.section or not c.section.strip()
			]
			filtered = section_courses + shared_courses
		else:
			# "All" — keep explicit-section courses; shared ones will be included
			# per section when _solve_and_render() iterates over sections.
			filtered = [c for c in all_courses if c.section and c.section.strip()]

		if selected_type == "Lab":
			filtered = [c for c in filtered if c.course_type == "lab"]
		elif selected_type == "Lecture":
			filtered = [c for c in filtered if c.course_type != "lab"]

		# Debug output — visible in the console when the GUI is running.
		print(f"[_filtered_courses] dept={selected_department!r}, sem={selected_semester!r}, "
			  f"section={selected_section!r}, type={selected_type!r}")
		print(f"[_filtered_courses] Total after filtering: {len(filtered)}")
		print(f"[_filtered_courses] Sample sections: {[c.section for c in filtered[:5]]}")
		print(f"[_filtered_courses] Sample codes:    {[c.code for c in filtered[:5]]}")
		return filtered

	def _update_scroll_region(self, event=None):
		self.canvas.configure(scrollregion=self.canvas.bbox("all"))

	def _resize_table_window(self, event):
		self.canvas.itemconfigure(self.table_window, height=max(event.height, 1))

	def _clear_table(self):
		for widget in self.table_frame.winfo_children():
			widget.destroy()

	def _render_placeholder(self):
		empty_grid = {
			room_name: {label: "" for label in self.timeslot_labels}
			for room_name in self._room_rows()
		}
		self._render_grid(empty_grid)

	def generate_timetable(self):
		# Debug: verify raw data before any filtering.
		all_sem2 = [
			c for c in self.department_courses.get(self.department_var.get(), [])
			if str(c.semester).strip() == str(self.semester_var.get()).strip()
			or self.semester_var.get() == "All"
		]
		print(f"[generate_timetable] All sem {self.semester_var.get()!r} courses: {len(all_sem2)}")
		print(f"[generate_timetable] Unique sections: {sorted(set(c.section for c in all_sem2))}")
		print(f"[generate_timetable] Sample: {[(c.code, c.section, c.meeting_index) for c in all_sem2[:5]]}")

		self.generate_button.config(state="disabled")
		self.export_button.config(state="disabled")
		self.last_assignment = None
		self.solve_in_progress = True
		filtered_courses = self._filtered_courses()
		if not filtered_courses:
			self.generate_button.config(state="normal")
			self.solve_in_progress = False
			self.status_var.set("No courses found for the selected department/semester.")
			return

		self.status_var.set(
			f"Generating timetable for department {self.department_var.get()}, semester {self.semester_var.get()} ({len(filtered_courses)} course sessions)..."
		)
		self._update_solving_status(time.monotonic())
		threading.Thread(target=self._solve_and_render, daemon=True).start()

	def _solve_and_render(self):
		try:
			courses = self._filtered_courses()
			selected_section = self.section_var.get()
			sections = sorted(set(c.section for c in courses if c.section and c.section.strip() != ""))
			print(f"Sections to solve: {sections}")
			print(f"Total courses: {len(courses)}")
			for course in courses[:5]:
				print(
					f"code={course.code} section={course.section} "
					f"semester='{course.semester}' type={type(course.semester)}"
				)
			self.last_solve_note = ""

			if selected_section == "All" and len(sections) > 1:
				combined_solution = {}
				failed_sections: list[str] = []
				from dataclasses import replace as _dc_replace
				all_dept_courses = self.department_courses.get(self.department_var.get(), [])

				if self.semester_var.get() == "All":
					groups: dict[tuple[str, str], list] = {}
					for section in sections:
						section_courses = [c for c in courses if c.section == section]
						shared = [
							_dc_replace(c, section=section)
							for c in all_dept_courses
							if not c.section or not c.section.strip()
						]
						combined = section_courses + shared
						combined_sorted = sorted(
							combined,
							key=lambda c: (c.code or "", c.section or "", c.row_id, c.meeting_index),
						)
						MAX_BUCKET_SIZE = 15 if len(all_dept_courses) > 100 else 20
						bucket_num = 1
						current_count = 0
						for course in combined_sorted:
							semester_value = str(course.semester).strip()
							if not semester_value:
								if current_count >= MAX_BUCKET_SIZE:
									bucket_num += 1
									current_count = 0
								semester_value = f"Auto{bucket_num}"
								current_count += 1
							key = (section, semester_value)
							groups.setdefault(key, []).append(course)
					group_items = sorted(groups.items())
				else:
					groups = {
						(section, str(self.semester_var.get())): [c for c in courses if c.section == section]
						for section in sections
					}
					group_items = sorted(groups.items())

				for (section, semester), group_courses in group_items:
					print(f"Group: section={section} semester={semester} courses={len(group_courses)}")

				for (section, semester), group_courses in group_items:
					if section == "Unknown":
						continue
					section_label = section if section else "Unknown"
					sem_label = str(semester).strip() if semester and str(semester).strip() else "All"
					if self.semester_var.get() == "All":
						section_courses = list(group_courses)
					else:
						# Shared curriculum (no section) — assign section so solver constraint works.
						shared = [
							_dc_replace(c, section=section)
							for c in all_dept_courses
							if (not c.section or not c.section.strip())
							and str(c.semester).strip() == str(semester).strip()
						]
						section_courses = list(group_courses) + shared

					print(f"\n=== Solving section {section} semester {semester} ===")
					print(f"Courses: {len(section_courses)}")
					for course in section_courses:
						from src.solver.constraints import build_domain
						domain = build_domain(course, self.rooms, self.timeslots)
						print(
							f"  {course.code} {course.section} "
							f"type={course.course_type} "
							f"domain={len(domain)} options"
						)
						if len(domain) == 0:
							print("  ^^^ EMPTY DOMAIN - this will cause solver to fail!")

					if len(section_courses) > len(self.timeslots):
						print(
							f"[solve] Section {section_label!r} sem {semester!r} has {len(section_courses)} "
							f"sessions but only {len(self.timeslots)} timeslots; skipping as infeasible."
						)
						failed_sections.append(f"Sec {section_label} Sem {sem_label}")
						continue
					try:
						section_solution = solve_csp(
							section_courses,
							self.rooms,
							self.timeslots,
							use_lcv=False,
							max_seconds=60,
						)
					except (SolveTimeoutError, ValueError):
						failed_sections.append(f"Sec {section_label} Sem {sem_label}")
						continue

					if section_solution is None:
						# Debug: print domain sizes to identify courses with zero options.
						from src.solver.constraints import build_domain
						print(f"[solver] Section {section_label!r} sem {semester!r} returned no solution "
							  f"({len(section_courses)} sessions, {len(self.timeslots)} timeslots)")
						zero_domain = []
						for sc in section_courses:
							d = build_domain(sc, self.rooms, self.timeslots)
							if len(d) == 0:
								zero_domain.append(sc)
								print(f"  ZERO DOMAIN: {sc.code!r} {sc.section!r} type={sc.course_type!r}")
						if not zero_domain:
							print(f"  (all courses have non-empty domains — likely infeasible "
								  f"due to too many sessions [{len(section_courses)}] vs "
								  f"timeslots [{len(self.timeslots)}] or constraint conflicts)")
						failed_sections.append(f"Sec {section_label} Sem {sem_label}")
						continue

					combined_solution.update(section_solution)

				if failed_sections:
					self.last_solve_note = (
						f"Could not schedule (too many courses): {', '.join(failed_sections)}"
					)

				# Cross-section teacher conflict check
				conflicts = _find_teacher_conflicts(combined_solution)
				if conflicts:
					self.last_solve_note += (
						f" WARNING: {len(conflicts)} cross-section teacher conflict(s) detected."
					)

				solution = combined_solution if combined_solution else None
			else:
				solution = solve_csp(courses, self.rooms, self.timeslots, use_lcv=False, max_seconds=60)
		except SolveTimeoutError:
			self.root.after(0, self._handle_timeout)
			return
		except ValueError as exc:
			self.root.after(0, lambda: self._handle_feasibility_error(exc))
			return
		except Exception as exc:
			self.root.after(0, lambda: self._handle_error(exc))
			return

		self.root.after(0, lambda: self._display_solution(solution))

	def _handle_error(self, exc: Exception):
		self.generate_button.config(state="normal")
		self.export_button.config(state="disabled")
		self.solve_in_progress = False
		self.status_var.set("Failed to generate timetable.")
		messagebox.showerror("Timetable Error", str(exc))

	def _handle_timeout(self):
		self.generate_button.config(state="normal")
		self.export_button.config(state="disabled")
		self.solve_in_progress = False
		self.status_var.set(
			"MGS has too many courses to auto-schedule. "
			"Try selecting a specific Section (e.g. A, B) "
			"and Semester instead of All."
		)

	def _handle_feasibility_error(self, exc: ValueError):
		self.generate_button.config(state="normal")
		self.export_button.config(state="disabled")
		self.solve_in_progress = False
		self.status_var.set(str(exc))

	def _display_solution(self, solution):
		self.generate_button.config(state="normal")
		self.solve_in_progress = False

		if solution is None:
			self.last_assignment = None
			self.export_button.config(state="disabled")
			self.status_var.set(
				f"No valid timetable found for department {self.department_var.get()}, semester {self.semester_var.get()}."
			)
			self._render_placeholder()
			return

		self.last_assignment = solution
		self.export_button.config(state="normal")

		self.status_var.set(
			f"Timetable generated for department {self.department_var.get()}, semester {self.semester_var.get()} with {len(solution)} course sessions."
		)
		if self.last_solve_note:
			self.status_var.set(f"{self.status_var.get()} {self.last_solve_note}")
		grid = build_timetable_grid(solution, self.day_var.get())
		self._render_grid(grid)

	def _update_solving_status(self, start_time: float):
		if not self.solve_in_progress:
			return
		elapsed = int(time.monotonic() - start_time)
		self.status_var.set(f"Generating timetable... ({elapsed}s elapsed)")
		self.root.after(1000, self._update_solving_status, start_time)

	def export_pdf(self):
		if not self.last_assignment:
			messagebox.showwarning("Export PDF", "Generate a timetable first.")
			return

		timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
		output_path = self.project_root / "data" / "output" / f"timetable_{timestamp}.pdf"
		try:
			if self.day_var.get() == FULL_WEEK_LABEL:
				grids_by_day = {day: build_grid_from_solver(self.last_assignment, day) for day in DAY_ORDER}
				saved_path = export_full_week_pdf(
					grids_by_day,
					output_path,
					self.department_var.get(),
					self.semester_var.get(),
				)
			else:
				grid = build_grid_from_solver(self.last_assignment, self.day_var.get())
				saved_path = export_timetable_pdf(
					grid,
					output_path,
					self.department_var.get(),
					self.semester_var.get(),
					self.day_var.get(),
				)
		except Exception as exc:
			messagebox.showerror("Export PDF", f"Failed to export timetable PDF.\n\n{exc}")
			return

		print(f"Exported timetable PDF: {saved_path}")
		messagebox.showinfo("Export PDF", f"Timetable exported successfully to:\n{saved_path}")
		try:
			subprocess.Popen(["cmd", "/c", "start", "", str(saved_path)])
		except Exception:
			# Export succeeded even if the viewer fails to open.
			pass

	def _render_grid(self, grid):
		self._clear_table()
		total_columns = len(self.timeslot_labels) + 2
		current_row = 0

		render_layout = list(self.room_layout)
		known_rooms = {value for row_type, value in render_layout if row_type == "room"}
		other_rooms = sorted(room_name for room_name in grid.keys() if room_name not in known_rooms)

		# Debug: show what arrived in the grid vs what the layout expects.
		grid_rooms_with_data = [r for r, slots in grid.items() if any(slots.values())]
		print(f"[_render_grid] grid has {len(grid)} rooms, {len(grid_rooms_with_data)} with data: {grid_rooms_with_data}")
		print(f"[_render_grid] known_rooms sample: {sorted(known_rooms)[:5]}")
		for gr in grid_rooms_with_data:
			if gr in known_rooms:
				print(f"[_render_grid]   OK room in layout: {gr!r}")
			else:
				print(f"[_render_grid]   MISSING from layout: {gr!r}")

		if other_rooms:
			render_layout.append(("divider", "Other"))
			for room_name in other_rooms:
				render_layout.append(("room", room_name))

		title_label = tk.Label(
			self.table_frame,
			text="GIK Institute Time Table Spring 2026",
			bg="#0B1F3A",
			fg="white",
			font=("Segoe UI", 13, "bold"),
			padx=8,
			pady=8,
		)
		title_label.grid(row=current_row, column=0, columnspan=total_columns, sticky="nsew", padx=1, pady=1)
		current_row += 1

		day_header = tk.Label(
			self.table_frame,
			text=self.day_var.get(),
			bg="#2C5C8F",
			fg="white",
			font=("Segoe UI", 11, "bold"),
			padx=6,
			pady=6,
		)
		day_header.grid(row=current_row, column=0, columnspan=total_columns, sticky="nsew", padx=1, pady=1)
		current_row += 1

		headers = ["Room"] + self.timeslot_labels + ["Room"]
		for col_index, header in enumerate(headers):
			header_label = tk.Label(
				self.table_frame,
				text=header,
				bg="#3D78AD",
				fg="white",
				font=("Segoe UI", 9, "bold"),
				padx=4,
				pady=6,
			)
			header_label.grid(row=current_row, column=col_index, sticky="nsew", padx=1, pady=1)
		current_row += 1

		is_full_week = self.day_var.get() == FULL_WEEK_LABEL
		cell_font_size = 7 if is_full_week else 8
		cell_wraplength = 150 if is_full_week else 0

		alternating_index = 0
		for row_type, value in render_layout:
			if row_type == "divider":
				divider_label = tk.Label(
					self.table_frame,
					text=value,
					bg="#5D8CB7",
					fg="white",
					font=("Segoe UI", 9, "bold"),
					anchor="w",
					padx=8,
					pady=4,
				)
				divider_label.grid(row=current_row, column=0, columnspan=total_columns, sticky="nsew", padx=1, pady=1)
				current_row += 1
				continue

			room_name = value
			row_bg = "#EBF3FB" if alternating_index % 2 == 0 else "#FFFFFF"
			room_bg = "#D9E6F3"

			left_room = tk.Label(
				self.table_frame,
				text=room_name,
				bg=room_bg,
				fg="#1C2D3F",
				font=("Segoe UI", 9, "bold"),
				anchor="w",
				padx=6,
				pady=4,
			)
			left_room.grid(row=current_row, column=0, sticky="nsew", padx=1, pady=1)

			room_row = grid.get(room_name, {})
			for offset, label in enumerate(self.timeslot_labels, start=1):
				cell_text = room_row.get(label, "")
				cell = tk.Label(
					self.table_frame,
					text=cell_text,
					bg=row_bg,
					fg="#1D2833",
					font=("Segoe UI", cell_font_size),
					anchor="center",
					padx=3,
					pady=4,
					wraplength=cell_wraplength,
				)
				cell.grid(row=current_row, column=offset, sticky="nsew", padx=1, pady=1)

			right_room = tk.Label(
				self.table_frame,
				text=room_name,
				bg=room_bg,
				fg="#1C2D3F",
				font=("Segoe UI", 9, "bold"),
				anchor="e",
				padx=6,
				pady=4,
			)
			right_room.grid(row=current_row, column=len(self.timeslot_labels) + 1, sticky="nsew", padx=1, pady=1)

			current_row += 1
			alternating_index += 1

		middle_minsize = 110 if is_full_week else 100
		room_minsize = 90 if is_full_week else 125
		for col_index in range(total_columns):
			if col_index in (0, total_columns - 1):
				self.table_frame.grid_columnconfigure(col_index, weight=0, minsize=room_minsize)
			else:
				self.table_frame.grid_columnconfigure(col_index, weight=1, minsize=middle_minsize)

		self._update_scroll_region()

	def run(self):
		self.root.mainloop()


def main():
	app = TimetableApp()
	app.run()


if __name__ == "__main__":
	main()
