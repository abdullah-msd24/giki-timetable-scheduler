# GIKI Timetable Scheduler

**Course:** CS378 - Design and Analysis of Algorithms  \
**Institute:** GIK Institute of Engineering Sciences and Technology  \
**Semester:** Spring 2026

## Project Overview
GIKI Timetable Scheduler is a desktop application that generates course timetables using constraint satisfaction techniques. It reads course and room data, builds a scheduling problem, and produces feasible timetables with a GUI for filtering by department, section, semester, and day. Export to PDF is supported for sharing official schedules.

## Features
- 🧠 CSP-based timetable generation with hard constraints
- ⚡ Backtracking search with MRV and forward checking
- 🧩 Section and semester-aware scheduling
- 🗓️ Full Week and per-day timetable views
- 📤 PDF export (single day or full week)
- 🔍 Filters for department, section, semester, and course type

## Algorithm Explanation
The scheduler models timetable generation as a Constraint Satisfaction Problem (CSP):
- **Variables:** Each course session (expanded by credit hours)
- **Domains:** Room x timeslot combinations that satisfy room type, capacity, and building rules
- **Constraints:** No room conflicts, no teacher conflicts, and no section clashes

The solver uses:
- **Backtracking search** to explore assignments
- **MRV (Minimum Remaining Values)** to choose the next variable
- **Forward checking** to prune invalid domain values early

This combination reduces search space and speeds up feasible solution discovery.

## Tech Stack
- Python
- Tkinter (GUI)
- pandas (data parsing)
- reportlab (PDF export)
- openpyxl (Excel support)

## Folder Structure
```
.
├─ data/
│  ├─ output/
│  └─ raw/
├─ src/
│  ├─ gui/
│  ├─ models/
│  ├─ solver/
│  └─ utils/
├─ diag_full.py
├─ main.py
├─ requirements.txt
├─ test_parser.py
├─ test_solver.py
└─ test_solver2.py
```

## Installation and Run
1) Create a virtual environment and install dependencies:
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

2) Run the GUI:
```
python -m src.gui.app
```

## Screenshots
_Add screenshots here (GUI main view, Full Week view, PDF export preview)._ 

## Limitations
- Large departments may time out due to the search space
- Input data quality (missing semesters or sections) can reduce accuracy
- Multi-section shared courses rely on heuristics when semester data is missing

## Course Info
This project was developed for **CS378 - Design and Analysis of Algorithms** at **GIK Institute of Engineering Sciences and Technology**, **Spring 2026**.
