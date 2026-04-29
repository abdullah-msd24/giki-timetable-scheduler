from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, SimpleDocTemplate, Table, TableStyle


TIMESLOTS = [
    "08:00-08:50",
    "09:00-09:50",
    "10:30-11:20",
    "11:30-12:20",
    "12:30-13:20",
    "14:30-15:20",
    "15:30-16:20",
    "16:30-17:20",
]

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

NAVY = colors.HexColor("#1F3864")
BLUE = colors.HexColor("#2E75B6")
LIGHT_BLUE = colors.HexColor("#D6E4F0")
ALT_ROW = colors.HexColor("#EBF3FB")
WHITE = colors.white
FULL_WEEK_TITLE = "GIK Institute Time Table Spring 2026 — Full Week"


def _timeslot_to_label(timeslot: Any) -> str:
    return f"{timeslot.start_time.strftime('%H:%M')}-{timeslot.end_time.strftime('%H:%M')}"


def build_grid_from_solver(assignment: dict, day: str) -> dict:
    """Return a room-keyed grid for one day from solver assignments."""
    grid: dict[str, dict[str, str]] = {}
    if not assignment:
        return grid

    # Debug: trace day filtering and slot matching.
    print(f"[build_grid_from_solver] Total assignments: {len(assignment)}")
    print(f"[build_grid_from_solver] Filtering for day: {day!r}")
    day_assignments = [(c, a) for c, a in assignment.items()
                       if getattr(getattr(a, 'timeslot', None), 'day', '') == day]
    print(f"[build_grid_from_solver] Assignments for {day!r}: {len(day_assignments)}")
    for course, opt in day_assignments[:3]:
        slot = _timeslot_to_label(opt.timeslot)
        print(f"  {course.code} {course.section} -> "
              f"{opt.room.room_name!r} @ {opt.timeslot.start_time}  "
              f"slot={slot!r}  in_TIMESLOTS={slot in TIMESLOTS}")

    for course, option in assignment.items():
        room = getattr(option, "room", None)
        timeslot = getattr(option, "timeslot", None)
        if room is None or timeslot is None:
            continue
        if getattr(timeslot, "day", "") != day:
            continue

        room_name = str(getattr(room, "room_name", "")).strip()
        if not room_name:
            continue

        slot = _timeslot_to_label(timeslot)
        if slot not in TIMESLOTS:
            continue

        if room_name not in grid:
            grid[room_name] = {timeslot_label: "" for timeslot_label in TIMESLOTS}

        code = str(getattr(course, "code", "")).strip()
        section = str(getattr(course, "section", "")).strip()
        text = f"{code} {section}".strip()

        if grid[room_name][slot]:
            grid[room_name][slot] = f"{grid[room_name][slot]}\n{text}"
        else:
            grid[room_name][slot] = text

    return grid


def _build_timetable_table(
    grid: dict,
    department_name: str,
    semester: str,
    day: str,
    title_text: str,
) -> Table:
    page_width, _ = landscape(A4)
    margin = 1 * cm
    usable_width = page_width - (2 * margin)

    room_col_width = 2.5 * cm
    right_room_col_width = 2.5 * cm
    middle_width = usable_width - room_col_width - right_room_col_width
    slot_col_width = middle_width / len(TIMESLOTS)
    col_widths = [room_col_width] + [slot_col_width] * len(TIMESLOTS) + [right_room_col_width]
    total_cols = len(col_widths)

    table_data: list[list[str]] = []
    table_data.append([title_text] + [""] * (total_cols - 1))
    table_data.append([f"{department_name}  |  Semester: {semester}  |  {day}"] + [""] * (total_cols - 1))
    table_data.append(["Room"] + TIMESLOTS + ["Room"])

    room_row_indexes: list[int] = []
    block_row_indexes: list[int] = []

    for block_name, block_rooms in ROOM_BLOCKS.items():
        table_data.append([block_name] + [""] * (total_cols - 1))
        block_row_indexes.append(len(table_data) - 1)

        for room_name in block_rooms:
            if room_name not in grid:
                continue

            row = [room_name]
            for timeslot in TIMESLOTS:
                row.append(grid.get(room_name, {}).get(timeslot, ""))
            row.append(room_name)
            table_data.append(row)
            room_row_indexes.append(len(table_data) - 1)

    timetable_table = Table(table_data, colWidths=col_widths)

    style = [
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 14),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("SPAN", (0, 1), (-1, 1)),
        ("BACKGROUND", (0, 1), (-1, 1), BLUE),
        ("TEXTCOLOR", (0, 1), (-1, 1), colors.white),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, 1), 10),
        ("ALIGN", (0, 1), (-1, 1), "CENTER"),
        ("BACKGROUND", (0, 2), (-1, 2), BLUE),
        ("TEXTCOLOR", (0, 2), (-1, 2), colors.white),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE", (0, 2), (-1, 2), 8),
        ("ALIGN", (0, 2), (-1, 2), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B7C5D8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]

    for row_index in block_row_indexes:
        style.extend(
            [
                ("SPAN", (0, row_index), (-1, row_index)),
                ("BACKGROUND", (0, row_index), (-1, row_index), BLUE),
                ("TEXTCOLOR", (0, row_index), (-1, row_index), colors.white),
                ("FONTNAME", (0, row_index), (-1, row_index), "Helvetica-Bold"),
                ("FONTSIZE", (0, row_index), (-1, row_index), 9),
                ("ALIGN", (0, row_index), (-1, row_index), "LEFT"),
            ]
        )

    for idx, row_index in enumerate(room_row_indexes):
        row_color = ALT_ROW if idx % 2 == 1 else WHITE
        style.extend(
            [
                ("BACKGROUND", (0, row_index), (0, row_index), LIGHT_BLUE),
                ("BACKGROUND", (-1, row_index), (-1, row_index), LIGHT_BLUE),
                ("FONTNAME", (0, row_index), (0, row_index), "Helvetica-Bold"),
                ("FONTNAME", (-1, row_index), (-1, row_index), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, row_index), (0, row_index), NAVY),
                ("TEXTCOLOR", (-1, row_index), (-1, row_index), NAVY),
                ("FONTSIZE", (0, row_index), (0, row_index), 8),
                ("FONTSIZE", (-1, row_index), (-1, row_index), 8),
                ("ALIGN", (0, row_index), (0, row_index), "LEFT"),
                ("ALIGN", (-1, row_index), (-1, row_index), "RIGHT"),
                ("BACKGROUND", (1, row_index), (-2, row_index), row_color),
                ("FONTSIZE", (1, row_index), (-2, row_index), 7.5),
                ("TEXTCOLOR", (1, row_index), (-2, row_index), colors.HexColor("#1F1F1F")),
                ("ALIGN", (1, row_index), (-2, row_index), "CENTER"),
            ]
        )

    timetable_table.setStyle(TableStyle(style))
    return timetable_table


def export_timetable_pdf(
    grid: dict,
    output_path,
    department_name: str = "FCSE",
    semester: str = "All",
    day: str = "Monday",
) -> str:
    """Build and save the official-format room x timeslot timetable PDF."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    margin = 1 * cm
    timetable_table = _build_timetable_table(
        grid,
        department_name,
        semester,
        day,
        "GIK Institute Time Table Spring 2026",
    )

    doc = SimpleDocTemplate(
        str(output),
        pagesize=landscape(A4),
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )
    doc.build([timetable_table])
    return str(output)


def export_full_week_pdf(
    grids_by_day: dict[str, dict],
    output_path,
    department_name: str = "FCSE",
    semester: str = "All",
) -> str:
    """Build and save a multi-page PDF with one timetable per day."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    margin = 1 * cm
    page_width, _ = landscape(A4)

    story = []
    for idx, day in enumerate(days):
        grid = grids_by_day.get(day, {})
        story.append(
            _build_timetable_table(
                grid,
                department_name,
                semester,
                day,
                FULL_WEEK_TITLE,
            )
        )
        if idx < len(days) - 1:
            story.append(PageBreak())

    def _draw_footer(canvas, _doc):
        page_num = canvas.getPageNumber()
        day_label = days[page_num - 1] if 1 <= page_num <= len(days) else ""
        footer_text = f"{day_label} | Page {page_num} of {len(days)}"
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(page_width - margin, 0.5 * cm, footer_text)
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(output),
        pagesize=landscape(A4),
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )
    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return str(output)
