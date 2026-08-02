#!/usr/bin/env python3
"""
MiSmTCP - IDEC MicroSmart "Maintenance Protocol" over TCP/IP (ASCII framing)

Key points:
- Default TCP port: 2101 (global PLC_PORT)
- Frames are ASCII-based, terminated by CR (0x0D)
- Request format:
    ENQ(0x05) + dev(2 ASCII) + cont('0'/'1') + cmd(1) + dtype(1) + payload + BCC(2 ASCII hex) + CR
- Reply format:
    ACK(0x06) or NAK(0x15) + dev(2) + cmd(1) + data + BCC(2) + CR
- Reply BCC includes the leading ACK/NAK byte (validated by your captures).
- Request BCC mode can differ by link/bridge/CPU. This library supports:
    bcc_mode="auto" (default): try include-ENQ first; if NAK 10, retry exclude-ENQ and lock mode
    bcc_mode="enq":  XOR includes ENQ
    bcc_mode="no_enq": XOR excludes ENQ

Simple enumerable I/O:
- output(0,1) or output("Q0",1) -> writes Y bit using payload like "00001" (exactly your table)
- input(0) or input("I0") -> reads X bit

Requires: Python standard library only
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any, Union
import struct
import time
import socket


# -------------------------
# Globals
# -------------------------

PLC_PORT = 2101
DEFAULT_DEVICE = "FF"
DEFAULT_TIMEOUT = 1.0
#PRECISION = 3 # default is 6, on the PLCs, but my typical use is 3-4, so.. 

# -------------------------
# Low-level helpers
# -------------------------

def _xor_bcc(data: bytes) -> int:
    x = 0
    for b in data:
        x ^= b
    return x & 0xFF


def _to_ascii_hex_byte(b: int) -> bytes:
    return f"{b & 0xFF:02X}".encode("ascii")


def _ascii_hex_to_int(two_ascii: bytes) -> int:
    return int(two_ascii.decode("ascii"), 16)


def _is_hex_ascii(data: bytes) -> bool:
    for c in data:
        if not (48 <= c <= 57 or 65 <= c <= 70):  # '0'..'9' or 'A'..'F'
            return False
    return True


def _pad4(num: int) -> str:
    if num < 0 or num > 9999:
        raise ValueError("operand number must be 0..9999")
    return f"{num:04d}"


def _parse_addr(addr: Union[str, int], dtype: Optional[str] = None) -> Tuple[str, int]:
    """
    Accept:
      - "D0100", "M8070", "X0007", "Y0000", "T0001", "C0099", ...
      - or (number int) with dtype provided (e.g. read_bit(7, dtype='X'))
    Returns: (dtype_char, operand_number_int)
    """
    if isinstance(addr, int):
        if not dtype or len(dtype) != 1:
            raise ValueError("dtype (1 char) required when addr is int")
        return dtype, addr

    s = str(addr).strip()
    # Add support for dot bit word syntax:: ie::"M8004.15"
    if "." in s:
        base, bit = s.split(".")
        if not bit.isdigit():
            raise ValueError("bit index must be numeric")

        d = base[0]
        n = base[1:]

        if not n.isdigit():
            raise ValueError("addr numeric portion must be digits")

        word = int(n)
        b = int(bit)

        if b < 0 or b > 15:
            raise ValueError("bit must be 0..15")

        return d, word * 16 + b
    #-----------------------------------------------------
    if len(s) < 2:
        raise ValueError("addr must look like 'D0100' or 'M8070'")

    d = s[0]
    n = s[1:]
    if not n.isdigit():
        raise ValueError("addr numeric portion must be digits")
    return d, int(n)


def _dtype_for_bit(dtype: str) -> str:
    """
    Bit operands are lowercase: x y m r
    """
    m = {"X": "x", "Y": "y", "M": "m", "R": "r", "x": "x", "y": "y", "m": "m", "r": "r"}
    if dtype not in m:
        raise ValueError("bit dtype must be X/Y/M/R (or x/y/m/r)")
    return m[dtype]


def _dtype_for_nbyte(dtype: str) -> str:
    """
    N-byte operands use their defined letter (often uppercase for D/W/C/T, etc.)
    """
    if len(dtype) != 1:
        raise ValueError("dtype must be 1 character")
    return dtype


def _parse_io(io: Union[str, int], is_out: bool) -> Tuple[str, int]:
    """
    Simple enumerable I/O addressing:
      output(0,1)         -> Q0 -> Y0
      output("Q7",1)      -> Y7
      output("Y0007",1)   -> Y7

      input(0)            -> I0 -> X0
      input("I7")         -> X7
      input("X0007")      -> X7
    """
    if isinstance(io, int):
        if io < 0 or io > 9999:
            raise ValueError("bit index must be 0..9999")
        return ("Y" if is_out else "X"), io

    s = str(io).strip().upper()
    if not s:
        raise ValueError("empty IO address")

    head, tail = s[0], s[1:]

    if head == "Q":
        if not is_out:
            raise ValueError("input() does not accept Q addresses")
        if not tail.isdigit():
            raise ValueError("Q address must be like Q0, Q7")
        return "Y", int(tail)

    if head == "I":
        if is_out:
            raise ValueError("output() does not accept I addresses")
        if not tail.isdigit():
            raise ValueError("I address must be like I0, I7")
        return "X", int(tail)

    if head in ("Y", "X"):
        if (head == "Y") != is_out:
            raise ValueError("output() expects Y/Q; input() expects X/I")
        if not tail.isdigit():
            raise ValueError("X/Y address must be numeric like X0007, Y0")
        return head, int(tail)

    raise ValueError("IO must start with Q/I or X/Y (e.g. Q0, I7, Y0000, X0007)")

# -------------------------
# Connection error handling
# -------------------------
class MiSmConnectionError(ConnectionError):
    """Raised when communication with the PLC cannot be established."""

def connect(self):
    if self._sock is not None:
        return

    try:
        self._sock = socket.create_connection(
            (self.host, self.port),
            timeout=self.timeout,
        )

    except TimeoutError as exc:
        raise MiSmConnectionError(
            f"PLC not found at {self.host}:{self.port}. "
            "Check the IP address, PLC power, and network cabling."
        ) from exc

    except ConnectionRefusedError as exc:
        raise MiSmConnectionError(
            f"PLC connection refused at {self.host}:{self.port}. "
            "Check that maintenance communication is enabled."
        ) from exc

    except OSError as exc:
        raise MiSmConnectionError(
            f"Unable to connect to PLC at {self.host}:{self.port}: {exc}"
        ) from exc

# -------------------------
# Reply parsing / ACK-NAK
# -------------------------

@dataclass
class Reply:
    kind: str                 # "ACK_OK", "ACK_NG", "NAK", "MALFORMED", "EMPTY", "UNKNOWN"
    raw: bytes
    ctrl: bytes = b""
    device: str = ""
    command: str = ""
    data: bytes = b""
    bcc_recv: Optional[int] = None
    bcc_calc: Optional[int] = None
    bcc_ok: bool = False
    ng_code: str = ""         # for ACK_NG
    nak_code: str = ""        # for NAK


def _parse_reply(raw: bytes) -> Reply:
    """
    Reply BCC includes ctrl (ACK=0x06 or NAK=0x15).
    """
    if not raw:
        return Reply(kind="EMPTY", raw=raw)

    if raw[-1:] != b"\r" or len(raw) < 6:
        return Reply(kind="MALFORMED", raw=raw)

    ctrl = raw[0:1]
    dev = raw[1:3]
    cmd = raw[3:4]
    bcc_ascii = raw[-3:-1]
    data = raw[4:-3]

    try:
        bcc_recv = _ascii_hex_to_int(bcc_ascii)
    except Exception:
        return Reply(kind="MALFORMED", raw=raw)

    bcc_calc = _xor_bcc(raw[0:-3])
    bcc_ok = (bcc_calc == bcc_recv)

    rep = Reply(
        kind="UNKNOWN",
        raw=raw,
        ctrl=ctrl,
        device=dev.decode("ascii", errors="replace"),
        command=cmd.decode("ascii", errors="replace"),
        data=data,
        bcc_recv=bcc_recv,
        bcc_calc=bcc_calc,
        bcc_ok=bcc_ok,
    )

    if ctrl == b"\x15":
        rep.kind = "NAK"
        rep.nak_code = data[:2].decode("ascii", errors="replace") if len(data) >= 2 else ""
        return rep

    if ctrl == b"\x06":
        # Some IDEC replies use command '2' for "ACK but NG (error)".
        if rep.command == "2":
            rep.kind = "ACK_NG"
            rep.ng_code = data[:2].decode("ascii", errors="replace") if len(data) >= 2 else ""
            return rep
        rep.kind = "ACK_OK"
        return rep

    return rep


def is_ack(rep: Reply) -> bool:
    return rep.kind in ("ACK_OK", "ACK_NG")


def is_nak(rep: Reply) -> bool:
    return rep.kind == "NAK"


def ack_ok(rep: Reply) -> bool:
    return rep.kind == "ACK_OK" and rep.bcc_ok


def ack_ng(rep: Reply) -> bool:
    return rep.kind == "ACK_NG" and rep.bcc_ok


# -------------------------
# Main TCP client
# -------------------------

class MiSmTCP:
    """
    TCP client for IDEC MicroSmart / FC6A Maintenance Protocol.

    The public API intentionally mirrors MiSmSerial as closely as possible:
      read("D0100")          # word read
      read("D0100.03")       # bit read inside a word
      write("D0100", 1234)   # word write
      write("D0100.03", 1)   # bit write inside a word
      read_bit("M8070")      # explicit native/special bit device read
      write_bit("Y0000", 1)  # explicit native/special bit device write
      read_float("D0100")
      write_float("D0100", 1.23)

    The PLC Ethernet connection must be configured as Maintenance Communication
    server. FC6A default Maintenance TCP port is commonly 2101.
    """

    def __init__(
        self,
        host: str,
        port: int = PLC_PORT,
        device: str = DEFAULT_DEVICE,
        timeout: float = DEFAULT_TIMEOUT,
        debug: bool = False,
        bcc_mode: str = "auto",   # "auto" | "enq" | "no_enq"
        keep_open: bool = True,
        connect_now: bool = True,
        precision = 3,
    ):
        if len(device) != 2:
            raise ValueError("device must be 2 ASCII hex chars (e.g. 'FF')")
        if bcc_mode not in ("auto", "enq", "no_enq"):
            raise ValueError("bcc_mode must be 'auto', 'enq', or 'no_enq'")

        self.host = host
        self.port = int(port)
        self.device = device.upper()
        self.timeout = timeout
        self.debug = debug
        self.bcc_mode = bcc_mode
        self.keep_open = keep_open
        self._sock: Optional[socket.socket] = None
        self.precision = precision

        if connect_now and keep_open:
            self.connect()

    # better error handling when connection issues occur 
    def connect(self) -> None:
        """Open the TCP connection if it is not already open."""
        if self._sock is not None:
            return

        try:
            sock = socket.create_connection(
                (self.host, self.port),
                timeout=self.timeout,
            )
            sock.settimeout(self.timeout)
            self._sock = sock

        except TimeoutError:
            raise SystemExit(
                f"PLC not found at {self.host}:{self.port}. "
                "Check the IP address, PLC power, and network cabling."
            ) from None

        except ConnectionRefusedError:
            raise SystemExit(
                f"PLC connection refused at {self.host}:{self.port}. "
                "Check that maintenance communication is enabled."
            ) from None

        except OSError as exc:
            raise SystemExit(
                f"Unable to connect to PLC at {self.host}:{self.port}: {exc}"
            ) from None   
  

    def close(self) -> None:
        """Close the TCP connection."""
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    disconnect = close

    def reconnect(self) -> None:
        """Force a clean reconnect."""
        self.close()
        self.connect()

    def __enter__(self) -> "MiSmTCP":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
    # ------------
    # Framing / transport
    # ------------

    def _frame_req(self, cont: str, cmd: str, dtype: str, payload: bytes, include_enq: bool) -> bytes:
        if cont not in ("0", "1"):
            raise ValueError("cont must be '0' or '1'")
        if len(cmd) != 1 or len(dtype) != 1:
            raise ValueError("cmd and dtype must be 1 character each")

        body = (
            self.device.encode("ascii")
            + cont.encode("ascii")
            + cmd.encode("ascii")
            + dtype.encode("ascii")
            + payload
        )

        if include_enq:
            bcc = _xor_bcc(b"\x05" + body)
        else:
            bcc = _xor_bcc(body)

        framed = b"\x05" + body + _to_ascii_hex_byte(bcc) + b"\r"

        if self.debug:
            try:
                print("TX(ascii):", body.decode("ascii"))
            except Exception:
                pass
            print("TX(hex):  ", framed.hex())

        return framed

    def _recv_until_cr(self, sock: socket.socket, limit: int = 8192) -> bytes:
        """Receive bytes until CR, timeout, close, or limit."""
        buf = bytearray()
        start = time.time()
        while len(buf) < limit:
            try:
                chunk = sock.recv(1)
            except socket.timeout:
                break

            if not chunk:
                break

            buf.extend(chunk)
            if chunk == b"\r":
                break

            if time.time() - start > (self.timeout * 3):
                break

        return bytes(buf)

    def _send_recv(self, req: bytes) -> bytes:
        """Send one framed request and return one CR-terminated reply."""
        if self.keep_open:
            self.connect()
            assert self._sock is not None
            try:
                self._sock.sendall(req)
                return self._recv_until_cr(self._sock)
            except (OSError, socket.timeout):
                # A stale PLC socket is common after cable changes, power cycles, etc.
                # Reconnect once and retry the same request.
                self.reconnect()
                assert self._sock is not None
                self._sock.sendall(req)
                return self._recv_until_cr(self._sock)

        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(req)
            return self._recv_until_cr(sock)

    def _xfer_once(self, cont: str, cmd: str, dtype: str, payload: bytes, include_enq: bool) -> Reply:
        req = self._frame_req(cont, cmd, dtype, payload, include_enq=include_enq)
        raw = self._send_recv(req)

        if self.debug:
            print("RX(hex):  ", raw.hex())

        rep = _parse_reply(raw)

        # If it's an ACK/NAK but reply BCC is wrong, treat as hard error.
        if rep.kind in ("ACK_OK", "ACK_NG", "NAK") and not rep.bcc_ok:
            raise IOError(
                f"Reply BCC mismatch: recv={rep.bcc_recv:02X} calc={rep.bcc_calc:02X} raw={raw.hex()}"
            )
        return rep

    def _xfer(self, cont: str, cmd: str, dtype: str, payload: bytes = b"") -> Reply:
        """
        Sends request using selected BCC mode.
        In 'auto' mode:
          - try include_enq=True first (matches your working read capture)
          - if NAK code '10', retry include_enq=False
          - if retry ACK_OK, lock to that mode for session
        """
        if self.bcc_mode == "enq":
            return self._xfer_once(cont, cmd, dtype, payload, include_enq=True)
        if self.bcc_mode == "no_enq":
            return self._xfer_once(cont, cmd, dtype, payload, include_enq=False)

        # auto
        rep = self._xfer_once(cont, cmd, dtype, payload, include_enq=True)
        if rep.kind == "NAK" and rep.nak_code == "10":
            rep2 = self._xfer_once(cont, cmd, dtype, payload, include_enq=False)
            if rep2.kind == "ACK_OK":
                self.bcc_mode = "no_enq"
            return rep2

        if rep.kind == "ACK_OK":
            self.bcc_mode = "enq"
        return rep

    def _raise_if_err(self, rep: Reply) -> None:
        if rep.kind == "NAK":
            raise IOError(f"NAK code={rep.nak_code} raw={rep.raw.hex()}")
        if rep.kind == "ACK_NG":
            raise IOError(f"ACK NG code={rep.ng_code} raw={rep.raw.hex()}")
        if rep.kind != "ACK_OK":
            raise IOError(f"Unexpected reply kind={rep.kind} raw={rep.raw.hex()}")

    # -------------------------
    # Word read/write
    # -------------------------

    def write(self, addr: Union[str, int], value: int, endian: int = 0, dtype: Optional[str] = None) -> int:
        """
        Write a 16-bit word using Write N Bytes (n=2).

        Dotted word-bit addresses are routed to write_bit():
          write("D0100", 1234)    -> writes the whole D0100 word
          write("D0100.0", 1)     -> sets bit 0 of D0100
          write("D0100.00", 1)    -> same as D0100.0
          write("D0100.15", 0)    -> clears bit 15 of D0100

        Returns written value masked to 16-bit for word writes, or 0/1 for bit writes.
        """
        if isinstance(addr, str) and "." in addr:
            return self.write_bit(addr, value)

        dt, op = _parse_addr(addr, dtype=dtype)
        dt = _dtype_for_nbyte(dt)

        w = value & 0xFFFF
        payload = _pad4(op).encode("ascii") + b"02" + f"{w:04X}".encode("ascii")

        rep = self._xfer("0", "W", dt, payload)
        self._raise_if_err(rep)
        return w

    def read(self, addr: Union[str, int], endian: int = 0, dtype: Optional[str] = None) -> int:
        """
        Read a 16-bit word using Read N Bytes (n=2).

        Dotted word-bit addresses are routed to read_bit():
          read("D0100")       -> reads the whole D0100 word
          read("D0100.0")     -> reads bit 0 of D0100
          read("D0100.00")    -> same as D0100.0
          read("D0100.15")    -> reads bit 15 of D0100

        Returns 0..65535 for word reads, or 0/1 for bit reads.
        """
        if isinstance(addr, str) and "." in addr:
            return self.read_bit(addr)

        dt, op = _parse_addr(addr, dtype=dtype)
        dt = _dtype_for_nbyte(dt)

        payload = _pad4(op).encode("ascii") + b"02"

        rep = self._xfer("0", "R", dt, payload)
        self._raise_if_err(rep)

        if len(rep.data) != 4 or not _is_hex_ascii(rep.data):
            raise IOError(f"Unexpected word payload: {rep.data!r}")
        return int(rep.data.decode("ascii"), 16)

    # -------------------------
    # Bit read/write (keeps your positional calls working)
    # -------------------------

    def write_bit(self, addr: Union[str, int], on: int, endian: int = 0, dtype: Optional[str] = None) -> int:
        """
        Write 1 bit. Compatible with calls like write_bit("Y0000", 1, 0).
        """
        # --- Q/I convenience aliases ---
        if isinstance(addr, str) and "." not in addr:
            s = addr.strip().upper()

            if s.startswith("Q") and s[1:].isdigit():
                addr = f"Y{int(s[1:]):04d}"

            elif s.startswith("I") and s[1:].isdigit():
                addr = f"X{int(s[1:]):04d}"

        # --- support word.bit syntax ---
        if isinstance(addr, str) and "." in addr:
            base, bit = addr.split(".")
            bit = int(bit)

            if bit < 0 or bit > 15:
                raise ValueError("bit must be 0..15")

            v = self.read(base)

            if on:
                v |= (1 << bit)
            else:
                v &= ~(1 << bit)

            self.write(base, v)
            return 1 if int(on) else 0
        # --------------------------------

        dt, op = _parse_addr(addr, dtype=dtype)
        bit_dt = _dtype_for_bit(dt.upper())

        status = b"1" if int(on) else b"0"
        payload = _pad4(op).encode("ascii") + status

        rep = self._xfer("0", "W", bit_dt, payload)
        self._raise_if_err(rep)
        return 1 if int(on) else 0

    def read_bit(self, addr: Union[str, int], endian: int = 0, dtype: Optional[str] = None) -> int:
        """
        Read 1 bit explicitly.

        Prefer read("D0100.03") for bits inside word devices such as D registers.
        Use read_bit() for special/native bit devices such as M, X, Y, and R:
          read_bit("M8070")
          read_bit("X0000")
          read_bit("Y0007")
          read_bit("M8004.15")

        Dotted bit numbers may be padded or unpadded:
          D0100.1 == D0100.01
          D0100.0 == D0100.00
        """
        # --- Q/I convenience aliases ---
        if isinstance(addr, str) and "." not in addr:
            s = addr.strip().upper()

            if s.startswith("Q") and s[1:].isdigit():
                addr = f"Y{int(s[1:]):04d}"

            elif s.startswith("I") and s[1:].isdigit():
                addr = f"X{int(s[1:]):04d}"
        
        # --- support word.bit syntax ---
        if isinstance(addr, str) and "." in addr:
            base, bit = addr.split(".")
            bit = int(bit)

            v = self.read(base)
            return 1 if (v & (1 << bit)) else 0
        # --------------------------------        
        dt, op = _parse_addr(addr, dtype=dtype)
        bit_dt = _dtype_for_bit(dt.upper())

        payload = _pad4(op).encode("ascii")

        rep = self._xfer("0", "R", bit_dt, payload)
        self._raise_if_err(rep)

        if len(rep.data) != 1 or rep.data not in (b"0", b"1"):
            raise IOError(f"Unexpected bit payload: {rep.data!r}")
        return 1 if rep.data == b"1" else 0

    # -------------------------
    # Simple enumerable I/O (Q/I aliases)
    # -------------------------

    def output(self, bit: Union[str, int], on: int = 1) -> int:
        """
        Output write helper matching your exact examples:

          Q0 ON  -> FF0Wy00001 + BCC + CR
          Q0 OFF -> FF0Wy00000 + BCC + CR
          Q7 ON  -> FF0Wy00071 + BCC + CR

        NOTE: This is NOT the same payload shape as write_bit(Yxxxx),
              it is the exact 5-char payload you showed.
        """
        _, b = _parse_io(bit, is_out=True)
        v = 1 if int(on) else 0

        # EXACT payload: 4-digit operand + 1-digit value, e.g. "00001"
        payload = f"{b:04d}{v}".encode("ascii")

        rep = self._xfer("0", "W", "y", payload)
        self._raise_if_err(rep)
        return v

    def input(self, bit: Union[str, int]) -> int:
        """
        Input read helper (I -> X).
        """
        _, b = _parse_io(bit, is_out=False)
        return self.read_bit(b, 0, dtype="X")

    # -------------------------
    # Timer / Counter / Error
    # -------------------------

    def read_timer(self, tnum: int, count: int = 1) -> List[Dict[str, Any]]:
        """
        Read Timer Information (dtype '_').
        Returns: [{"timer":n,"current":int,"preset":int,"status":int}, ...]
        Payload: operand(4 digits) + count(2 hex ASCII)
        Reply:   10*count ASCII hex chars: current(4) + preset(4) + status(2)
        """
        if count < 1 or count > 48:
            raise ValueError("count must be 1..48")

        payload = _pad4(tnum).encode("ascii") + f"{count:02X}".encode("ascii")

        rep = self._xfer("0", "R", "_", payload)
        self._raise_if_err(rep)

        expected = 10 * count
        if len(rep.data) != expected or not _is_hex_ascii(rep.data):
            raise IOError(f"Unexpected timer payload len={len(rep.data)} data={rep.data!r}")

        out: List[Dict[str, Any]] = []
        for i in range(count):
            block = rep.data[i * 10:(i + 1) * 10]
            cur = int(block[0:4].decode("ascii"), 16)
            pre = int(block[4:8].decode("ascii"), 16)
            st = int(block[8:10].decode("ascii"), 16)
            out.append({"timer": tnum + i, "current": cur, "preset": pre, "status": st})
        return out

    def write_timer(self, tnum: int, value: int, preset: Optional[int] = None) -> int:
        """
        Write timer current/present value by default.

        If preset is provided, also write the timer preset value.

        Examples:
            plc.write_timer(0, 150)
                -> T0000 current/present value = 150

            plc.write_timer(0, 150, preset=300)
                -> T0000 current/present value = 150
                -> T0000 preset value = 300
        """
        if tnum < 0 or tnum > 9999:
            raise ValueError("timer number must be 0..9999")

        if value < 0 or value > 0xFFFF:
            raise ValueError("timer current value must be 0..65535")

        if preset is not None:
            if preset < 0 or preset > 0xFFFF:
                raise ValueError("timer preset value must be 0..65535")

            self.write(tnum, preset, dtype="T")

        return self.write(tnum, value, dtype="t")

    def write_counter(self, cnum: int, preset: int) -> int:
        """
        Convenience: write counter preset (Cxxxx) using 16-bit word write.
        """
        return self.write(cnum, preset, dtype="C")

    def read_error(self, addr: int = 0, nbytes: int = 12) -> List[int]:
        """
        Read Error Code (dtype 'E').
        payload: operand(4) + nbytes(2 hex ASCII)
        reply:   4*(nbytes/2) ASCII hex chars (each slot = 1 word)
        """
        if nbytes < 2 or nbytes > 12 or (nbytes % 2) != 0:
            raise ValueError("nbytes must be even, 2..12")

        payload = _pad4(addr).encode("ascii") + f"{nbytes:02X}".encode("ascii")

        rep = self._xfer("0", "R", "E", payload)
        self._raise_if_err(rep)

        n = nbytes // 2
        expected = 4 * n
        if len(rep.data) != expected or not _is_hex_ascii(rep.data):
            raise IOError(f"Unexpected error payload len={len(rep.data)} data={rep.data!r}")

        vals: List[int] = []
        for i in range(n):
            vals.append(int(rep.data[i * 4:(i + 1) * 4].decode("ascii"), 16))
        return vals
    # -------------------------
    # Blocks of data 
    # -------------------------
    
    def read_block(self, addr, count=2, endian=0, dtype=None):
        """
        Read count 16-bit registers as a list of words.
        endian:
          0 = normal PLC/order-as-returned
          1 = reversed word order
        """
        if count < 1 or count > 127:
            raise ValueError("count must be 1..127 registers")

        dt, op = _parse_addr(addr, dtype=dtype)
        dt = _dtype_for_nbyte(dt)

        nbytes = count * 2
        payload = _pad4(op).encode("ascii") + f"{nbytes:02X}".encode("ascii")

        rep = self._xfer("0", "R", dt, payload)
        self._raise_if_err(rep)

        expected = count * 4
        if len(rep.data) != expected or not _is_hex_ascii(rep.data):
            raise IOError(f"Unexpected block payload: {rep.data!r}")

        words = [
            int(rep.data[i:i + 4].decode("ascii"), 16)
            for i in range(0, expected, 4)
        ]

        if endian == 1:
            words.reverse()
        elif endian != 0:
            raise ValueError("endian must be 0 or 1")

        return words

    def write_block(self, addr, values, endian=0, dtype=None):
        """
        Write a list of 16-bit register values.
        """
        if not values:
            raise ValueError("values must not be empty")
        if len(values) > 127:
            raise ValueError("too many registers")

        #words = [int(v) & 0xFFFF for v in values]
        original_words = [int(v) & 0xFFFF for v in values]
        words = list(original_words)
        if endian == 1:
            words = list(reversed(words))
        elif endian != 0:
            raise ValueError("endian must be 0 or 1")

        dt, op = _parse_addr(addr, dtype=dtype)
        dt = _dtype_for_nbyte(dt)

        data_ascii = "".join(f"{w:04X}" for w in words).encode("ascii")
        nbytes = len(words) * 2
        payload = _pad4(op).encode("ascii") + f"{nbytes:02X}".encode("ascii") + data_ascii

        rep = self._xfer("0", "W", dt, payload)
        self._raise_if_err(rep)
        return original_words    
    
    # -------------------------
    # block-o-register helpers
    # -------------------------

    def read_uint(self, addr, count=2, endian=0, dtype=None):
        words = self.read_block(addr, count=count, endian=endian, dtype=dtype)

        value = 0
        for w in words:
            value = (value << 16) | w

        return value

    def write_uint(self, addr, value, count=2, endian=0, dtype=None):
        if count < 1 or count > 127:
            raise ValueError("count must be 1 .. 127 registers")
        
        if value < 0 or value >= (1 << (16 * count)):
            raise ValueError(f"value does not fit in {count} registers")

        words = []
        for shift in range((count - 1) * 16, -1, -16):
            words.append((value >> shift) & 0xFFFF)

        return self.write_block(addr, words, endian=endian, dtype=dtype)


    # -------------------------
    # Float helpers (2 regs)
    # -------------------------

    def read_float(self, addr: Union[str, int], endian: int = 0, dtype: Optional[str] = None) -> float:
        """
        Read IEEE-754 float from 2 successive registers (4 bytes).
        Uses Read N Bytes with n=4 (8 ASCII hex).
        endian:
          0 = little word-order  (low word at addr, high word at addr+1)
          1 = big word-order     (high word at addr, low word at addr+1)
        """
        dt, op = _parse_addr(addr, dtype=dtype)
        dt = _dtype_for_nbyte(dt)

        payload = _pad4(op).encode("ascii") + b"04"

        rep = self._xfer("0", "R", dt, payload)
        self._raise_if_err(rep)

        if len(rep.data) != 8 or not _is_hex_ascii(rep.data):
            raise IOError(f"Unexpected float payload: {rep.data!r}")

        w0 = int(rep.data[0:4].decode("ascii"), 16)
        w1 = int(rep.data[4:8].decode("ascii"), 16)

        if endian == 0:
            low, high = w0, w1
        elif endian == 1:
            high, low = w0, w1
        else:
            raise ValueError("endian must be 0 (little) or 1 (big)")

        b = struct.pack(">HH", high, low)
        val = struct.unpack(">f", b)[0]
        #return round(val, PRECISION)
        return round(val, self.precision)
        #return struct.unpack(">f", b)[0]

    def write_float(self, addr: Union[str, int], value: float, endian: int = 0, dtype: Optional[str] = None) -> float:
        """
        Write IEEE-754 float into 2 successive registers.
        Uses Write N Bytes with n=4.
        endian word-order as in read_float().
        """
        dt, op = _parse_addr(addr, dtype=dtype)
        dt = _dtype_for_nbyte(dt)

        b = struct.pack(">f", float(value))
        high, low = struct.unpack(">HH", b)

        if endian == 0:
            w0, w1 = low, high
        elif endian == 1:
            w0, w1 = high, low
        else:
            raise ValueError("endian must be 0 (little) or 1 (big)")

        data_ascii = f"{w0:04X}{w1:04X}".encode("ascii")
        payload = _pad4(op).encode("ascii") + b"04" + data_ascii

        rep = self._xfer("0", "W", dt, payload)
        self._raise_if_err(rep)
        return float(value)

    # -------------------------
    # Forced I/O 
    # -------------------------

    def force_io(self, enable: bool = True) -> int:
        """
        Enable or disable/suspend IDEC Force I/O mode.

        Capture-derived maintenance protocol frames:
          enable  -> W O 1
          disable -> W O 0

        Returns 1 when enabled, 0 when disabled.
        """
        v = 1 if bool(enable) else 0
        rep = self._xfer("0", "W", "O", str(v).encode("ascii"))
        self._raise_if_err(rep)
        return v

    def force(self, bit: Union[str, int], on: int = 1) -> int:
        """Force one physical output Q0..Q7 ON/OFF."""
        _, b = _parse_io(bit, is_out=True)
        if b < 0 or b > 7:
            raise ValueError("force currently supports Q0..Q7 only")

        v = 1 if int(on) else 0

        self.force_io(True)

        rep = self._xfer("0", "W", "]", f"{b:04d}{v}".encode("ascii"))
        self._raise_if_err(rep)

        rep = self._xfer("0", "W", "^", f"{b:04d}1".encode("ascii"))
        self._raise_if_err(rep)

        return v

    #def release_force(self, bit: Union[str, int]) -> int:
    def release_force(self) -> int:
        """Release Force control."""        	
        return self.force_io(False)

    # Short aliases
    force_output = force
    force_release = release_force

    # -------------------------
    # Upload: plc to pc.
    # -------------------------

    def upload(self, filename=None):
        """
        Upload PLC program image.

        Returns:
            bytes
        """

        # Try upload start
        try:
            self._upload_begin()

        except PLCPasswordRequired:
            import getpass

            pw = getpass.getpass("PLC upload password: ")

            if not self._unlock_upload(pw):
                raise IOError("Incorrect PLC password")

            self._upload_begin()

        blocks = []

        while True:
            chunk, done = self._upload_next_block()

            blocks.append(chunk)

            if done:
                break

        blob = b"".join(blocks)

        if filename:
            with open(filename, "wb") as f:
                f.write(blob)

        return blob

    ## checksum the PLC program
    def upload_sha256(self):
        import hashlib
        return hashlib.sha256(self.upload()).hexdigest()

# -------------------------
# Optional module-level wrappers
# -------------------------

def input(plc: MiSmTCP, bit: Union[str, int]) -> int:
    return plc.input(bit)


def output(plc: MiSmTCP, bit: Union[str, int], on: int = 1) -> int:
    return plc.output(bit, on)

"""
# -------------------------
if __name__ == "__main__":
    # Example: your test sequence
    plc = MiSmTCP("192.168.1.5", device="FF", debug=True, bcc_mode="auto")

    from time import sleep
    v = plc.read_bit("M8004.01")   # second arg accepted/ignored for compatibility
    print(v)
    v = plc.read("M8004")   # second arg accepted/ignored for compatibility
    print(v)

    plc.write_bit("M8004.15", 0)
    plc.write_timer(420, 100)            # set current time to 100 on t0420
    plc.write_timer(421, 100, preset=30) # set current time to 100 on t0421 with a preset of 100
    v = plc.read_bit("M8004.15")   # second arg accepted/ignored for compatibility
    print(v)

    for i in range(0,8):
        plc.output(i,1)
        sleep(1)
    for i in range(0,8):
        plc.output(i,0)
        sleep(1)
    plc.close()

"""


# Backward-friendly aliases.
PLC = MiSmTCP
Client = MiSmTCP
