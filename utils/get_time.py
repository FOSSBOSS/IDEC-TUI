#!/usr/bin/env python3
"""
Get / check the PLC system time
"""
from datetime import datetime

def get_time(plc):
    """Read and report the current PLC date/time."""

    year = int(plc.read("D8008"))
    month = int(plc.read("D8009"))
    day = int(plc.read("D8010"))
    weekday = int(plc.read("D8011"))
    hour = int(plc.read("D8012"))
    minute = int(plc.read("D8013"))
    second = int(plc.read("D8014"))

    if year < 100:
        year += 2000

    plc_time = datetime(
        year=year,
        month=month,
        day=day,
        hour=hour,
        minute=minute,
        second=second,
    )

    print(f"PLC time: {plc_time:%Y-%m-%d %H:%M:%S}")

    return plc_time
