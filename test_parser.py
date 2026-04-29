from pathlib import Path

from src.utils.excel_parser import ExcelParser


def parse_rooms(parser: ExcelParser, file_path: Path):
    return parser.load_rooms(file_path.name)


def parse_department_courses(parser: ExcelParser, file_path: Path):
    return parser.load_course_sessions(file_path.name)


def main() -> None:
    root = Path(__file__).resolve().parent
    raw_dir = root / "data" / "raw"

    parser = ExcelParser(raw_dir)

    rooms = parse_rooms(parser, raw_dir / "rooms.xlsx")
    sessions = parse_department_courses(parser, raw_dir / "fcse.xlsx")

    print(f"Total rooms loaded: {len(rooms)}")
    print(f"Total CourseSession variables after credit-hour expansion: {len(sessions)}")
    print("First 10 sessions (session_id, instructor, total_sessions):")

    for session in sessions[:10]:
        session_id = getattr(session, "session_id", "N/A")
        instructor = getattr(session, "instructor", "")
        total_sessions = getattr(session, "total_sessions", "N/A")
        print(f"- {session_id}, {instructor}, {total_sessions}")


if __name__ == "__main__":
    main()
