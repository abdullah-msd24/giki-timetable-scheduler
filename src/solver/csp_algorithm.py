from __future__ import annotations

import time
from typing import Iterable

from src.models.course import CourseSession
from src.models.room import Room
from src.models.timeslot import TimeSlot
from src.solver.constraints import (
	AssignmentOption,
	build_domain,
	check_global_feasibility,
	define_variables,
	is_assignment_consistent,
)
from src.solver.heuristics import order_domain_values, select_unassigned_variable


class SolveTimeoutError(RuntimeError):
	"""Raised when CSP solving exceeds the configured time limit."""


def solve_csp(
	courses: Iterable[CourseSession],
	rooms: Iterable[Room],
	timeslots: Iterable[TimeSlot],
	use_lcv: bool = False,
	max_seconds: float | None = None,
) -> dict[CourseSession, AssignmentOption] | None:
	"""Return the first timetable that satisfies the hard constraints.

	This is a backtracking search guided by MRV and Degree selection, with
	optional Least Constraining Value ordering for domain values.

	``use_lcv`` defaults to False: random value ordering is orders of magnitude
	faster for typical GIKI section sizes (2-30 sessions). Enable LCV only when
	debugging difficult constraint conflicts.
	"""
	is_feasible, message = check_global_feasibility(courses, timeslots)
	if not is_feasible:
		print(message or "WARNING: Global feasibility check reported issues; continuing.")
	variables = define_variables(courses)
	domains = {course: build_domain(course, rooms, timeslots) for course in variables}
	deadline = time.monotonic() + max_seconds if max_seconds and max_seconds > 0 else None
	return _backtrack(variables, domains, {}, use_lcv, deadline)


def _backtrack(
	variables: list[CourseSession],
	domains: dict[CourseSession, list[AssignmentOption]],
	assignment: dict[CourseSession, AssignmentOption],
	use_lcv: bool,
	deadline: float | None,
) -> dict[CourseSession, AssignmentOption] | None:
	if deadline is not None and time.monotonic() >= deadline:
		raise SolveTimeoutError("Timetable generation timed out.")

	if len(assignment) == len(variables):
		return dict(assignment)

	course = select_unassigned_variable(variables, assignment, domains)
	if course is None:
		return dict(assignment)

	for option in order_domain_values(course, assignment, domains, variables, use_lcv=use_lcv):
		if deadline is not None and time.monotonic() >= deadline:
			raise SolveTimeoutError("Timetable generation timed out.")

		if not is_assignment_consistent(course, option, assignment):
			continue

		assignment[course] = option
		next_domains = _forward_check(variables, domains, assignment)
		if next_domains is None:
			del assignment[course]
			continue

		solution = _backtrack(variables, next_domains, assignment, use_lcv, deadline)
		if solution is not None:
			return solution
		del assignment[course]

	return None


def _forward_check(
	variables: list[CourseSession],
	domains: dict[CourseSession, list[AssignmentOption]],
	assignment: dict[CourseSession, AssignmentOption],
) -> dict[CourseSession, list[AssignmentOption]] | None:
	"""Prune domains after a tentative assignment.

	Only unassigned variables are retained. Any value that violates the current
	partial assignment is removed immediately, which catches conflicts before the
	next recursive level.
	"""
	pruned_domains: dict[CourseSession, list[AssignmentOption]] = {}
	for course in variables:
		if course in assignment:
			continue

		remaining_options = [
			option
			for option in domains.get(course, [])
			if is_assignment_consistent(course, option, assignment)
		]
		if not remaining_options:
			return None
		pruned_domains[course] = remaining_options

	return pruned_domains
