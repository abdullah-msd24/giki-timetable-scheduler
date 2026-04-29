from __future__ import annotations

import re as _re
from dataclasses import dataclass
from typing import Iterable

from src.models.course import CourseSession
from src.models.room import Room
from src.models.timeslot import TimeSlot


@dataclass(frozen=True)
class AssignmentOption:
	room: Room
	timeslot: TimeSlot

	@property
	def key(self) -> tuple[str, str, str]:
		return (self.room.room_id, self.timeslot.day, self.timeslot.label)


def define_variables(courses: Iterable[CourseSession]) -> list[CourseSession]:
	"""Return the CSP variables.

	Each variable represents one course session that must be assigned a room
	and a timeslot. The parser already expands each course into N individual
	1-credit sessions (meeting_index 1..N), so we simply return them as-is.
	"""
	return list(courses)


# Minimum seat threshold per room type. Rooms below this are excluded.
_MIN_LECTURE_CAPACITY = 30
_MIN_LAB_CAPACITY = 10

# ---------------------------------------------------------------------------
# Lab building mapping
# ---------------------------------------------------------------------------
# Maps course-code alphabetic prefixes to the building(s) whose labs they
# should use. Building values are taken directly from rooms.xlsx:
#   ACB, FES, BB, FME, FMCE, FBS, TBA
#
# CS/FCSE courses  → ACB labs (AI Lab, CYS Lab, DA Lab) + FBS (general-use)
# ME/MT courses    → FME lab
# EE courses       → FEE area (ACB or FEE)
# ES/PH courses    → FES physics/science labs
# CH/MM courses    → FCME chemistry/materials labs
# BS courses       → FBS biology lab
# No mapping       → any lab room is acceptable
_PREFIX_TO_LAB_BUILDINGS: dict[str, frozenset[str]] = {
	"CS": frozenset({"ACB", "FBS"}),
	"IF": frozenset({"ACB", "FBS"}),
	"SE": frozenset({"ACB", "FBS"}),
	"AI": frozenset({"ACB", "FBS"}),
	"CY": frozenset({"ACB", "FBS"}),
	"DS": frozenset({"ACB", "FBS"}),
	"SW": frozenset({"ACB", "FBS"}),
	"ME": frozenset({"FME", "FBS"}),
	"MT": frozenset({"FME", "FBS"}),
	"EE": frozenset({"ACB", "FBS"}),
	"ES": frozenset({"FES", "FBS"}),
	"PH": frozenset({"FES", "FBS"}),
	"CH": frozenset({"FMCE", "FBS"}),
	"MM": frozenset({"FMCE", "FBS"}),
	"BS": frozenset({"FBS"}),
	# Humanities labs go to Academic Block or BB PC Lab (never FME/FES/FMCE).
	"HM": frozenset({"ACB", "BB", "FBS"}),
}


# ---------------------------------------------------------------------------
# Lecture building restrictions for FCSE-area courses
# ---------------------------------------------------------------------------
# CS/IF/SE/AI/CY/DS/SW lectures should only use FCSE and Academic Block halls.
# Building values from rooms.xlsx: FCSE, FEE, ACB, FES, BB, FME, FMCE, FBS.
_FCSE_LECTURE_PREFIXES: frozenset[str] = frozenset({
	"CS", "IF", "SE", "AI", "CY", "DS", "SW",
})

_BLOCKED_LECTURE_BUILDINGS_FOR_CS: frozenset[str] = frozenset({
	"FME", "FMCE", "BB", "FBS", "FES",
})

_BB_PREFIXES: frozenset[str] = frozenset({"HM", "MS", "AF", "EM", "SC"})
_BLOCKED_FOR_BB: frozenset[str] = frozenset({"FME", "FMCE", "FES", "FCSE", "FEE"})

def _course_code_prefix(course: CourseSession) -> str:
	"""Extract the alphabetic prefix from a course code, e.g. 'CS112 L' → 'CS'."""
	m = _re.match(r'^([A-Za-z]+)', (course.code or "").strip())
	return m.group(1).upper() if m else ""


def _is_room_suitable(course: CourseSession, room: Room) -> bool:
	"""Return True if the room is appropriate for this course.

	Rules:
	  - TBA room is never assigned (it is a placeholder with cap=999).
	  - Lab courses only go to lab rooms; lecture courses only go to lecture rooms.
	  - For lab courses, further restrict by building: course-code prefixes are
	    mapped to faculty-appropriate buildings. If no prefix mapping exists,
	    any lab room is acceptable.
	"""
	# Never assign the TBA placeholder.
	if room.room_name == "TBA":
		return False

	course_type = (course.course_type or "lecture").strip().lower()
	is_lab_room = "lab" in (room.room_type or "").strip().lower()

	if course_type == "lab":
		if not is_lab_room:
			return False
		# Restrict by course-code prefix → allowed lab buildings.
		prefix = _course_code_prefix(course)
		allowed_buildings = _PREFIX_TO_LAB_BUILDINGS.get(prefix)
		if allowed_buildings:
			return (room.building or "").strip() in allowed_buildings
		return True  # No mapping → any lab room is acceptable.

	# Lecture / non-lab course must not be placed in a lab room.
	if is_lab_room:
		return False

	# For humanities/management prefixes, keep lectures in BB/AcB blocks.
	prefix = _course_code_prefix(course)
	if prefix in _BB_PREFIXES:
		building = (room.building or "").strip()
		return building not in _BLOCKED_FOR_BB and not is_lab_room

	# For CS/FCSE prefixes, block non-FCSE/AcB lecture buildings so
	# courses like CS112 never land in ME Main, BB LH, or FES halls.
	if prefix in _FCSE_LECTURE_PREFIXES:
		return (room.building or "").strip() not in _BLOCKED_LECTURE_BUILDINGS_FOR_CS

	return True


def build_domain(
	course: CourseSession,
	rooms: Iterable[Room],
	timeslots: Iterable[TimeSlot],
) -> list[AssignmentOption]:
	"""Build the domain for one course as Room × TimeSlot combinations.

	Filters rooms by type (lab vs lecture) and a minimum capacity threshold
	so the solver never assigns a course to an unsuitable or impossibly small
	space. Capacity is compared against the minimum per room type rather than
	the credit_hours field (which is always 1 after session expansion).
	"""
	course_type = (course.course_type or "lecture").strip().lower()
	min_cap = _MIN_LAB_CAPACITY if course_type == "lab" else _MIN_LECTURE_CAPACITY
	room_list = list(rooms)
	timeslot_list = list(timeslots)

	suitable_rooms = [
		r for r in room_list
		if _is_room_suitable(course, r) and r.capacity >= min_cap
	]

	# Debug print for CS101 courses as requested.
	if "CS101" in (course.code or ""):
		print(f"[build_domain] CS101 suitable rooms ({len(suitable_rooms)}): "
			  f"{[r.room_name for r in suitable_rooms]}")

	# Safety fallback: if the strict per-prefix filter yields nothing,
	# open to all appropriately-typed rooms (excluding TBA) so the solver
	# never receives an empty domain.
	if not suitable_rooms:
		is_lab_course = course_type == "lab"
		suitable_rooms = [
			r for r in room_list
			if ("lab" in (r.room_type or "").lower()) == is_lab_course
			and r.room_name != "TBA"
			and r.capacity >= min_cap
		]
		if suitable_rooms:
			print(f"[build_domain] WARNING: {course.code} {course.section} used fallback "
				  f"room list ({len(suitable_rooms)} rooms)")

	return [
		AssignmentOption(room=room, timeslot=ts)
		for room in suitable_rooms
		for ts in timeslot_list
	]


def teacher_conflict(
	course: CourseSession,
	assignment: AssignmentOption,
	existing_assignments: dict[CourseSession, AssignmentOption],
) -> bool:
	"""Return True when assigning the course would create a teacher clash."""
	for other_course, other_assignment in existing_assignments.items():
		if other_course.instructor == course.instructor and _same_timeslot(assignment, other_assignment):
			return True
	return False


def room_conflict(
	assignment: AssignmentOption,
	existing_assignments: dict[CourseSession, AssignmentOption],
) -> bool:
	"""Return True when the room is already used at the same timeslot."""
	for other_assignment in existing_assignments.values():
		if assignment.room.room_id == other_assignment.room.room_id and _same_timeslot(assignment, other_assignment):
			return True
	return False


def section_conflict(
	course: CourseSession,
	assignment: AssignmentOption,
	existing_assignments: dict[CourseSession, AssignmentOption],
) -> bool:
	"""Return True when the section already has another class in the slot."""
	for other_course, other_assignment in existing_assignments.items():
		if other_course.section == course.section and _same_timeslot(assignment, other_assignment):
			return True
	return False


def is_assignment_consistent(
	course: CourseSession,
	assignment: AssignmentOption,
	existing_assignments: dict[CourseSession, AssignmentOption],
) -> bool:
	"""Check all hard constraints for a single tentative assignment."""
	if teacher_conflict(course, assignment, existing_assignments):
		return False
	if room_conflict(assignment, existing_assignments):
		return False
	if section_conflict(course, assignment, existing_assignments):
		return False
	return True


def check_global_feasibility(
	courses: Iterable[CourseSession],
	timeslots: Iterable[TimeSlot],
) -> tuple[bool, str | None]:
	"""Warn about heavy section/instructor load and allow solver to continue."""
	timeslot_list = list(timeslots)
	available_slots = len(timeslot_list)
	if available_slots == 0:
		print("WARNING: No timeslots available; solver will still attempt search.")
		return True, None

	section_counts: dict[tuple[str, str], int] = {}
	instructor_counts: dict[str, int] = {}
	for course in courses:
		section = (course.section or "").strip()
		section_label = section if section else "No section assigned"
		semester = course.semester or "Unknown"
		section_key = (section_label, semester)
		section_counts[section_key] = section_counts.get(section_key, 0) + 1

		instructor = course.instructor or "Unknown"
		instructor_counts[instructor] = instructor_counts.get(instructor, 0) + 1

	for (section, semester), count in section_counts.items():
		if count > available_slots:
			print(
				f"WARNING: Section {section} sem {semester} has {count} sessions vs "
				f"{available_slots} timeslots"
			)

	for instructor, count in instructor_counts.items():
		if count > available_slots:
			print(
				f"Warning: Instructor {instructor} has {count} sessions but only "
				f"{available_slots} timeslots available."
			)

	return True, None


def _same_timeslot(first: AssignmentOption, second: AssignmentOption) -> bool:
	return (
		first.timeslot.day == second.timeslot.day
		and first.timeslot.start_time == second.timeslot.start_time
		and first.timeslot.end_time == second.timeslot.end_time
	)
