#!/usr/bin/env python3
"""
MiSmSDCard - FC6A PLC SD Card helper for MiSmTCP / MiSmSerial style objects.

This module does not own the connection. It borrows an existing PLC object and
uses either:
  - plc.sd_xfer(packet) / plc._sd_xfer(packet), if you add one later
  - plc._ser for serial objects like MiSmSerial
  - plc._send_recv(packet) for persistent MiSmTCP connections
  - plc._send(packet) for simpler FC6AMaint-style TCP objects

Intended use:
    from MiSmSDCard import MiSmSDCard
    from MiSmTCP import MiSmTCP
    plc = MiSmTCP("192.168.1.50")
    plc.SD = MiSmSDCard(plc)

    print(plc.SD.checkSD())
    print(plc.SD.listSD("/FCDATA01/DATALOG/1-secLog"))
    plc.SD.deleteSD("/cap")

Implemented operations:
    checkSD()      register checks + optional extended SD status poll
    listSD(path)   directory listing based on observed DataFileManager frames
    walkSD(...)    recursively list SD card entries below path
    deleteSD(...)  delete path or file
    readSD(...)    read a PLC SD card file into bytes
    saveSD(...)    stream a PLC SD card file directly to disk

Not yet implemented:
    writeSD(...)   write files to PLC SD card path
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union
import os
import re
import socket
import time


VERSION = "2026.07.18.1"


class SDProtocolError(IOError):
    """The PLC rejected a valid SD-card protocol request."""


class SDPathNotFoundError(SDProtocolError):
    """The requested SD-card directory was not found."""


class SDTransportError(IOError):
    """The SD-card reply was missing, truncated, or otherwise unusable."""


# -------------------------
# Low-level helpers
# -------------------------


def _xor_bcc(data: bytes) -> int:
    x = 0
    for b in data:
        x ^= b
    return x & 0xFF


def _bcc_ascii(data: bytes) -> bytes:
    return f"{_xor_bcc(data):02X}".encode("ascii")


def _frame_bcc(body: bytes) -> bytes:
    """Frame with ENQ, XOR BCC including ENQ, and CR."""
    msg = b"\x05" + body
    return msg + _bcc_ascii(msg) + b"\r"


def _frame_no_bcc(body: bytes) -> bytes:
    """Frame with ENQ and CR only. Some SD entry-read frames use this."""
    return b"\x05" + body + b"\r"


def _printable(data: bytes) -> str:
    out = []
    for b in data:
        if 32 <= b <= 126:
            out.append(chr(b))
        elif b == 0x00:
            out.append("<NUL>")
        elif b == 0x05:
            out.append("<ENQ>")
        elif b == 0x06:
            out.append("<ACK>")
        elif b == 0x15:
            out.append("<NAK>")
        elif b == 0x0D:
            out.append("<CR>")
        else:
            out.append(f"<{b:02X}>")
    return "".join(out)


def _norm_path(path: Optional[str] = "/") -> str:
    if path is None or path == "":
        return "/"
    return "/" + str(path).strip("/")


def _join_path(path: str, file: Optional[str] = None) -> str:
    path = _norm_path(path)
    if not file:
        return path
    return path.rstrip("/") + "/" + str(file).strip("/")


def _body_open_dir(device: str, path: str) -> bytes:
    path = _norm_path(path)
    path_bytes = path.encode("ascii") + b"\x00"
    return device.encode("ascii") + b"1FR" + f"{len(path_bytes):03X}".encode("ascii") + path_bytes


def _body_resolve_path(device: str, path: str) -> bytes:
    # Observed notes show: FF1FR005/path
    # This is not the same path-length format as directory open.
    return device.encode("ascii") + b"1FR005" + _norm_path(path).encode("ascii")


def _body_delete_path(device: str, path: str) -> bytes:
    # Observed notes show: FF0FC005/path
    return device.encode("ascii") + b"0FC005" + _norm_path(path).encode("ascii")


@dataclass
class SDReply:
    kind: str
    raw: bytes
    device: str = ""
    command: str = ""
    data: bytes = b""
    bcc_recv: Optional[int] = None
    bcc_calc: Optional[int] = None
    bcc_ok: bool = False
    ng_code: str = ""
    nak_code: str = ""

    @property
    def ok(self) -> bool:
        return self.kind == "ACK_OK" and self.bcc_ok


def _parse_reply(raw: bytes) -> SDReply:
    if not raw:
        return SDReply(kind="EMPTY", raw=raw)
    if raw[-1:] != b"\r" or len(raw) < 6:
        return SDReply(kind="MALFORMED", raw=raw)

    ctrl = raw[0:1]
    dev = raw[1:3]
    cmd = raw[3:4]
    data = raw[4:-3]
    bcc_ascii = raw[-3:-1]

    try:
        bcc_recv = int(bcc_ascii.decode("ascii"), 16)
    except Exception:
        return SDReply(kind="MALFORMED", raw=raw)

    bcc_calc = _xor_bcc(raw[0:-3])
    bcc_ok = bcc_recv == bcc_calc

    rep = SDReply(
        kind="UNKNOWN",
        raw=raw,
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
        if rep.command == "2":
            rep.kind = "ACK_NG"
            rep.ng_code = data[:2].decode("ascii", errors="replace") if len(data) >= 2 else ""
            return rep
        rep.kind = "ACK_OK"
        return rep

    return rep


def _parse_entry(payload: bytes) -> Optional[Dict[str, Any]]:
    payload = payload.rstrip(b"\x00")

    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError:
        return None

    m = re.match(
        r"^([01])([0-9A-Fa-f]{8})([0-9]{8})([0-9]{6})([0-9A-Fa-f]{3})(.*)$",
        text,
    )
    if not m:
        return None

    kind, size_hex, date, tm, name_len_hex, name = m.groups()
    name_len = int(name_len_hex, 16)
    name = name[:name_len]

    return {
        "is_dir": kind == "1",
        "size": int(size_hex, 16),
        "date": date,
        "time": tm,
        "name": name,
        "raw": text,
    }


# -------------------------
# SD Card feature object
# -------------------------


class MiSmSDCard:
    def __init__(
        self, plc: Any, device: Optional[str] = None, timeout: float = 5.0,
        debug: Optional[bool] = None, retries: int = 3, retry_delay: float = 0.25,
    ):
        self.plc = plc
        self.device = (device or self._guess_device()).upper()
        self.timeout = timeout
        self.debug = bool(getattr(plc, "debug", False) if debug is None else debug)
        self.retries = max(int(retries), 1)
        self.retry_delay = max(float(retry_delay), 0.0)

    # ----------
    # Public API
    # ----------

    def checkSD(self, extended: bool = True) -> Dict[str, Any]:
        """
        Quick SD status check.

        Uses standard PLC devices first:
          M8070 = SD mounted/recognized
          M8071 = accessing SD card
          D8005 bit 12 = SD memory card transfer error
          D8005 bit 14 = SD memory card access error

        If extended=True, also sends observed SD status poll:
          FF0RA1F5F0220
        """
        mounted = self._safe_read_bit("M8070")
        accessing = self._safe_read_bit("M8071")
        d8005 = self._safe_read_word("D8005")

        transfer_error = bool(d8005 & (1 << 12)) if d8005 is not None else None
        access_error = bool(d8005 & (1 << 14)) if d8005 is not None else None

        out: Dict[str, Any] = {
            "mounted": mounted,
            "accessing": accessing,
            "D8005": d8005,
            "transfer_error": transfer_error,
            "access_error": access_error,
            "ok": bool(mounted) and not bool(transfer_error) and not bool(access_error),
        }

        if extended:
            try:
                packet = _frame_bcc(self.device.encode("ascii") + b"0RA1F5F0220")
                rep = self._request(packet, "sd status")
                out["extended_raw"] = rep.data.decode("ascii", errors="replace")
                out["extended_reply_ok"] = rep.ok
            except Exception as e:
                out["extended_error"] = str(e)

        return out

    def listSD(
        self, path: str = "/", retries: Optional[int] = None,
        cancel: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """List a directory, restarting after transient failures unless cancelled."""
        path = _norm_path(path)
        attempts = self.retries if retries is None else max(int(retries), 1)

        for attempt in range(1, attempts + 1):
            self._raise_if_cancelled(cancel)
            try:
                return self._list_sd_once(path, cancel)
            except SDProtocolError:
                raise
            except Exception:
                self._raise_if_cancelled(cancel)
                if attempt == attempts:
                    raise
                self._reset_transport()
                self._cancelable_delay(cancel, self.retry_delay)

        raise RuntimeError("unreachable")

    def _list_sd_once(
        self, path: str, cancel: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        packet = _frame_bcc(_body_open_dir(self.device, path))
        open_rep = self._request(packet, f"open dir {path}")
        if open_rep.kind == "ACK_NG" and open_rep.ng_code == "22":
            raise SDPathNotFoundError(
                f"Remote SD path does not exist or is not a directory: {path} "
                "(PLC code 22)"
            )
        self._raise_if_bad(open_rep)

        try:
            count = int(open_rep.data.decode("ascii"), 16)
        except Exception as exc:
            raise SDTransportError(
                f"Could not decode directory count from {open_rep.data!r}"
            ) from exc

        entries: List[Dict[str, Any]] = []
        for i in range(count):
            self._raise_if_cancelled(cancel)
            last = i == count - 1
            body = self.device.encode("ascii") + (b"0FR21" if last else b"1FR20")
            rep = self._request(_frame_no_bcc(body), f"entry {i + 1}/{count}")
            self._raise_if_bad(rep)

            entry = _parse_entry(rep.data)
            if entry is None:
                text = _printable(rep.data)
                raise SDTransportError(
                    f"Could not parse directory entry {i + 1}/{count}: {text}"
                )

            entry["path"] = path
            entries.append(entry)
            time.sleep(0.02)

        return entries

    def walkSD(self, path: str = "/") -> List[Dict[str, Any]]:
        """Recursively list SD card entries below path."""
        path = _norm_path(path)
        found: List[Dict[str, Any]] = []

        for entry in self.listSD(path):
            full_path = _join_path(path, entry["name"])
            entry = dict(entry)
            entry["full_path"] = full_path
            found.append(entry)
            print(full_path)
            if entry.get("is_dir"):
                found.extend(self.walkSD(full_path))

        return found

    def writeSD(
        self, path: str, file: Optional[str] = None,
        data: Union[str, bytes, bytearray, memoryview, None] = None,
        block_size: int = 0x400,
        progress: Optional[Callable[[int, int], None]] = None,
        encoding: str = "utf-8",
        parents: bool = False,
    ) -> int:
        """
        Write bytes or text to a PLC SD-card file.

        When parents=True, create missing parent directories first.
        """
        target = self._wire_path(_join_path(path, file))

        if data is None:
            raise ValueError("data is required")

        if parents:
            parent = target.rsplit("/", 1)[0]

            if parent:
                self.makedirsSD(parent, exist_ok=True)

        payload = data.encode(encoding) if isinstance(data, str) else bytes(data)
        return self._write_file(target, payload, block_size, progress)

    def _write_file(
        self, target: str, data: bytes, block_size: int,
        progress: Optional[Callable[[int, int], None]],
    ) -> int:
        if not 1 <= int(block_size) <= 0xFFFF:
            raise ValueError("block_size must be 1..65535")

        total = len(data)
        if total > 0xFFFFFFFF:
            raise ValueError("File is too large for the captured FD format")

        path_data = target.encode("ascii") + b"\x00"
        if len(path_data) > 0xFFF:
            raise ValueError("SD card path is too long")

        device = self.device.encode("ascii")
        body = device + b"1FD"
        body += f"{total:08X}{len(path_data):03X}".encode("ascii")
        body += path_data

        reply = self._request_write(
            _frame_bcc(body),
            f"create file {target}",
        )
        self._raise_if_bad(reply)

        if reply.command != "0":
            raise SDTransportError(
                f"Unexpected create-file acknowledgment {reply.command!r}"
            )

        if progress:
            progress(0, total)

        if total == 0:
            body = device + b"0FD000000000000"
            reply = self._request_write(
                _frame_bcc(body),
                f"finish empty file {target}",
                offset=0,
                size=0,
                final=True,
            )
            self._raise_if_bad(reply)

            if reply.command != "0":
                raise SDTransportError(
                    f"Unexpected empty-file acknowledgment {reply.command!r}"
                )

            return 0

        offset = 0

        while offset < total:
            chunk = data[offset:offset + block_size]
            final = offset + len(chunk) == total
            command = b"0FD" if final else b"1FD"

            body = device + command
            body += f"{offset:08X}{len(chunk):04X}".encode("ascii")
            body += chunk

            reply = self._request_write(
                _frame_bcc(body),
                f"write {target}",
                offset=offset,
                size=len(chunk),
                final=final,
            )
            self._raise_if_bad(reply)

            expected = "0" if final else "1"
            if reply.command != expected:
                raise SDTransportError(
                    f"Unexpected FD acknowledgment {reply.command!r}; "
                    f"expected {expected!r} at offset {offset}"
                )

            offset += len(chunk)

            if progress:
                progress(offset, total)

        return offset

    def mkdirSD(self, path: str) -> None:
        """Create a directory on the PLC SD card."""
        target = self._wire_path(path)
        path_data = target.encode("ascii") + b"\x00"

        if len(path_data) > 0xFFF:
            raise ValueError("SD card path is too long")

        body = self.device.encode("ascii") + b"0FM"
        body += f"{len(path_data):03X}".encode("ascii")
        body += path_data

        reply = self._request(_frame_bcc(body), f"create directory {target}")
        self._raise_if_bad(reply)

        if reply.command != "0":
            raise SDTransportError(
                f"Unexpected FM acknowledgment command {reply.command!r}"
            )

    def makedirsSD(self, path: str, exist_ok: bool = True) -> None:
        """Create a directory and any missing parent directories."""
        target = self._wire_path(path)

        if target == "/":
            return

        parts = [part for part in target.split("/") if part]
        current = ""

        for part in parts:
            parent = current or "/"
            current += "/" + part

            entries = self.listSD(parent)
            existing = next(
                (entry for entry in entries if entry["name"] == part),
                None,
            )

            if existing is None:
                self.mkdirSD(current)
                continue

            if not existing["is_dir"]:
                raise NotADirectoryError(
                    f"Cannot create directory {current}: "
                    f"{existing['name']!r} is a file"
                )

            if current == target and not exist_ok:
                raise FileExistsError(current)

    def deleteSD(self, path: str, file: Optional[str] = None) -> bool:
        """
        Delete a file or folder from the PLC SD card.

        Examples:
            plc.SD.deleteSD("/cap")
            plc.SD.deleteSD("/FCDATA01/DATALOG", "LOG_260625.CSV")
        """
        target = _join_path(path, file)

        # DataFileManager resolves the path twice before issuing the delete.
        for _ in range(2):
            packet = _frame_bcc(_body_resolve_path(self.device, target))
            rep = self._request(packet, f"resolve {target}")
            self._raise_if_bad(rep)

        rep = self._request(_frame_bcc(_body_delete_path(self.device, target)), f"delete {target}")
        self._raise_if_bad(rep)
        return True

    def readSD(
        self, path: str, file: Optional[str] = None, block_size: int = 0x5C0,
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> bytes:
        """Read one PLC SD card file and return its exact contents."""
        target = self._wire_path(_join_path(path, file))
        data = bytearray()
        self._read_file(target, data.extend, block_size, progress)
        return bytes(data)


    def saveSD(
        self, path: str, file: Optional[str] = None, local_path: Optional[str] = None,
        block_size: int = 0x5C0, progress: Optional[Callable[[int, int], None]] = None,
    ) -> str:
        """
        Stream one PLC SD card file to disk and return the local filename.

        Data is written to ``local_path + ".part"`` and atomically renamed only
        after the complete file has been received. If the transfer fails or is
        interrupted, the partial file is intentionally retained.
        """
        target = self._wire_path(_join_path(path, file))
        local_path = local_path or os.path.basename(target.rstrip("/"))
        if not local_path:
            raise ValueError("local_path is required when the remote path has no filename")

        parent = os.path.dirname(os.path.abspath(local_path))
        if parent:
            os.makedirs(parent, exist_ok=True)

        temp_path = local_path + ".part"
        with open(temp_path, "wb") as out:
            self._read_file(target, out.write, block_size, progress)
        os.replace(temp_path, local_path)
        return local_path

    # ----------
    # Internals
    # ----------

    def _wire_path(self, path: str) -> str:
        path = _norm_path(path)
        if path.upper() == "/SD":
            return "/"
        if path.upper().startswith("/SD/"):
            return path[3:]
        return path

    def _read_file(
        self, target: str, write: Callable[[bytes], Any], block_size: int,
        progress: Optional[Callable[[int, int], None]],
    ) -> int:
        if not 1 <= int(block_size) <= 0xFFF:
            raise ValueError("block_size must be 1..4095")

        path_bytes = target.encode("ascii") + b"\x00"
        if len(path_bytes) > 0xFFF:
            raise ValueError("SD card path is too long")

        dev = self.device.encode("ascii")
        body = dev + b"1Fu" + f"{len(path_bytes):03X}".encode("ascii")
        body += path_bytes + f"{block_size:03X}".encode("ascii")
        rep = self._request(_frame_bcc(body), f"open file {target}")
        self._raise_if_bad(rep)

        try:
            total = int(rep.data.decode("ascii"), 16)
        except Exception as e:
            raise IOError(f"Could not decode file size from {rep.data!r}") from e

        received = 0
        if progress:
            progress(received, total)

        while received < total:
            remaining = total - received
            final = remaining <= block_size
            body = dev + (b"0FU" if final else b"1FU")
            rep = self._request_file_chunk(_frame_bcc(body), received, total)
            self._raise_if_bad(rep)

            if len(rep.data) < 3 or not re.fullmatch(rb"[0-9A-Fa-f]{3}", rep.data[:3]):
                raise IOError(f"Invalid file block header: {rep.data[:16]!r}")

            count = int(rep.data[:3], 16)
            chunk = rep.data[3:]
            if count != len(chunk):
                raise IOError(f"File block says {count} bytes but returned {len(chunk)}")
            if count == 0 or count > remaining:
                raise IOError(f"Invalid file block size {count}; {remaining} bytes remain")
            if final and rep.command != "0":
                raise IOError(f"Expected final file reply, got command {rep.command!r}")
            if not final and rep.command != "1":
                raise IOError(f"Expected continued file reply, got command {rep.command!r}")

            write(chunk)
            received += count
            if progress:
                progress(received, total)

        return received

    def _request_write(
        self, packet: bytes, label: str,
        offset: Optional[int] = None,
        size: Optional[int] = None,
        final: Optional[bool] = None,
    ) -> SDReply:
        """
        Send one FD write request without reconnecting and retrying it.

        An interrupted FD transfer must be restarted from the create-file
        request rather than retrying one block on a new TCP connection.
        """
        if self.debug:
            if offset is None:
                print()
                print("TX", label)
                print("TX hex:", packet.hex(" ").upper())
                print("TX txt:", _printable(packet))
            else:
                print(
                    f"TX file block: offset=0x{offset:08X} "
                    f"size={size} final={final}"
                )

        for name in ("sd_write_xfer", "_sd_write_xfer"):
            fn = getattr(self.plc, name, None)
            if callable(fn):
                raw = fn(packet)
                break
        else:
            ser = getattr(self.plc, "_ser", None)

            if ser is not None:
                try:
                    ser.reset_input_buffer()
                except Exception:
                    pass

                ser.write(packet)
                ser.flush()
                raw = self._serial_recv_until_cr(ser)
            else:
                connect = getattr(self.plc, "connect", None)
                sock = getattr(self.plc, "_sock", None)

                if sock is None and callable(connect):
                    connect()
                    sock = getattr(self.plc, "_sock", None)

                if sock is None:
                    raise TypeError(
                        "SD file writing requires MiSmSerial._ser, "
                        "a persistent MiSmTCP._sock, or sd_write_xfer()."
                    )

                old_timeout = sock.gettimeout()

                try:
                    current = 0.0 if old_timeout is None else float(old_timeout)
                    sock.settimeout(max(current, float(self.timeout)))
                    sock.sendall(packet)
                    raw = self._socket_recv_until_cr(sock, limit=64)
                except (OSError, socket.timeout):
                    close = getattr(self.plc, "close", None)
                    if callable(close):
                        close()
                    raise
                finally:
                    if getattr(self.plc, "_sock", None) is sock:
                        try:
                            sock.settimeout(old_timeout)
                        except OSError:
                            pass

        reply = _parse_reply(raw)

        if self.debug:
            print(f"RX: {reply.kind} command={reply.command!r}")

        return reply

    def _request_file_chunk(self, packet: bytes, received: int, total: int) -> SDReply:
        """Receive one binary-safe file block through MiSmSerial or MiSmTCP."""
        for name in ("sd_file_xfer", "_sd_file_xfer"):
            fn = getattr(self.plc, name, None)
            if callable(fn):
                return _parse_reply(fn(packet))

        ser = getattr(self.plc, "_ser", None)
        if ser is not None:
            try:
                ser.reset_input_buffer()
            except Exception:
                pass
            ser.write(packet)
            ser.flush()
            raw, count = self._recv_file_reply(
                lambda size: self._serial_recv_exact(ser, size),
                lambda: self._serial_recv_until_cr(ser),
            )
            if self.debug and count is not None:
                print(f"RX serial file block: {count} bytes")
            return _parse_reply(raw)

        sock = getattr(self.plc, "_sock", None)
        connect = getattr(self.plc, "connect", None)
        if sock is None and callable(connect):
            connect()
            sock = getattr(self.plc, "_sock", None)

        if sock is None:
            raise TypeError(
                "SD file transfer requires MiSmSerial._ser, a persistent MiSmTCP._sock, "
                "or an sd_file_xfer() hook."
            )

        try:
            sock.sendall(packet)
            raw, count = self._recv_file_reply(
                lambda size: self._socket_recv_exact(sock, size),
                lambda: self._socket_recv_until_cr(sock),
            )
        except (OSError, socket.timeout):
            close = getattr(self.plc, "close", None)
            if callable(close):
                close()
            raise

        if self.debug and count is not None:
            print(f"RX TCP file block: {count} bytes")
        return _parse_reply(raw)

    def _recv_file_reply(
        self, recv_exact: Callable[[int], bytes], recv_tail: Callable[[], bytes],
    ) -> Tuple[bytes, Optional[int]]:
        head = recv_exact(7)
        if head[:1] != b"\x06" or head[3:4] not in (b"0", b"1"):
            return head + recv_tail(), None
        try:
            count = int(head[4:7].decode("ascii"), 16)
        except Exception:
            return head + recv_tail(), None
        return head + recv_exact(count + 3), count

    def _socket_recv_exact(self, sock: socket.socket, count: int) -> bytes:
        data = bytearray()
        while len(data) < count:
            chunk = sock.recv(count - len(data))
            if not chunk:
                raise ConnectionError("PLC closed the connection during SD file transfer")
            data.extend(chunk)
        return bytes(data)

    def _serial_recv_exact(self, ser: Any, count: int) -> bytes:
        baud = max(int(getattr(ser, "baudrate", 9600) or 9600), 1)
        wire_time = count * 11.0 / baud
        end = time.monotonic() + max(self.timeout * 3.0, wire_time + self.timeout * 2.0)
        data = bytearray()
        while len(data) < count and time.monotonic() < end:
            chunk = ser.read(count - len(data))
            if chunk:
                data.extend(chunk)
        if len(data) != count:
            raise TimeoutError(
                f"Timed out during SD file transfer: received {len(data)} of {count} bytes"
            )
        return bytes(data)


    def _cancel_requested(self, cancel: Optional[Any]) -> bool:
        if cancel is None:
            return False
        is_set = getattr(cancel, "is_set", None)
        if callable(is_set):
            return bool(is_set())
        if callable(cancel):
            return bool(cancel())
        return bool(cancel)

    def _raise_if_cancelled(self, cancel: Optional[Any]) -> None:
        if self._cancel_requested(cancel):
            raise InterruptedError("SD-card operation was cancelled")

    def _cancelable_delay(self, cancel: Optional[Any], seconds: float) -> None:
        wait = getattr(cancel, "wait", None)
        if callable(wait):
            if wait(max(float(seconds), 0.0)):
                self._raise_if_cancelled(cancel)
            return
        end = time.monotonic() + max(float(seconds), 0.0)
        while time.monotonic() < end:
            self._raise_if_cancelled(cancel)
            time.sleep(min(0.05, end - time.monotonic()))

    def _reset_transport(self) -> None:
        """Reset MiSmSerial input state or reconnect a persistent TCP client."""
        ser = getattr(self.plc, "_ser", None)
        if ser is not None:
            for name in ("reset_input_buffer", "reset_output_buffer"):
                fn = getattr(ser, name, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass
            return

        reconnect = getattr(self.plc, "reconnect", None)
        if callable(reconnect):
            reconnect()
            return

        close = getattr(self.plc, "close", None)
        connect = getattr(self.plc, "connect", None)
        if callable(close):
            close()
        if callable(connect):
            connect()

    def _guess_device(self) -> str:
        dev = getattr(self.plc, "device", "FF")
        if isinstance(dev, bytes):
            return dev.decode("ascii", errors="replace")
        return str(dev)

    def _request(self, packet: bytes, label: str = "") -> SDReply:
        if self.debug:
            print()
            print("TX", label)
            print("TX hex:", packet.hex(" ").upper())
            print("TX txt:", _printable(packet))

        raw = self._raw_xfer(packet)

        if self.debug:
            print("RX hex:", raw.hex(" ").upper() if raw else "")
            print("RX txt:", _printable(raw) if raw else "")

        rep = _parse_reply(raw)

        if self.debug:
            print("DATA  :", _printable(rep.data))

        return rep

    def _raw_xfer(self, packet: bytes) -> bytes:
        """Send one already-framed packet through the parent PLC object's transport."""
        # Preferred explicit hooks, if you add one to MiSmTCP/MiSmSerial later.
        for name in ("sd_xfer", "_sd_xfer", "raw_xfer", "_raw_xfer"):
            fn = getattr(self.plc, name, None)
            if callable(fn):
                return fn(packet)

        # MiSmSerial-style object.
        ser = getattr(self.plc, "_ser", None)
        if ser is not None:
            try:
                ser.reset_input_buffer()
            except Exception:
                pass
            ser.write(packet)
            ser.flush()
            return self._serial_recv_until_cr(ser)

        # MiSmTCP keeps one socket open, which SD directory and file state requires.
        send_recv = getattr(self.plc, "_send_recv", None)
        if callable(send_recv):
            return send_recv(packet)

        # FC6AMaint / simple MiSmTCP-style object.
        send = getattr(self.plc, "_send", None)
        if callable(send):
            return send(packet)

        # Fallback for objects with ip/host and port attributes but no _send().
        host = getattr(self.plc, "host", None) or getattr(self.plc, "ip", None)
        port = int(getattr(self.plc, "port", 2101))
        timeout = float(getattr(self.plc, "timeout", self.timeout))
        if host:
            with socket.create_connection((host, port), timeout=timeout) as sock:
                sock.settimeout(timeout)
                sock.sendall(packet)
                return self._socket_recv_until_cr(sock)

        raise TypeError(
            "PLC object has no supported raw transport "
            "(_ser, _send_recv, _send, host/ip, or raw_xfer)."
        )

    def _serial_recv_until_cr(self, ser: Any, limit: int = 8192) -> bytes:
        end = time.time() + self.timeout
        buf = bytearray()
        while time.time() < end and len(buf) < limit:
            b = ser.read(1)
            if not b:
                continue
            buf.extend(b)
            if b == b"\r":
                break
        return bytes(buf)

    def _socket_recv_until_cr(self, sock: socket.socket, limit: int = 8192) -> bytes:
        buf = bytearray()
        while len(buf) < limit:
            chunk = sock.recv(256)
            if not chunk:
                break
            buf.extend(chunk)
            if b"\r" in chunk:
                break
        if b"\r" in buf:
            buf = buf.split(b"\r", 1)[0] + b"\r"
        return bytes(buf)

    def _raise_if_bad(self, rep: SDReply) -> None:
        if rep.kind == "NAK":
            raise SDProtocolError(
                f"PLC replied NAK code={rep.nak_code} raw={rep.raw.hex()}"
            )
        if rep.kind == "ACK_NG":
            raise SDProtocolError(
                f"PLC replied ACK/NG code={rep.ng_code} raw={rep.raw.hex()}"
            )
        if rep.kind != "ACK_OK":
            raise SDTransportError(
                f"Unexpected reply kind={rep.kind} raw={rep.raw.hex()}"
            )
        if not rep.bcc_ok:
            recv = rep.bcc_recv if rep.bcc_recv is not None else -1
            calc = rep.bcc_calc if rep.bcc_calc is not None else -1
            raise SDTransportError(
                f"Reply BCC mismatch: recv={recv:02X} calc={calc:02X} "
                f"raw={rep.raw.hex()}"
            )

    def _safe_read_bit(self, addr: str) -> Optional[int]:
        # Preferred modern MiSmSerial style: read_bit("M8070")
        fn = getattr(self.plc, "read_bit", None)
        if callable(fn):
            try:
                return int(fn(addr))
            except TypeError:
                pass
            except Exception:
                return None

        # Older/simple style: read_bits(8070)
        fn = getattr(self.plc, "read_bits", None)
        if callable(fn):
            try:
                num = int(re.sub(r"\D", "", addr))
                return int(bool(fn(num)))
            except Exception:
                return None

        return None

    def _safe_read_word(self, addr: str) -> Optional[int]:
        # Preferred modern MiSmSerial style: read("D8005")
        fn = getattr(self.plc, "read", None)
        if callable(fn):
            try:
                return int(fn(addr))
            except TypeError:
                pass
            except Exception:
                return None

        # Older/simple style: read_word(8005)
        fn = getattr(self.plc, "read_word", None)
        if callable(fn):
            try:
                num = int(re.sub(r"\D", "", addr))
                return int(fn(num))
            except Exception:
                return None

        return None
