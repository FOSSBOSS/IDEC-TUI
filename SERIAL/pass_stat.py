#!/usr/bin/env python3
from MiSmSerial import MiSmSerial
"""
Purpose: Detect password status on plc.
Tested on FC5A, FC6A, pentra plcs
"""

PROTECTION_STATUS = {
    "0": "Not protected",
    "1": "Write protected",
    "2": "Read protected",
    "3": "Read and write protected",
}


plc = MiSmSerial(
    "/dev/ttyACM0",
    device="FF",
    baud=9600,
    timeout=2.0,
    debug=False,
    bcc_mode="auto",
)

try:
    # RS: Read PLC Operating Status
    reply = plc._xfer("0", "R", "S")
    plc._raise_if_err(reply)

    if len(reply.data) < 3:
        raise IOError(f"RS reply is too short: {reply.data!r}")

    # RS data layout:
    #   data[0] = RUN/STOP status
    #   data[1] = timer/counter changed status
    #   data[2] = user-program protection status
    protection = reply.data[2:3].decode("ascii")

    if protection not in PROTECTION_STATUS:
        raise IOError(
            f"Unknown protection status {protection!r}: "
            f"raw={reply.raw.hex()}"
        )

    print()
    print(f"Protection value:  {protection}")
    print(f"Protection status: {PROTECTION_STATUS[protection]}")

    if protection == "0":
        print("RESULT: No password protection is reported.")
    else:
        print("RESULT: PLC is password protected.")

finally:
    plc.close()
