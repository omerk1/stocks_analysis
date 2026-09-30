"""M21 -- Confirmed break through the MA as an entry signal (DESIGN.md M21;
PREREGISTRATION.md, 2026-09-30). The mirror of M20: same runner, same
placebo panel, same generic-move control, event = the confirmed *break*
(`features/respect.py::break_flags`) instead of the confirmed bounce.

Usage mirrors `bounce_entry_run.py`:
  python -m src.signals.moving_averages.break_entry_run --feasibility
  python -m src.signals.moving_averages.break_entry_run
Writes `m21_break_entry_{feasibility,primary,sensitivity,kill}.csv` under
output/moving_averages (gitignored).
"""

from __future__ import annotations

from src.signals.moving_averages.bounce_entry_run import main

if __name__ == "__main__":
    main("break")
