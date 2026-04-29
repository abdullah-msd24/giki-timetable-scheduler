from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class CourseSession:
	code: str
	title: str
	credit_hours: int
	instructor: str
	section: str
	program: str = ""
	semester: str = ""
	course_type: str = "lecture"
	row_id: int = 0
	meeting_index: int = 1

	@property
	def required_slots(self) -> int:
		return max(1, int(self.credit_hours))

	def with_meeting(self, meeting_index: int) -> "CourseSession":
		return replace(self, meeting_index=meeting_index)
