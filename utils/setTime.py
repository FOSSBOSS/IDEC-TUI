#!/usr/bin/env python3
from datetime import datetime

def set_time(plc):
    """Set the PLC clock to the current PC time."""

    now = datetime.now()

    plc.write("D8015", now.year % 100)
    plc.write("D8016", now.month)
    plc.write("D8017", now.day)
    plc.write("D8018", now.weekday())
    plc.write("D8019", now.hour)
    plc.write("D8020", now.minute)
    plc.write("D8021", now.second)

    # Registers are populated, but the PLC clock has not changed yet.
    plc.write_bit("M8020", 1)
    plc.write_bit("M8020", 0)

    print(
        "PLC time set to: "
        f"{now.year:04d}-{now.month:02d}-{now.day:02d} "
        f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}"
    )
