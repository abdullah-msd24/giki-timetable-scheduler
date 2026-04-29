from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Iterable


@dataclass(frozen=True)
class TimeSlot:
	day: str
	start_time: time
	end_time: time

	@property
	def label(self) -> str:
		return f"{self.day} {self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')}"


def generate_timeslots(
	days: Iterable[str],
	start_time: str = "08:30",
	end_time: str = "17:30",
	slot_minutes: int = 60,
	start_times: Iterable[str] | None = None,
) -> list[TimeSlot]:
	slot_delta = timedelta(minutes=slot_minutes)
	slots: list[TimeSlot] = []

	if start_times is not None:
		parsed_starts = [datetime.strptime(value, "%H:%M") for value in start_times]
		for day in days:
			for slot_start in parsed_starts:
				slot_end = slot_start + slot_delta
				slots.append(TimeSlot(day=day, start_time=slot_start.time(), end_time=slot_end.time()))
		return slots

	start = datetime.strptime(start_time, "%H:%M")
	finish = datetime.strptime(end_time, "%H:%M")

	for day in days:
		current = start
		while current + slot_delta <= finish:
			slot_end = current + slot_delta
			slots.append(TimeSlot(day=day, start_time=current.time(), end_time=slot_end.time()))
			current = slot_end

	return slots
