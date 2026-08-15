#!/usr/bin/env python3
"""IDEC MicroSmart Maintenance Protocol emulator over PTY or TCP."""

from __future__ import annotations

import argparse
import json
import os
import select
import signal
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

if os.name != "nt":
    import pty
else:
    pty = None


DEFAULT_CONFIG = Path(__file__).with_name("plc.json")

ENQ = 0x05
ACK = 0x06
NAK = 0x15

def xor_bcc(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
    return value & 0xFF


def reply(device: bytes, command: bytes, data: bytes = b"", control: int = ACK) -> bytes:
    body = bytes((control,)) + device + command + data
    return body + f"{xor_bcc(body):02X}".encode("ascii") + b"\r"


def parse_number(value: object) -> int:
    if isinstance(value, int):
        return value
    return int(str(value), 0)


@dataclass
class PLCMemory:
    words: dict[str, dict[int, int]] = field(default_factory=dict)
    bits: dict[str, dict[int, int]] = field(default_factory=dict)
    timer_status: dict[int, int] = field(default_factory=dict)
    force_enabled: bool = False
    forced_values: dict[int, int] = field(default_factory=dict)
    forced_masks: set[int] = field(default_factory=set)

    def read_word(self, dtype: str, address: int) -> int:
        return self.words.get(dtype, {}).get(address, 0) & 0xFFFF

    def write_word(self, dtype: str, address: int, value: int) -> None:
        self.words.setdefault(dtype, {})[address] = value & 0xFFFF

    def read_bit(self, dtype: str, address: int) -> int:
        return 1 if self.bits.get(dtype.lower(), {}).get(address, 0) else 0

    def write_bit(self, dtype: str, address: int, value: int) -> None:
        self.bits.setdefault(dtype.lower(), {})[address] = 1 if value else 0

    @classmethod
    def from_config(cls, config: dict) -> "PLCMemory":
        memory = cls()
        for address, value in config.get("registers", {}).items():
            dtype, number = address[0], int(address[1:])
            if dtype.lower() in {"x", "y", "m", "r"}:
                memory.write_bit(dtype, number, parse_number(value))
            else:
                memory.write_word(dtype, number, parse_number(value))
        for number, status in config.get("timer_status", {}).items():
            memory.timer_status[int(number)] = parse_number(status) & 0xFF
        return memory


class ProtocolError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class Emulator:
    def __init__(self, config: dict, verbose: bool = False):
        self.device = str(config.get("device", "FF")).upper().encode("ascii")
        self.memory = PLCMemory.from_config(config)
        self.verbose = verbose
        self.delay = float(config.get("reply_delay", 0))
        self.drop_every = int(config.get("drop_every", 0))
        self.requests = 0

    def handle(self, frame: bytes) -> bytes | None:
        self.requests += 1
        if self.drop_every and self.requests % self.drop_every == 0:
            return None
        try:
            device, command, dtype, payload = self.parse_frame(frame)
            if device not in (self.device, b"FF"):
                return None
            data = self.execute(command, dtype, payload)
            if self.delay:
                time.sleep(self.delay)
            return reply(device, command, data)
        except ProtocolError as error:
            device = frame[1:3] if len(frame) >= 3 else self.device
            command = frame[4:5] if len(frame) >= 5 else b"0"
            return reply(device, command, error.code.encode("ascii"), NAK)
        except (ValueError, IndexError, UnicodeDecodeError):
            device = frame[1:3] if len(frame) >= 3 else self.device
            command = frame[4:5] if len(frame) >= 5 else b"0"
            return reply(device, command, b"11", NAK)

    def parse_frame(self, frame: bytes) -> tuple[bytes, bytes, str, bytes]:
        if len(frame) < 10 or frame[0] != ENQ or frame[-1:] != b"\r":
            raise ProtocolError("11")
        body, supplied = frame[:-3], frame[-3:-1]
        try:
            received_bcc = int(supplied.decode("ascii"), 16)
        except ValueError as error:
            raise ProtocolError("10") from error
        valid_bccs = {xor_bcc(body), xor_bcc(body[1:])}
        if received_bcc not in valid_bccs:
            raise ProtocolError("10")
        return frame[1:3], frame[4:5], chr(frame[5]), frame[6:-3]

    def execute(self, command: bytes, dtype: str, payload: bytes) -> bytes:
        if command == b"R":
            return self.read(dtype, payload)
        if command == b"W":
            self.write(dtype, payload)
            return b""
        raise ProtocolError("12")

    def read(self, dtype: str, payload: bytes) -> bytes:
        if len(payload) < 4:
            raise ProtocolError("11")
        address = int(payload[:4])
        if dtype in "xymr":
            return str(self.memory.read_bit(dtype, address)).encode("ascii")
        if dtype == "_":
            count = int(payload[4:6], 16)
            blocks = []
            for number in range(address, address + count):
                current = self.memory.read_word("t", number)
                preset = self.memory.read_word("T", number)
                status = self.memory.timer_status.get(number, 0)
                blocks.append(f"{current:04X}{preset:04X}{status:02X}")
            return "".join(blocks).encode("ascii")
        nbytes = int(payload[4:6], 16)
        if nbytes % 2:
            raise ProtocolError("11")
        values = [self.memory.read_word(dtype, address + offset)
                  for offset in range(nbytes // 2)]
        return "".join(f"{value:04X}" for value in values).encode("ascii")

    def write(self, dtype: str, payload: bytes) -> None:
        if dtype == "O":
            self.memory.force_enabled = payload == b"1"
            if not self.memory.force_enabled:
                self.memory.forced_values.clear()
                self.memory.forced_masks.clear()
            return
        if dtype in "]^":
            address, value = int(payload[:4]), int(payload[4:5])
            if dtype == "]":
                self.memory.forced_values[address] = value
            else:
                if value:
                    self.memory.forced_masks.add(address)
                    forced = self.memory.forced_values.get(address, 0)
                    self.memory.write_bit("y", address, forced)
                else:
                    self.memory.forced_masks.discard(address)
            return
        if dtype in "xymr":
            self.memory.write_bit(dtype, int(payload[:4]), int(payload[4:5]))
            return
        address = int(payload[:4])
        nbytes = int(payload[4:6], 16)
        data = payload[6:]
        if nbytes % 2 or len(data) != nbytes * 2:
            raise ProtocolError("11")
        for offset in range(nbytes // 2):
            start = offset * 4
            self.memory.write_word(dtype, address + offset, int(data[start:start + 4], 16))

def load_config(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as stream:
        return json.load(stream)


def install_link(target: str, link_name: str) -> None:
    link = Path(link_name)

    if link.is_symlink() or not link.exists():
        link.unlink(missing_ok=True)
        link.symlink_to(target)
        return

    raise FileExistsError(f"refusing to replace non-symlink: {link}")


def process_chunk(emulator: Emulator, buffer: bytearray,
                  chunk: bytes, send) -> None:
    buffer.extend(chunk)

    while b"\r" in buffer:
        frame, _, remainder = buffer.partition(b"\r")
        buffer[:] = remainder
        frame += b"\r"

        if emulator.verbose:
            print(f"RX {frame.hex()}", file=sys.stderr)

        response = emulator.handle(frame)

        if response is not None:
            send(response)

            if emulator.verbose:
                print(f"TX {response.hex()}", file=sys.stderr)


def serve(config: dict, link_name: str | None = None,
          verbose: bool = False) -> int:
    """Run the emulator using a Linux pseudo-terminal."""

    if pty is None:
        raise OSError("PTY transport is not available on Windows")

    master, slave = pty.openpty()
    port = os.ttyname(slave)

    if link_name:
        install_link(port, link_name)
        port = link_name

    print(port, flush=True)

    emulator = Emulator(config, verbose)
    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    buffer = bytearray()

    try:
        while running:
            readable, _, _ = select.select([master], [], [], 0.25)

            if not readable:
                continue

            chunk = os.read(master, 4096)

            if chunk:
                process_chunk(
                    emulator,
                    buffer,
                    chunk,
                    lambda data: os.write(master, data),
                )

    finally:
        os.close(master)
        os.close(slave)

        if link_name:
            Path(link_name).unlink(missing_ok=True)

    return 0


class EmulatorServer:
    """Background TCP IDEC emulator."""

    def __init__(self, config: dict, host: str = "127.0.0.1",
                 port: int = 0, verbose: bool = False):
        self.host = host
        self.port = port
        self.emulator = Emulator(config, verbose)

        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: BaseException | None = None

        self._thread = threading.Thread(
            target=self._run,
            name="idec-emu",
            daemon=True,
        )

        self._thread.start()
        self._ready.wait()

        if self._error is not None:
            raise RuntimeError("failed to start IDEC emulator") from self._error

    @property
    def endpoint(self) -> str:
        return f"socket://{self.host}:{self.port}"

    def _run(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind((self.host, self.port))

                self.port = server.getsockname()[1]

                server.listen(1)
                server.settimeout(0.25)

                self._ready.set()

                while not self._stop.is_set():
                    try:
                        client, _ = server.accept()
                    except socket.timeout:
                        continue

                    with client:
                        client.settimeout(0.25)
                        buffer = bytearray()

                        while not self._stop.is_set():
                            try:
                                chunk = client.recv(4096)
                            except socket.timeout:
                                continue

                            if not chunk:
                                break

                            process_chunk(
                                self.emulator,
                                buffer,
                                chunk,
                                client.sendall,
                            )

        except BaseException as error:
            self._error = error
            self._ready.set()

    def stop(self) -> None:
        self._stop.set()

        if self._thread.is_alive():
            self._thread.join(timeout=1.0)


def start_emulator(config_path: str | Path | None = None,
                   verbose: bool = False,
                   host: str = "127.0.0.1",
                   port: int = 0) -> EmulatorServer:
    if config_path is None:
        config_path = DEFAULT_CONFIG

    config = load_config(config_path)

    return EmulatorServer(
        config,
        host=host,
        port=port,
        verbose=verbose,
    )


def serve_tcp(config: dict, host: str = "127.0.0.1",
              port: int = 0, verbose: bool = False) -> int:
    emulator = EmulatorServer(
        config,
        host=host,
        port=port,
        verbose=verbose,
    )

    print(emulator.endpoint, flush=True)

    try:
        while True:
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        emulator.stop()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="JSON PLC configuration",
    )

    parser.add_argument(
        "--link",
        help="stable symlink to the allocated PTY",
    )

    parser.add_argument(
        "--tcp",
        action="store_true",
        help="use TCP instead of a pseudo-terminal",
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="TCP listen address",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="TCP port, 0 selects an available port",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print protocol frames",
    )

    args = parser.parse_args()

    config = load_config(args.config)

    if os.name == "nt" or args.tcp:
        if args.link:
            parser.error("--link is only available with PTY transport")

        return serve_tcp(
            config,
            host=args.host,
            port=args.port,
            verbose=args.verbose,
        )

    return serve(
        config,
        link_name=args.link,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    raise SystemExit(main())
