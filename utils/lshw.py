#!/usr/bin/env python3
"""
lshw.py

List IDEC PLC CPU and expansion-module hardware.

The hardware inventory is read from:
    D8002   CPU type
    D8037   Connected expansion-module count
    D8470+  Expansion-module information

This module can be:
    1. Run directly as a standalone serial utility.
    2. Imported by IDEC-TUI and called with an existing PLC connection.

Requirements:
    - Python 3
    - pyserial
    - MiSmSerial.py in the IDEC-TUI project root or on PYTHONPATH

Reference:
    FC6A User Manual, page 368 - Device IDs for expansion slots.
"""

import sys
from pathlib import Path

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("Connectivity failure: pyserial is not installed.")
    print("Install with: pip install pyserial")
    sys.exit(1)


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from MiSmSerial import MiSmSerial
except ImportError:
    print("Connectivity failure: MiSmSerial.py could not be imported.")
    print("Make sure MiSmSerial.py is in the project root or on PYTHONPATH.")
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


LEGACY_CPU_TYPES = {
    0x00: "10-I/O",
    0x01: "16-I/O",
    0x02: "20-I/O transistor output",
    0x03: "24-I/O",
    0x04: "40-I/O",
    0x06: "20-I/O relay output",
}


FC6A_CPU_TYPES = {
    0x12: "FC6A CAN J1939 All-in-One 40-I/O CPU",
    0x20: "FC6A Plus 16-I/O CPU",
    0x21: "FC6A Plus 32-I/O CPU",
}


FC6A_MODULE_TYPES = {
    0x00: "FC6A-N16B1, FC6A-N16B3",
    0x01: (
        "FC6A-R161, FC6A-T16K1, FC6A-T16P1, "
        "FC6A-T16K3, FC6A-T16P3"
    ),
    0x02: "FC6A-N32B3",
    0x03: "FC6A-T32K3, FC6A-T32P3",
    0x04: "FC6A-N08B1, FC6A-N08A11",
    0x05: "FC6A-R081, FC6A-T08K1, FC6A-T08P1",
    0x06: "FC6A-M08BR1",
    0x07: "FC6A-M24BR1",
    0x18: "FC6A-PH1",
    0x19: "FC6A-EXM2",
    0x1A: "FC6A-EXM1S",
    0x20: "FC6A-J2C1",
    0x21: "FC6A-J4A1",
    0x22: "FC6A-J8A1",
    0x24: "FC6A-K4A1",
    0x25: "FC6A-L06A1",
    0x26: "FC6A-L03CN1",
    0x27: "FC6A-J4CN1",
    0x28: "FC6A-J8CU1",
    0x29: "FC6A-F2M1",
    0x2A: "FC6A-F2MR1",
    0x2B: "FC6A-J4CH1Y",
    0x2C: "FC6A-EXM1M",
    0x2E: "FC6A-SIF52",
}


FC6A_MODULE_STATUS = {
    0x00: "OK",
    0x81: "Communication error",
    0x82: "Unknown device detected",
    0x83: "Device setting error",
    0x84: "Device writing error",
}


def safe_read_word(plc, register):
    if hasattr(plc, "read_word"):
        return plc.read_word(register)
    if hasattr(plc, "read"):
        return plc.read(register)
    raise AttributeError("MiSmSerial instance has no read_word() or read()")


def safe_read_block(plc, register, count):
    if hasattr(plc, "read_block"):
        return plc.read_block(register, count=count)

    prefix = register[0].upper()
    start = int(register[1:])

    return [
        int(safe_read_word(plc, f"{prefix}{start + offset:04d}"))
        for offset in range(count)
    ]


def describe_cpu_type(cpu_type):
    if cpu_type in FC6A_CPU_TYPES:
        return FC6A_CPU_TYPES[cpu_type], None

    if cpu_type in LEGACY_CPU_TYPES:
        return "FC5A or earlier CPU detected", LEGACY_CPU_TYPES[cpu_type]

    return f"Unknown CPU type 0x{cpu_type:04X}", None


def software_version(raw):
    return f"{int(raw) / 100:.2f}"


def module_status_text(status):
    return FC6A_MODULE_STATUS.get(
        status,
        f"Unknown status 0x{status:02X}",
    )


def print_expansion_module(slot, info_register, info, detail):
    info = int(info)
    detail = int(detail)

    type_id = info & 0xFF
    status = (info >> 8) & 0xFF

    if type_id == 0xFF:
        print(
            f"  Expansion slot {slot}: "
            "Legacy or unidentified expansion module | "
            f"{module_status_text(status)} | "
            f"D{info_register:04d}=0x{info:04X}, "
            f"D{info_register + 1:04d}=0x{detail:04X}"
        )
        return True

    model = FC6A_MODULE_TYPES.get(
        type_id,
        f"Unknown module type ID 0x{type_id:02X}",
    )

    position = (detail >> 8) & 0xFF
    node = (position >> 4) & 0x0F
    node_slot = position & 0x0F
    version = detail & 0xFF

    print(
        f"  Expansion slot {slot}: {model} | "
        f"{module_status_text(status)} | "
        f"node {node}, node slot {node_slot} | "
        f"software {software_version(version)} | "
        f"D{info_register:04d}=0x{info:04X}, "
        f"D{info_register + 1:04d}=0x{detail:04X}"
    )
    return True


def print_expansion_inventory(plc):
    try:
        connected = int(safe_read_word(plc, "D8037"))
    except Exception as exc:
        print(f"  Expansion module count unavailable: {exc}")
        return 0

    print(f"  Connected expansion modules: {connected}") # D8037

    if connected <= 0:
        return 0

    if connected > 63:
        print(f"  Invalid expansion module count: {connected}")
        return 0

    try:
        expansion_data = safe_read_block(
            plc,
            "D8470",
            connected * 2,
        )
    except Exception as exc:
        print(f"  Expansion module information unavailable: {exc}")
        return 0

    installed = 0

    for slot in range(1, connected + 1):
        offset = (slot - 1) * 2
        register = 8470 + offset

        if print_expansion_module(
            slot,
            register,
            expansion_data[offset],
            expansion_data[offset + 1],
        ):
            installed += 1

    return installed


def hardware_inventory(plc):
    print("Hardware inventory:")

    try:
        cpu_type = int(safe_read_word(plc, "D8002"))
    except Exception as exc:
        print(f"  CPU type unavailable: {exc}")
    else:
        #print(f"  CPU type D8002: 0x{cpu_type:04X} ({cpu_type})")

        description, cpu_class = describe_cpu_type(cpu_type)
        print(f"  CPU: {description}")

        if cpu_class is not None:
            print(f"  CPU class: {cpu_class}")

    installed = print_expansion_inventory(plc)

    if not installed:
        print("  No identifiable expansion modules reported.")


def list_candidate_ports():
    ports = []

    for port in list_ports.comports():
        ports.append({
            "device": port.device,
            "description": port.description,
            "hwid": port.hwid,
        })

    def rank_port(port_name):
        for index, hint in enumerate(PORT_HINTS):
            if hint in port_name:
                return index
        return 999

    ports.sort(key=lambda item: (rank_port(item["device"]), item["device"]))
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


def probe_plc_on_port(port_name):
    result = {
        "port": port_name,
        "connected": False,
        "reason": "",
    }

    ok, error = try_open_port_raw(port_name)
    if not ok:
        result["reason"] = f"serial open failed: {error}"
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

    try:
        safe_read_word(plc, "D8002")
        result["connected"] = True
        result["reason"] = "responded to D8002"
        return plc, result
    except Exception as exc:
        result["reason"] = f"opened serial port, but D8002 read failed: {exc}"
        return None, result


def main():
    ports = list_candidate_ports()

    if not ports:
        print("Connectivity failure: no serial devices found on this system.")
        sys.exit(2)

    plc = None
    chosen = None
    failures = []

    for port in ports:
        tested_plc, result = probe_plc_on_port(port["device"])

        if result["connected"]:
            plc = tested_plc
            chosen = result
            break

        failures.append(result)

    if plc is None:
        print("Connectivity failure: no responsive PLC found.")
        print()
        print("Probe summary:")

        for failure in failures:
            print(f"  {failure['port']}: {failure['reason']}")

        sys.exit(3)

    print(f"PLC connection: OK on {chosen['port']} ({chosen['reason']})")
    print()
    hardware_inventory(plc)


if __name__ == "__main__":
    main()
