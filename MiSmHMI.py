#!/usr/bin/env python3
"""
MiSmHMI - standalone IDEC HMI Maintenance Protocol server/emulator.

The HMI is the TCP client.  MiSmHMI listens on TCP port 2101 and presents a
small PLC-like register image to the panel.  It is based on the command shapes
observed in fc6a/dev/HMI/hmi_reg.py and its captured request lists, rather than
on an IDEC HMI protocol manual.

Supported observed commands:
    RD  Read D words (decimal address)
    RM  Read M bits (ASCII 0/1 collection)
    RA  Read extended D words (hexadecimal address)
    R_  Read timer current values
    WA  Write extended D words (hexadecimal address)
    WD  Write D words
    WM  Write an M bit collection
    Wm  Write one M bit
    Rl  Read a collection of bits

The public memory API intentionally resembles MiSmTCP / MiSmSerial:
    hmi.read("D0100")
    hmi.write("D0100", 123)
    hmi.read_bit("M0500")
    hmi.write_bit("M0500", 1)
    hmi.read_block("D0100", 4)
    hmi.write_block("D0100", [1, 2, 3, 4])
    hmi.read_float("D0100")
    hmi.write_float("D0100", 12.5)

Standard-library only. Extended functionality not included. 
"""
from __future__ import annotations

from dataclasses import dataclass
import socket
import struct
import threading
from typing import Callable, Dict, Iterable, List, Optional, Tuple, Union

HMI_PORT = 2101
DEFAULT_DEVICE = "00"
Address = Union[str, int]


def _xor_bcc(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
    return value & 0xFF


def _frame_hex(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)


def _parse_address(addr: Address, dtype: Optional[str] = None) -> Tuple[str, int, Optional[int]]:
    if isinstance(addr, int):
        if dtype is None or len(dtype) != 1:
            raise ValueError("dtype is required when addr is an integer")
        return dtype.upper(), addr, None

    text = str(addr).strip()
    if len(text) < 2:
        raise ValueError("address must look like D0100, M0500, T0000, or D0100.3")
    area = text[0].upper()
    rest = text[1:]
    bit = None
    if "." in rest:
        rest, bit_text = rest.split(".", 1)
        if not bit_text.isdigit():
            raise ValueError("bit index must be numeric")
        bit = int(bit_text)
        if not 0 <= bit <= 15:
            raise ValueError("bit index must be 0..15")
    if not rest.isdigit():
        raise ValueError("numeric address portion must contain decimal digits")
    return area, int(rest), bit


def _check_word(value: int) -> int:
    value = int(value)
    if not 0 <= value <= 0xFFFF:
        raise ValueError("word value must be 0..65535")
    return value


@dataclass(frozen=True)
class HMIRequest:
    raw: bytes
    device: str
    continuation: str
    command: str
    payload: str
    bcc_received: int
    bcc_with_enq: int
    bcc_without_enq: int
    bcc_ok: bool
    bcc_mode: str


class MiSmHMI:
    """Thread-safe register image plus TCP Maintenance Protocol server."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = HMI_PORT,
        device: str = DEFAULT_DEVICE,
        timeout: float = 0.5,
        debug: bool = False,
        bcc_mode: str = "auto",
        strict_device: bool = False,
        rl_base: int = 0,
    ):
        if len(device) != 2:
            raise ValueError("device must be two ASCII characters")
        if bcc_mode not in ("auto", "enq", "no_enq", "ignore"):
            raise ValueError("bcc_mode must be auto, enq, no_enq, or ignore")
        self.host = host
        self.port = int(port)
        self.device = device.upper()
        self.timeout = float(timeout)
        self.debug = bool(debug)
        self.bcc_mode = bcc_mode
        self.strict_device = bool(strict_device)
        self.rl_base = int(rl_base)

        self._words: Dict[str, Dict[int, int]] = {"D": {}, "T": {}, "A": {}}
        self._bits: Dict[str, Dict[int, int]] = {"M": {}, "L": {}}
        self._lock = threading.RLock()
        self._server: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._clients: set[socket.socket] = set()
        self._handlers: Dict[str, Callable[[HMIRequest], bytes]] = {}
        self.on_request: Optional[Callable[[HMIRequest], None]] = None
        self.on_write: Optional[Callable[[str, int, object], None]] = None

    # ---------- public memory API ----------
    def read(self, addr: Address, endian: int = 0, dtype: Optional[str] = None) -> int:
        area, number, bit = _parse_address(addr, dtype)
        if bit is not None:
            word = self.read(f"{area}{number}")
            return 1 if word & (1 << bit) else 0
        if area in self._bits:
            return self.read_bit(number, dtype=area)
        with self._lock:
            return self._words.setdefault(area, {}).get(number, 0)

    def write(self, addr: Address, value: int, endian: int = 0, dtype: Optional[str] = None) -> int:
        area, number, bit = _parse_address(addr, dtype)
        if bit is not None:
            word = self.read(f"{area}{number}")
            if int(value):
                word |= 1 << bit
            else:
                word &= ~(1 << bit)
            return self.write(f"{area}{number}", word)
        if area in self._bits:
            return self.write_bit(number, value, dtype=area)
        value = _check_word(value)
        with self._lock:
            self._words.setdefault(area, {})[number] = value
        self._emit_write(area, number, value)
        return value

    def read_bit(self, addr: Address, endian: int = 0, dtype: Optional[str] = None) -> int:
        area, number, bit = _parse_address(addr, dtype)
        if bit is not None:
            return self.read(addr)
        area = "L" if area.lower() == "l" else area
        with self._lock:
            return 1 if self._bits.setdefault(area, {}).get(number, 0) else 0

    def write_bit(self, addr: Address, on: int, endian: int = 0, dtype: Optional[str] = None) -> int:
        area, number, bit = _parse_address(addr, dtype)
        if bit is not None:
            return self.write(addr, on)
        area = "L" if area.lower() == "l" else area
        value = 1 if int(on) else 0
        with self._lock:
            self._bits.setdefault(area, {})[number] = value
        self._emit_write(area, number, value)
        return value

    def read_block(self, addr: Address, count: int = 2, endian: int = 0, dtype: Optional[str] = None) -> List[int]:
        if count < 1:
            raise ValueError("count must be at least 1")
        area, number, bit = _parse_address(addr, dtype)
        if bit is not None:
            raise ValueError("read_block does not accept a dotted bit address")
        values = [self.read(number + offset, dtype=area) for offset in range(count)]
        if endian == 1:
            values.reverse()
        elif endian != 0:
            raise ValueError("endian must be 0 or 1")
        return values

    def write_block(self, addr: Address, values: Iterable[int], endian: int = 0, dtype: Optional[str] = None) -> List[int]:
        area, number, bit = _parse_address(addr, dtype)
        if bit is not None:
            raise ValueError("write_block does not accept a dotted bit address")
        original = [_check_word(v) for v in values]
        ordered = list(reversed(original)) if endian == 1 else list(original)
        if endian not in (0, 1):
            raise ValueError("endian must be 0 or 1")
        for offset, value in enumerate(ordered):
            self.write(number + offset, value, dtype=area)
        return original

    def read_float(self, addr: Address, endian: int = 0, dtype: Optional[str] = None) -> float:
        words = self.read_block(addr, 2, endian=0, dtype=dtype)
        if endian == 0:
            low, high = words
        elif endian == 1:
            high, low = words
        else:
            raise ValueError("endian must be 0 or 1")
        return struct.unpack(">f", struct.pack(">HH", high, low))[0]

    def write_float(self, addr: Address, value: float, endian: int = 0, dtype: Optional[str] = None) -> float:
        high, low = struct.unpack(">HH", struct.pack(">f", float(value)))
        words = [low, high] if endian == 0 else [high, low]
        if endian not in (0, 1):
            raise ValueError("endian must be 0 or 1")
        self.write_block(addr, words, dtype=dtype)
        return float(value)

    def read_timer(self, tnum: int, count: int = 1) -> List[dict]:
        return [
            {"timer": tnum + i, "current": self.read(tnum + i, dtype="T"), "preset": 0, "status": 0}
            for i in range(count)
        ]

    def write_timer(self, tnum: int, value: int, preset: Optional[int] = None) -> int:
        # The observed HMI R_ request only exposes the current-value collection.
        return self.write(tnum, value, dtype="T")

    def set_bits(self, addr: Address, values: Iterable[int], dtype: Optional[str] = None) -> List[int]:
        area, number, bit = _parse_address(addr, dtype)
        if bit is not None:
            raise ValueError("set_bits does not accept a dotted address")
        result = [1 if int(v) else 0 for v in values]
        for offset, value in enumerate(result):
            self.write_bit(number + offset, value, dtype=area)
        return result

    def get_bits(self, addr: Address, count: int, dtype: Optional[str] = None) -> List[int]:
        area, number, bit = _parse_address(addr, dtype)
        if bit is not None:
            raise ValueError("get_bits does not accept a dotted address")
        return [self.read_bit(number + offset, dtype=area) for offset in range(count)]

    def register_handler(self, command: str, handler: Callable[[HMIRequest], bytes]) -> None:
        if len(command) != 2:
            raise ValueError("command must contain exactly two characters")
        self._handlers[command] = handler

    # ---------- server lifecycle ----------
    @property
    def running(self) -> bool:
        return self._server is not None and not self._stop.is_set()

    def start(self, daemon: bool = True) -> "MiSmHMI":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self.serve_forever, name="MiSmHMI", daemon=daemon)
        self._thread.start()
        return self

    def serve_forever(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(4)
        server.settimeout(self.timeout)
        self._server = server
        if self.debug:
            print(f"MiSmHMI listening on {self.host}:{self.port}")
        try:
            while not self._stop.is_set():
                try:
                    client, peer = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                client.settimeout(self.timeout)
                with self._lock:
                    self._clients.add(client)
                thread = threading.Thread(target=self._client_loop, args=(client, peer), daemon=True)
                thread.start()
        finally:
            self._server = None
            try:
                server.close()
            except OSError:
                pass

    def close(self) -> None:
        self._stop.set()
        server, self._server = self._server, None
        if server is not None:
            try:
                server.close()
            except OSError:
                pass
        with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=max(1.0, self.timeout * 3))

    stop = close
    disconnect = close

    def __enter__(self) -> "MiSmHMI":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ---------- protocol ----------
    def parse_request(self, frame: bytes) -> HMIRequest:
        if len(frame) < 9 or frame[0] != 0x05 or not frame.endswith(b"\r"):
            raise ValueError("malformed request frame")
        body = frame[:-3]
        try:
            received = int(frame[-3:-1].decode("ascii"), 16)
            device = frame[1:3].decode("ascii")
            continuation = chr(frame[3])
            command = frame[4:6].decode("ascii")
            payload = frame[6:-3].decode("ascii")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("request contains invalid ASCII fields") from exc
        with_enq = _xor_bcc(body)
        without_enq = _xor_bcc(body[1:])
        if self.bcc_mode == "enq":
            ok, mode = received == with_enq, "enq"
        elif self.bcc_mode == "no_enq":
            ok, mode = received == without_enq, "no_enq"
        elif self.bcc_mode == "ignore":
            ok, mode = True, "ignore"
        else:
            ok = received in (with_enq, without_enq)
            mode = "enq" if received == with_enq else "no_enq" if received == without_enq else "invalid"
        return HMIRequest(frame, device, continuation, command, payload, received, with_enq, without_enq, ok, mode)

    def handle_request(self, request: HMIRequest) -> bytes:
        if not request.bcc_ok:
            return self._nak(request.device, "00")
        if self.strict_device and request.device not in (self.device, "FF"):
            return self._nak(request.device, "03")
        if self.on_request:
            self.on_request(request)
        if request.command in self._handlers:
            return self._handlers[request.command](request)
        handler = getattr(self, f"_cmd_{request.command}", None)
        if handler is None:
            return self._nak(request.device, "03")
        try:
            return handler(request)
        except (ValueError, IndexError):
            return self._nak(request.device, "04")

    def _client_loop(self, client: socket.socket, peer) -> None:
        if self.debug:
            print(f"HMI connected: {peer}")
        buffer = bytearray()
        try:
            while not self._stop.is_set():
                try:
                    chunk = client.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buffer.extend(chunk)
                while b"\r" in buffer:
                    index = buffer.index(0x0D)
                    frame = bytes(buffer[: index + 1])
                    del buffer[: index + 1]
                    if self.debug:
                        print("RX HEX:", _frame_hex(frame))
                        print("RX ASCII:", repr(frame))
                    try:
                        request = self.parse_request(frame)
                        reply = self.handle_request(request)
                    except ValueError:
                        reply = self._nak(self.device, "04")
                    if self.debug:
                        print("TX HEX:", _frame_hex(reply))
                        print("TX ASCII:", repr(reply))
                    client.sendall(reply)
        except (ConnectionError, OSError):
            pass
        finally:
            with self._lock:
                self._clients.discard(client)
            try:
                client.close()
            except OSError:
                pass
            if self.debug:
                print(f"HMI disconnected: {peer}")

    def _reply(self, device: str, data: bytes = b"", command: bytes = b"0") -> bytes:
        body = b"\x06" + device.encode("ascii") + command + data
        return body + f"{_xor_bcc(body):02X}".encode("ascii") + b"\r"

    def _nak(self, device: str, code: str) -> bytes:
        body = b"\x15" + device.encode("ascii") + b"0" + code.encode("ascii")
        return body + f"{_xor_bcc(body):02X}".encode("ascii") + b"\r"

    @staticmethod
    def _selector(payload: str, address_base: int = 10) -> Tuple[int, int, str]:
        if len(payload) < 6:
            raise ValueError("payload needs address(4) plus byte count(2)")
        address = int(payload[:4], address_base)
        nbytes = int(payload[4:6], 16)
        return address, nbytes, payload[6:]

    def _cmd_RD(self, request: HMIRequest) -> bytes:
        address, nbytes, _ = self._selector(request.payload)
        count = (nbytes + 1) // 2
        data = "".join(f"{self.read(address + i, dtype='D'):04X}" for i in range(count))
        return self._reply(request.device, data[: nbytes * 2].encode("ascii"))

    def _cmd_WD(self, request: HMIRequest) -> bytes:
        address, nbytes, data = self._selector(request.payload)
        self._write_word_ascii("D", address, nbytes, data)
        return self._reply(request.device)

    def _cmd_RA(self, request: HMIRequest) -> bytes:
        address, nbytes, _ = self._selector(request.payload, 16)
        count = (nbytes + 1) // 2
        data = "".join(f"{self.read(address + i, dtype='D'):04X}" for i in range(count))
        return self._reply(request.device, data[: nbytes * 2].encode("ascii"))

    def _cmd_WA(self, request: HMIRequest) -> bytes:
        address, nbytes, data = self._selector(request.payload, 16)
        self._write_word_ascii("D", address, nbytes, data)
        return self._reply(request.device)

    def _cmd_R_(self, request: HMIRequest) -> bytes:
        address, count, _ = self._selector(request.payload)
        data = "".join(f"{self.read(address + i, dtype='T'):04X}" for i in range(count))
        return self._reply(request.device, data.encode("ascii"))

    def _cmd_RM(self, request: HMIRequest) -> bytes:
        address, nbytes, _ = self._selector(request.payload)
        # This differs from the older PLC manual: observed HMI emulation requires
        # one ASCII 0/1 character per bit, i.e. nbytes * 8 reply characters.
        bits = self.get_bits(address, nbytes * 8, dtype="M")
        return self._reply(request.device, "".join(map(str, bits)).encode("ascii"))

    def _cmd_WM(self, request: HMIRequest) -> bytes:
        address, nbytes, data = self._selector(request.payload)
        bit_count = nbytes * 8
        bits = self._decode_bit_collection(data, bit_count)
        self.set_bits(address, bits, dtype="M")
        return self._reply(request.device)

    def _cmd_Wm(self, request: HMIRequest) -> bytes:
        if len(request.payload) < 5:
            raise ValueError("Wm payload needs address and state")
        address = int(request.payload[:4], 10)
        state = request.payload[4]
        if state not in "01":
            raise ValueError("invalid bit state")
        self.write_bit(address, int(state), dtype="M")
        return self._reply(request.device)

    def _cmd_Rl(self, request: HMIRequest) -> bytes:
        address, nbytes, _ = self._selector(request.payload)
        # Rl is capture-derived and not documented.  Treat it as a collection of
        # bits, in the current interpretation.  L is a separate
        # local bit area so it cannot accidentally alias M.  rl_base can map the
        # observed address into a smaller logical range when desired.
        logical = address - self.rl_base
        bits = self.get_bits(logical, nbytes * 8, dtype="L")
        return self._reply(request.device, "".join(map(str, bits)).encode("ascii"))

    def _write_word_ascii(self, area: str, address: int, nbytes: int, data: str) -> None:
        expected = nbytes * 2
        if len(data) < expected:
            raise ValueError("not enough write data")
        if nbytes % 2:
            raise ValueError("word write byte count must be even")
        for offset in range(nbytes // 2):
            word = int(data[offset * 4 : offset * 4 + 4], 16)
            self.write(address + offset, word, dtype=area)

    @staticmethod
    def _decode_bit_collection(data: str, bit_count: int) -> List[int]:
        if len(data) >= bit_count and all(ch in "01" for ch in data[:bit_count]):
            return [int(ch) for ch in data[:bit_count]]
        needed_hex = (bit_count + 3) // 4
        if len(data) >= needed_hex:
            raw = bytes.fromhex(data[:needed_hex])
            bits: List[int] = []
            for byte in raw:
                bits.extend((byte >> bit) & 1 for bit in range(8))
            return bits[:bit_count]
        raise ValueError("unsupported bit collection encoding")

    def _emit_write(self, area: str, address: int, value: object) -> None:
        if self.on_write:
            self.on_write(area, address, value)


if __name__ == "__main__":
    hmi = MiSmHMI(debug=True)
    hmi.write("D0570", 26)
    try:
        hmi.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        hmi.close()
