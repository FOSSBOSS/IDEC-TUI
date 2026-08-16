#!/usr/bin/env python3

from getpass import getpass
from MiSmSerial import MiSmSerial

PORT = "/dev/ttyACM0"

plc = MiSmSerial(
    PORT,
    device="FF",
    baud=9600,
    debug=True,
    bcc_mode="auto",
)
def status(plc, label):
    rep = plc._xfer("0", "R", "S", b"")
    plc._raise_if_err(rep)

    data = rep.data.decode("ascii")
    print(f"\n{label}")
    print("Raw:        ", data)
    print("Protection: ", data[2])
    print("Program CRC:", data[4:8])


status(plc, "Before unlock")

password = getpass("PLC password: ")
pw = password.encode("ascii").ljust(8, b"\x00")

rep = plc._xfer("0", "W", "V", pw + b"0")
plc._raise_if_err(rep)

status(plc, "After unlock")

rep = plc._xfer("0", "R", "i", b"00001FB800040")
plc._raise_if_err(rep)

status(plc, "After Ri")

try:
    password = getpass("PLC password: ")
    pw = password.encode("ascii")

    if len(pw) > 8:
        raise ValueError("WV protect code is limited to 8 characters")

    # Protocol specifies NUL padding, not ASCII '0'.
    pw = pw.ljust(8, b"\x00")

    print("\nAttempting temporary protection disable...")
    rep = plc._xfer("0", "W", "V", pw + b"0")
    plc._raise_if_err(rep)

    print("Password accepted; protection temporarily disabled.")

    print("\nSending Ri...")
    rep = plc._xfer("0", "R", "i", b"00001FB800040")
    plc._raise_if_err(rep)

    print("Ri accepted:", rep.data)
    status(plc, label)

finally:
    plc.close()
"""
WRONG PASSWD Given:
PLC password: 

Attempting temporary protection disable...
TX(ascii): FF0WVH0twater0
TX(hex):   05464630575648307477617465723037440d
RX(hex):   06303132303533300d
Traceback (most recent call last):
  File "/home/l/fc6a/test/1_n.py", line 28, in <module>
    plc._raise_if_err(rep)
  File "/home/l/fc6a/test/MiSmSerial.py", line 415, in _raise_if_err
    raise IOError(f"ACK NG code={rep.ng_code} raw={rep.raw.hex()}")
OSError: ACK NG code=05 raw=06303132303533300d

Right Passwd Given:
PLC password: 

Attempting temporary protection disable...
TX(ascii): FF0WVDRYW00D10
TX(hex):   05464630575644525957303044313036390d
RX(hex):   0630313033370d
Password accepted; protection temporarily disabled.

Sending Ri...
TX(ascii): FF0Ri00001FB800040
TX(hex):   0546463052693030303031464238303030343033370d
RX(hex):   06303130383346463030303033430d
Ri accepted: b'83FF0000'


"""
