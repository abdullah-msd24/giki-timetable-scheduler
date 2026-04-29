from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import pandas as pd

from src.models.course import CourseSession
from src.models.room import Room
from src.models.timeslot import TimeSlot, generate_timeslots


class ExcelParser:
	def __init__(self, raw_data_dir: str | Path):
		self.raw_data_dir = Path(raw_data_dir)

	def load_rooms(self, filename: str = "rooms.xlsx") -> list[Room]:
		frame = self._read_tabular(self.raw_data_dir / filename)
		normalized = self._normalize_columns(frame)
		rooms: list[Room] = []

		for _, row in normalized.iterrows():
			room_id = self._get_value(row, "room_id")
			room_name = self._get_value(row, "room_name")
			building = self._get_value(row, "building")
			room_type = self._get_value(row, "type", default="lecture_hall")
			capacity = self._to_int(self._get_value(row, "capacity", default=0))

			if room_id and room_name:
				rooms.append(
					Room(
						room_id=room_id,
						room_name=room_name,
						building=building,
						room_type=room_type,
						capacity=capacity,
					)
				)

		return rooms

	def load_course_sessions(self, filename: str) -> list[CourseSession]:
		frame = self._read_tabular(self.raw_data_dir / filename)
		normalized = self._normalize_columns(frame)
		sessions: list[CourseSession] = []

		for row_index, row in normalized.iterrows():
			code = self._get_any(row, ["code", "course_code"])
			title = self._get_any(row, ["title", "course_title", "course title"])
			credit_hours = self._to_int(
				self._get_any(
					row,
					["credit_hours", "ch", "ch_", "credit_hour", "c_h", "credit hour", "credit hours"],
					default=0,
				)
			)
			instructor = self._get_any(row, ["instructor", "course_instructor", "teacher"], default="")
			section = self._get_any(row, ["section", "sec", "grp", "group", "div", "division", "section_"], default="")
			program = self._get_any(row, ["program", "for"], default="")
			semester = self._get_any(row, ["sem", "sem_", "sem.", "semester"], default="")
			raw_course_type = self._get_any(row, ["type", "course_type"], default="")
			course_type = self._infer_course_type(code=code, title=title, raw_type=raw_course_type)

			# Courses with no section are shared curriculum (apply to all sections).
			# Keep them loaded; _filtered_courses() will assign the target section
			# dynamically before passing them to the solver.

			if code and title:
				total_sessions = max(1, credit_hours)
				for session_index in range(1, total_sessions + 1):
					session = CourseSession(
						code=code,
						title=title,
						# Each generated row is an independent session variable.
						credit_hours=1,
						instructor=instructor,
						section=section,
						program=program,
						semester=str(semester) if semester != "" else "",
						course_type=course_type,
						row_id=int(row_index),
						meeting_index=session_index,
					)
					session_id = f"{code}-{section}-{session_index}"
					# Attach parser-level metadata without changing the shared model contract.
					object.__setattr__(session, "session_id", session_id)
					object.__setattr__(session, "session_index", session_index)
					object.__setattr__(session, "total_sessions", total_sessions)
					sessions.append(session)

		unique_sections = set(s.section for s in sessions)
		print(f"Unique sections found: {unique_sections}")
		print(f"Loaded {len(sessions)} course sessions from {filename}.")
		return sessions

	def load_all_courses_by_program(
		self, filename: str = "courses.csv"
	) -> dict[str, list[CourseSession]]:
		"""Load courses.csv and group CourseSession objects by the 'program' column.

		Returns a dict mapping program code (e.g. 'BCS', 'BAI') to the list of
		expanded CourseSession objects for that program. This replaces the old
		one-xlsx-per-department layout.
		"""
		frame = self._read_tabular(self.raw_data_dir / filename)
		normalized = self._normalize_columns(frame)
		by_program: dict[str, list[CourseSession]] = {}

		for row_index, row in normalized.iterrows():
			code = self._get_any(row, ["code", "course_code"])
			title = self._get_any(row, ["title", "course_title"])
			credit_hours = self._to_int(
				self._get_any(row, ["credit_hours", "ch", "credit_hour"], default=1)
			)
			instructor = self._get_any(row, ["instructor", "teacher"], default="")
			section = self._get_any(row, ["section", "sec"], default="")
			program = self._get_any(row, ["program"], default="UNKNOWN")
			raw_course_type = self._get_any(row, ["type", "course_type"], default="")
			course_type = self._infer_course_type(code=code, title=title, raw_type=raw_course_type)
			# courses.csv has no semester column; use empty string so the
			# semester filter in the GUI defaults to 'All'.
			semester = ""

			if not (code and title):
				continue

			program_key = str(program).strip().upper() if program else "UNKNOWN"
			total_sessions = max(1, credit_hours)
			for session_index in range(1, total_sessions + 1):
				session = CourseSession(
					code=code,
					title=title,
					credit_hours=1,
					instructor=instructor,
					section=str(section).strip() if section else "",
					program=str(program).strip() if program else "",
					semester=semester,
					course_type=course_type,
					row_id=int(row_index),
					meeting_index=session_index,
				)
				session_id = f"{code}-{section}-{session_index}"
				object.__setattr__(session, "session_id", session_id)
				object.__setattr__(session, "session_index", session_index)
				object.__setattr__(session, "total_sessions", total_sessions)
				by_program.setdefault(program_key, []).append(session)

		for prog, sessions in by_program.items():
			print(f"  {prog}: {len(sessions)} sessions")
		print(f"load_all_courses_by_program: {len(by_program)} programs, "
			  f"{sum(len(v) for v in by_program.values())} total sessions from {filename}")
		return by_program

	def generate_timeslots(
		self,
		days: list[str] | None = None,
		start_time: str = "08:30",
		end_time: str = "17:30",
		slot_minutes: int = 60,
		start_times: list[str] | None = None,
	) -> list[TimeSlot]:
		if days is None:
			days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

		# Default academic pattern:
		# 08:00, 09:00, break, 10:30, 11:30, 12:30, lunch/prayer break, 14:30, 15:30, 16:30
		if start_times is None:
			start_times = ["08:00", "09:00", "10:30", "11:30", "12:30", "14:30", "15:30", "16:30"]
			slot_minutes = 50

		return generate_timeslots(
			days=days,
			start_time=start_time,
			end_time=end_time,
			slot_minutes=slot_minutes,
			start_times=start_times,
		)

	def _read_tabular(self, path: Path) -> pd.DataFrame:
		if not path.exists():
			raise FileNotFoundError(f"File not found: {path}")

		if path.suffix.lower() == ".csv":
			return pd.read_csv(path)

		if path.suffix.lower() in {".xlsx", ".xls"}:
			return pd.read_excel(path)

		raise ValueError(f"Unsupported file format: {path.suffix}")

	def _normalize_columns(self, frame: pd.DataFrame) -> pd.DataFrame:
		renamed = {}
		for column in frame.columns:
			normalized = self._normalize_key(str(column))
			renamed[column] = normalized
		return frame.rename(columns=renamed)

	def _normalize_key(self, value: str) -> str:
		cleaned = value.strip().lower()
		cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned)
		return cleaned.strip("_")

	def _get_value(self, row: pd.Series, key: str, default: Any = "") -> Any:
		if key in row and pd.notna(row[key]):
			value = row[key]
			if isinstance(value, str):
				return value.strip()
			return value
		return default

	def _get_any(self, row: pd.Series, keys: list[str], default: Any = "") -> Any:
		for key in keys:
			normalized_key = self._normalize_key(key)
			if normalized_key in row and pd.notna(row[normalized_key]):
				value = row[normalized_key]
				if isinstance(value, str):
					return value.strip()
				return value
		return default

	def _to_int(self, value: Any) -> int:
		try:
			return int(float(value))
		except (TypeError, ValueError):
			return 0

	def _infer_course_type(self, code: str, title: str, raw_type: str) -> str:
		if isinstance(raw_type, str):
			normalized = raw_type.strip().lower()
			if "lab" in normalized:
				return "lab"
			if normalized:
				return "lecture"

		text = f"{code} {title}".lower()
		if isinstance(code, str) and code.strip().upper().endswith("L"):
			return "lab"
		if " lab" in text or "laboratory" in text:
			return "lab"
		return "lecture"
