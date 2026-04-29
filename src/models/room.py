from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Room:
	room_id: str
	room_name: str
	building: str
	room_type: str
	capacity: int
