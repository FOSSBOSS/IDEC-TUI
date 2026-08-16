#!/usr/bin/env python3

from getpass import getpass
from MiSmSerial import MiSmSerial
"""
Expirament with Commands:
   Use _xfer() to send raw test commands.
   
   Here, we are testing the security bits
"""
PORT = "/dev/ttyACM0"


def status(plc, label):
    rep = plc._xfer("0", "R", "S", b"")
    plc._raise_if_err(rep)

    data = rep.data.decode("ascii")

    print(f"\n{label}")
    print("Raw:        ", data)
    print("Protection: ", data[2])
    print("Program CRC:", data[4:8])

    return data


plc = MiSmSerial(
    PORT,
    device="FF",
    baud=9600,
    debug=True,
    bcc_mode="auto",
)

try:
    status(plc, "Before unlock")

    password = getpass("\nPLC password: ")
    pw = password.encode("ascii")

    if len(pw) > 8:
        raise ValueError("WV protect code is limited to 8 characters")

    pw = pw.ljust(8, b"\x00")

    print("\nAttempting temporary protection disable...")
    rep = plc._xfer("0", "W", "V", pw + b"0")
    plc._raise_if_err(rep)

    print("Password accepted.")
    status(plc, "After unlock")

    print("\nSending Ri...")
    rep = plc._xfer("0", "R", "i", b"00001FB800040")
    plc._raise_if_err(rep)

    print("Ri accepted:", rep.data)
    status(plc, "After Ri")

finally:
    plc.close()
