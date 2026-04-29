from __future__ import annotations

import random
from collections.abc import Iterable
from datetime import time as dt_time

from src.models.course import CourseSession
from src.solver.constraints import AssignmentOption, is_assignment_consistent


DAY_RANK = {
	"Monday": 0,
	"Tuesday": 1,
	"Wednesday": 2,
	"Thursday": 3,
	"Friday": 4,
}


def select_unassigned_variable(
	variables: Iterable[CourseSession],
	assignment: dict[CourseSession, AssignmentOption],
	domains: dict[CourseSession, list[AssignmentOption]],
) -> CourseSession | None:
	"""Select the next variable using MRV, then Degree as a tie-breaker."""
	unassigned = [course for course in variables if course not in assignment]
	if not unassigned:
		return None

	def key(course: CourseSession) -> tuple[int, int, str, str, int, int]:
		return (
			len(domains.get(course, [])),
			-_degree(course, unassigned),
			course.section,
			course.code,
			course.row_id,
			course.meeting_index,
		)

	return min(unassigned, key=key)


def order_domain_values(
	course: CourseSession,
	assignment: dict[CourseSession, AssignmentOption],
	domains: dict[CourseSession, list[AssignmentOption]],
	variables: Iterable[CourseSession],
	use_lcv: bool = False,
) -> list[AssignmentOption]:
	"""Order values for a variable.

	If `use_lcv` is False, the domain order is randomized. When enabled,
	values are sorted by Least Constraining Value so the option that leaves the
	most choices for the remaining variables is tried first.
	"""
	values = list(domains.get(course, []))
	if not use_lcv:
		course_semester = str(getattr(course, "semester", "")).strip()
		prefers_morning = course_semester in {"1", "2"}
		course_type = (getattr(course, "course_type", "lecture") or "lecture").strip().lower()
		ideal_capacity = 15 if course_type == "lab" else 30

		def soft_score(option: AssignmentOption) -> tuple[float, str, int, object, object]:
			timeslot_score = 0.0
			if prefers_morning:
				start_time = option.timeslot.start_time
				if start_time < dt_time(12, 0):
					timeslot_score = -2.0
			capacity_score = abs(option.room.capacity - ideal_capacity) / 100.0
			total_score = timeslot_score + capacity_score
			return (
				total_score,
				option.room.room_id,
				DAY_RANK.get(option.timeslot.day, 99),
				option.timeslot.start_time,
				option.timeslot.end_time,
			)

		random.shuffle(values)
		return sorted(values, key=soft_score)

	# Randomize first so equal-scored options do not always favor the same room.
	random.shuffle(values)

	unassigned = [item for item in variables if item not in assignment and item != course]

	def score(option: AssignmentOption) -> tuple[int, str, int, object, object]:
		trial_assignment = dict(assignment)
		trial_assignment[course] = option
		remaining_choices = 0
		for other_course in unassigned:
			for other_option in domains.get(other_course, []):
				if is_assignment_consistent(other_course, other_option, trial_assignment):
					remaining_choices += 1
		return (
			-remaining_choices,
			option.room.room_id,
			DAY_RANK.get(option.timeslot.day, 99),
			option.timeslot.start_time,
			option.timeslot.end_time,
		)

	return sorted(values, key=score)


def _degree(course: CourseSession, unassigned: list[CourseSession]) -> int:
	"""Count how many unassigned sessions are likely to be affected by this course."""
	count = 0
	for other_course in unassigned:
		if other_course == course:
			continue
		if other_course.instructor == course.instructor or other_course.section == course.section:
			count += 1
	return count
