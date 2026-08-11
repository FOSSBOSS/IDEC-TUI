#!/usr/bin/env python3
from datetime import datetime
from MiSmSerial import MiSmSerial
import sys
"""
Written and tested on Windows10.
you dont need anything special, except the MiSmSerail library,
https://github.com/Makerspace-Bangor/fc6a/blob/main/SERIAL/MiSmSerial.py
an accruate PC clock, the USB cable, python, and the knowledge of good and evil..
oops i mean the com interface. see device manager. 
I could make a UI real quick but this is example code. 
"""

PORT = "COM3"
def get_port(port=PORT):
    entered = input(f"Pres Enter to use COM3, \n else: Enter COM port [{port}]: ").strip()
    print(f"Port Enterned: {entered}")
    return entered if entered else PORT
    

def set_time(plc):
    now = datetime.now()
    plc.write("D8015", now.year % 100)
    plc.write("D8016", now.month)
    plc.write("D8017", now.day)
    plc.write("D8018", now.weekday())
    plc.write("D8019", now.hour)
    plc.write("D8020", now.minute)
    plc.write("D8021", now.second)
    # regs are populated, but time hasnt changed
    plc.write_bit("M8020", 1)   # write calendar bits
    plc.write_bit("M8020", 0)   # IDEC is extra retentive about this
    print(
        f"PLC time set to: "
        f"{now.year:04d}-{now.month:02d}-{now.day:02d} "
        f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}"
    )
port = get_port().upper() 
try:
    plc = MiSmSerial(
        port,
        device="FF",
        baud=9600,
        debug=False,
        bcc_mode="auto",
    )
except Exception as e:
    print(f"Port '{port}' is unavailable.")
    #print(f"Details: {e}")
    sys.exit(1)

try:
    #plc.write_bit("M8000", 0) #curtesy stop
    #print("M8000 set to 0 (STOP).")
    set_time(plc)
    # no one wants to stop they process for time change
    #plc.write_bit("M8000", 1)
    #print("M8000 set to 1 (Run).") 
except Exception as e:
    print(f"\nCommunication error: {e}")

       
finally:
    try:
        plc.close()
    except Exception:
        pass
        
