#!/usr/bin/env python3
"""
plc_diag.py

Simple IDEC PLC connectivity and health diagnostic script.

What it does:
- Detects the host OS
- Scans available serial ports
- Tries to identify a responsive PLC
- Reports connectivity failures briefly
- Reads:
    - D8005 general error bitfield
    - D8006 user program execution error code
    - M8004 user program execution error flag
    - M8005 data link communication error flag
    - M8006 data link communication stopped flag
    - M8255 SD card transfer/upload/download execution error flag
    - D8056 battery voltage (mV)
    - D8029 firmware version (/100)
    - PLC date/time
    - active outputs Y0-Y7

Behavior:
- D8005 is decoded as a bitfield
- D8006 is decoded as a single execution error code, but only reported if M8004 is ON

Requirements:
- Python 3
- pyserial
- MiSmSerial.py available in the same directory or on PYTHONPATH

NOTES:

https://lit.stromquist.com/docs/IDEC/KIT-FC6A_UserMan.pdf
page 368 Device IDs for expansion slots.
D8000, D8002 CPU IDs. TODO: locate product IDS for CPU IDs.
"""

import sys
import platform
from datetime import datetime
from enum import IntFlag

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("Connectivity failure: pyserial is not installed.")
    print("Install with: pip install pyserial")
    sys.exit(1)

try:
    from MiSmSerial import MiSmSerial
except ImportError:
    print("Connectivity failure: MiSmSerial.py could not be imported.")
    print("Make sure MiSmSerial.py is in the same folder or on PYTHONPATH.")
    sys.exit(1)


DEVICE = "FF"
BAUD = 9600
DEBUG = False

PORT_HINTS = [
    "/dev/ttyACM",
    "/dev/ttyUSB",
    "COM",
    "/dev/cu.usb",
    "/dev/tty.usb",
]

OUTPUT_BITS = [f"Y{i}" for i in range(8)]

PLC_TIME_REGS = {
    "year": "D8015",
    "month": "D8016",
    "day": "D8017",
    "weekday": "D8018",
    "hour": "D8019",
    "minute": "D8020",
    "second": "D8021",
}


class D8005Error(IntFlag):
    POWER_FAILURE = 1 << 0
    WATCHDOG_TIMER = 1 << 1
    DATALINK_CONNECTION_ERROR = 1 << 2
    USER_PROGRAM_ROM_CRC_ERROR = 1 << 3
    TIMER_COUNTER_PRESET_VALUE_CHANGE_ERROR = 1 << 4
    # bit 5 reserved
    KEEP_DATA_SUM_CHECK_ERROR = 1 << 6
    USER_PROGRAM_SYNTAX_ERROR = 1 << 7
    USER_PROGRAM_DOWNLOAD_ERROR = 1 << 8
    SYSTEM_ERROR = 1 << 9
    CLOCK_ERROR = 1 << 10
    EXPANSION_BUS_INITIALIZATION_ERROR = 1 << 11
    SD_MEMORY_CARD_TRANSFER_ERROR = 1 << 12
    USER_PROGRAM_EXECUTION_ERROR = 1 << 13
    SD_MEMORY_CARD_ACCESS_ERROR = 1 << 14


D8006_ERRORS = {
    1: "Source/destination device exceeds range.",
    2: "MUL result exceeds data type range.",
    3: "DIV result exceeds data type range, or division by 0.",
    4: "BCDLS has S1 or S1+1 exceeding 9999.",
    5: "S1 is 10,000 or higher in HTOB(W), or 100,000,000 or higher in HTOB(D).",
    6: "BTOH has at least one digit in S1 exceeding 9.",
    7: "HTOA/ATOH/BTOA/ATOB has quantity of digits to convert out of range.",
    8: "ATOH/ATOB has non-ASCII data for S1 through S1+4.",
    9: "WEEK/WKTIM range error or WKTBL/WKTIM setup problem.",
    10: "YEAR/WKTBL month/day data out of range.",
    11: "DGRD specified as BCD 5 digits but value exceeds 65535.",
    12: "CVXTY/CVYTX executed without matching XYFS, or data type mismatch.",
    13: "CVXTY/CVYTX has S2 exceeding the value specified in XYFS.",
    14: "Label in LJMP, LCAL, or DJNZ is not found.",
    16: "Executed invalid PID/PIDA instruction.",
    18: "Attempted to execute an instruction that cannot be used in an interrupt program.",
    19: "Attempted to execute an instruction not available for the PLC.",
    20: "Pulse output instructions have invalid values in operation parameters.",
    21: "DECO has S1 exceeding 255.",
    22: "BCNT has S2 exceeding 256.",
    23: "ICMP>= has S1 < S3.",
    25: "BCDLS has S2 exceeding 7.",
    26: "DI or EI executed when interrupt input or timer interrupt is not programmed.",
    27: "Work area is broken when using DTML, DTIM, DTMH, DTMS, or TTIM.",
    28: "Source device data for float instruction exceeds valid range.",
    29: "Result of float instruction exceeds data type range.",
    30: "SFTL/SFTR shift data size or number of bits to shift exceeds valid range.",
    31: "FIFOF used before FIFO data file was registered.",
    32: "TADD, TSUB, HOUR, or HTOS has invalid source data in S1.",
    33: "RNDM has invalid data. S1 > S2 or S1/S2 exceeds 32767.",
    35: "SUM result exceeds valid range for selected data type, or S2 is 0.",
    36: "DLOG/TRACE CSV file capacity exceeds daily maximum size or file count.",
    41: "SD memory card is write protected.",
    42: "SCRPT instruction completed with an abnormal result.",
    46: "SCALE has invalid minimum/maximum values or dead band exceeds range.",
    48: "Pulse output instructions using the same pulse output are executed at the same time.",
    49: "Pulse output instruction used absolute position counter before ABS initialization.",
}


def detect_os():
    return platform.system(), platform.release(), platform.version()


def list_candidate_ports():
    ports = []
    for p in list_ports.comports():
        ports.append({
            "device": p.device,
            "description": p.description,
            "hwid": p.hwid,
        })

    def rank_port(port_name: str) -> int:
        for idx, hint in enumerate(PORT_HINTS):
            if hint in port_name:
                return idx
        return 999

    ports.sort(key=lambda x: (rank_port(x["device"]), x["device"]))
    return ports


def try_open_port_raw(port_name, baud=BAUD, timeout=0.5):
    try:
        ser = serial.Serial(
            port=port_name,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_ODD,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            write_timeout=timeout,
        )
        ser.close()
        return True, None
    except Exception as exc:
        return False, str(exc)


def safe_read_bit(plc, reg):
    try:
        return plc.read_bit(reg, 0)
    except TypeError:
        pass
    except Exception:
        raise

    return plc.read_bit(reg)


def safe_read_word(plc, reg):
    if hasattr(plc, "read_word"):
        return plc.read_word(reg)
    if hasattr(plc, "read"):
        return plc.read(reg)
    raise AttributeError("MiSmSerial instance has no read_word() or read()")


def interpret_bool(val):
    if isinstance(val, bool):
        return val
    try:
        return bool(int(val))
    except Exception:
        return False


def probe_plc_on_port(port_name):
    result = {
        "port": port_name,
        "connected": False,
        "reason": "",
    }

    ok, err = try_open_port_raw(port_name)
    if not ok:
        result["reason"] = f"serial open failed: {err}"
        return None, result

    try:
        plc = MiSmSerial(port_name, device=DEVICE, debug=DEBUG)
    except TypeError:
        try:
            plc = MiSmSerial(port_name, device=DEVICE)
        except Exception as exc:
            result["reason"] = f"MiSmSerial init failed: {exc}"
            return None, result
    except Exception as exc:
        result["reason"] = f"MiSmSerial init failed: {exc}"
        return None, result

    for reg in ("M8004", "M8005", "M8006"):
        try:
            _ = safe_read_bit(plc, reg)
            result["connected"] = True
            result["reason"] = f"responded to {reg}"
            return plc, result
        except Exception:
            continue

    result["reason"] = "opened serial port, but PLC did not respond to probe registers"
    return None, result


def decode_d8005(raw_value):
    try:
        raw_value = int(raw_value)
    except Exception:
        return []

    valid_mask = 0
    for flag in D8005Error:
        valid_mask |= flag.value

    masked = raw_value & valid_mask
    return [flag for flag in D8005Error if masked & flag.value]


def format_d8005_error(flag):
    names = {
        D8005Error.POWER_FAILURE: "Power failure",
        D8005Error.WATCHDOG_TIMER: "Watchdog timer error",
        D8005Error.DATALINK_CONNECTION_ERROR: "Datalink connection error",
        D8005Error.USER_PROGRAM_ROM_CRC_ERROR: "User program ROM CRC error",
        D8005Error.TIMER_COUNTER_PRESET_VALUE_CHANGE_ERROR: "Timer/counter preset value change error",
        D8005Error.KEEP_DATA_SUM_CHECK_ERROR: "Keep data sum check error",
        D8005Error.USER_PROGRAM_SYNTAX_ERROR: "User program syntax error",
        D8005Error.USER_PROGRAM_DOWNLOAD_ERROR: "User program download error",
        D8005Error.SYSTEM_ERROR: "System error",
        D8005Error.CLOCK_ERROR: "Clock error",
        D8005Error.EXPANSION_BUS_INITIALIZATION_ERROR: "Expansion bus initialization error",
        D8005Error.SD_MEMORY_CARD_TRANSFER_ERROR: "SD memory card transfer error",
        D8005Error.USER_PROGRAM_EXECUTION_ERROR: "User program execution error",
        D8005Error.SD_MEMORY_CARD_ACCESS_ERROR: "SD memory card access error",
    }
    return names.get(flag, f"Unknown flag {flag}")


def read_d8005_errors(plc):
    try:
        raw = int(safe_read_word(plc, "D8005"))
        active = decode_d8005(raw)
        return {"readable": True, "raw": raw, "active": active, "error": None}
    except Exception as exc:
        return {"readable": False, "raw": None, "active": [], "error": str(exc)}


def read_d8006_error(plc):
    try:
        raw = int(safe_read_word(plc, "D8006"))
        return {
            "readable": True,
            "raw": raw,
            "text": D8006_ERRORS.get(raw, f"Unknown execution error code ({raw})"),
            "error": None,
        }
    except Exception as exc:
        return {
            "readable": False,
            "raw": None,
            "text": None,
            "error": str(exc),
        }


def read_status_bits(plc):
    status = {}
    mapping = {
        "M8004": "User program execution error",
        "M8005": "Data link communication error",
        "M8006": "Data link communication stopped",
        "M8255": "SD memory card download/upload execution error output",
    }

    for reg, meaning in mapping.items():
        try:
            val = interpret_bool(safe_read_bit(plc, reg))
            status[reg] = {"value": val, "meaning": meaning, "error": None}
        except Exception as exc:
            status[reg] = {"value": None, "meaning": meaning, "error": str(exc)}

    return status


def battery_status_from_mv(mv):
    try:
        volts = int(mv) / 1000.0
    except Exception:
        return "unknown"

    if 2.7 <= volts <= 3.3:
        return f"{volts:.3f} V - fine"
    if volts < 2.7:
        return f"{volts:.3f} V - low battery"
    return f"{volts:.3f} V - above expected range"


def read_battery(plc):
    try:
        raw = int(safe_read_word(plc, "D8056"))
        return {
            "readable": True,
            "raw_mv": raw,
            "text": battery_status_from_mv(raw),
            "error": None,
        }
    except Exception as exc:
        return {
            "readable": False,
            "raw_mv": None,
            "text": "unknown",
            "error": str(exc),
        }


def read_firmware_version(plc):
    try:
        raw = int(safe_read_word(plc, "D8029"))
        version = raw / 100.0
        return {
            "readable": True,
            "raw": raw,
            "text": f"{version:.2f}",
            "error": None,
        }
    except Exception as exc:
        return {
            "readable": False,
            "raw": None,
            "text": None,
            "error": f"could not read D8029: {exc}",
        }


def read_outputs(plc):
    active = []
    failed = []

    for reg in OUTPUT_BITS:
        try:
            val = safe_read_bit(plc, reg)
            if interpret_bool(val):
                active.append(reg)
        except Exception:
            failed.append(reg)

    return active, failed


def read_plc_datetime(plc):
    values = {}
    for key, reg in PLC_TIME_REGS.items():
        try:
            values[key] = int(safe_read_word(plc, reg))
        except Exception as exc:
            return {
                "readable": False,
                "datetime": None,
                "error": f"could not read {reg}: {exc}",
            }

    try:
        year = values["year"]
        if year < 100:
            year += 2000

        dt = datetime(
            year=year,
            month=values["month"],
            day=values["day"],
            hour=values["hour"],
            minute=values["minute"],
            second=values["second"],
        )
        return {"readable": True, "datetime": dt, "error": None}
    except Exception as exc:
        return {
            "readable": False,
            "datetime": None,
            "error": f"invalid PLC time values: {exc}",
        }


def summarize_primary_status(status_bits, d8005_info, d8006_info):
    problems = []

    for reg in ("M8004", "M8005", "M8006", "M8255"):
        if status_bits[reg]["value"] is True:
            problems.append(f"{reg} ON")

    if d8005_info["readable"] and d8005_info["active"]:
        problems.extend(format_d8005_error(flag) for flag in d8005_info["active"])

    if status_bits["M8004"]["value"] is True and d8006_info is not None:
        if d8006_info["readable"]:
            problems.append(f"D8006={d8006_info['raw']}")
        else:
            problems.append("D8006 unreadable")

    if problems:
        return "PLC reachable, active issues: " + ", ".join(problems)
    return "PLC reachable, no active errors detected"


def print_status_bits(status_bits):
    print("Status bits:")
    for reg in ("M8004", "M8005", "M8006", "M8255"):
        info = status_bits[reg]
        if info["value"] is None:
            print(f"  {reg}: unreadable - {info['error']}")
        else:
            state = "ON" if info["value"] else "OFF"
            print(f"  {reg}: {state} - {info['meaning']}")


def print_d8005_report(d8005_info):
    if not d8005_info["readable"]:
        print(f"D8005: unreadable ({d8005_info['error']})")
        return

    print(f"D8005 raw: {d8005_info['raw']}")
    if d8005_info["active"]:
        print("Active D8005 errors:")
        for flag in d8005_info["active"]:
            print(f"  - {format_d8005_error(flag)}")
    else:
        print("Active D8005 errors: none")


def print_d8006_report(status_bits, d8006_info):
    if status_bits["M8004"]["value"] is not True:
        #print("D8006: not relevant (M8004 is OFF)")
        return

    if d8006_info is None:
        print("D8006: not read")
        return

    if not d8006_info["readable"]:
        print(f"D8006: unreadable ({d8006_info['error']})")
        return

    print(f"D8006 code: {d8006_info['raw']}")
    print(f"D8006 meaning: {d8006_info['text']}")


def main():
    host_now = datetime.now()
    os_name, os_release, _ = detect_os()

    print(f"Host OS: {os_name} {os_release}")
    print(f"Host time: {host_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    ports = list_candidate_ports()
    if not ports:
        print("Connectivity failure: no serial devices found on this system.")
        sys.exit(2)

    #print("Available serial devices:")
    #for p in ports:
    #    print(f"  {p['device']:<18} {p['description']}")
    #print()

    plc = None
    chosen = None
    failures = []

    for p in ports:
        tested_plc, result = probe_plc_on_port(p["device"])
        if result["connected"]:
            plc = tested_plc
            chosen = result
            break
        failures.append(result)

    if plc is None:
        print("Connectivity failure: no responsive PLC found on available serial ports.")
        print()
        print("Probe summary:")
        for f in failures:
            print(f"  {f['port']}: {f['reason']}")
        sys.exit(3)

    status_bits = read_status_bits(plc)
    d8005_info = read_d8005_errors(plc)
    d8006_info = read_d8006_error(plc) if status_bits["M8004"]["value"] is True else None
    battery_info = read_battery(plc)
    firmware_info = read_firmware_version(plc)
    plc_time_info = read_plc_datetime(plc)
    active_outputs, failed_outputs = read_outputs(plc)

    print(f"PLC connection: OK on {chosen['port']} ({chosen['reason']})")
    print(f"Summary: {summarize_primary_status(status_bits, d8005_info, d8006_info)}")
    print()

    print("PLC report")
    print("----------")
    print("Connectivity: good")
    print_status_bits(status_bits)
    print()

    print_d8005_report(d8005_info)
    print()
    print_d8006_report(status_bits, d8006_info)
    print()

    if active_outputs:
        print(f"Active outputs: {', '.join(active_outputs)}")
    else:
        print("Active outputs: none detected")

    if failed_outputs:
        print(f"Unreadable outputs: {', '.join(failed_outputs)}")

    print()

    if battery_info["readable"]:
        print(f"Battery: {battery_info['text']} (D8056={battery_info['raw_mv']} mV)")
    else:
        print(f"Battery: unavailable ({battery_info['error']})")

    if firmware_info["readable"]:
        print(f"Firmware version: {firmware_info['text']} (D8029={firmware_info['raw']})")
    else:
        print(f"Firmware version: unavailable ({firmware_info['error']})")

    if plc_time_info["readable"]:
        print(f"PLC date/time: {plc_time_info['datetime'].strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print(f"PLC date/time: unavailable ({plc_time_info['error']})")


if __name__ == "__main__":
    main()
