#!/usr/bin/env python3
"""
Interactive terminal shell for controlling an IDEC PLC over serial using MiSmSerial.

Adds:
- Persistent command history
- Tab completion
- Readline support on Linux/macOS
- Same built-in commands and PLC commands as the current IDEC-TUI shell

Commands:
  clear
      Clear screen

  config
      Configure serial connection settings

  connect
      Open the serial connection using current config

  disconnect
      Close the serial connection

  status
      Show current config + connection state

  help
      Show help

  methods
      List supported MiSmSerial methods

  check
      Run the external PLC diagnostic script and return

  set-time
      Set the PLC date/time from this computer and return

  q | quit | exit
      Quit

PLC commands can be entered directly after connecting, for example:
  read D0100
  write D0100 1234
  read_bit M8004.15
  write_bit M8004.15 1
  input I0
  output Q0 1
  read_float D0200
  write_float D0200 12.5
  read_timer 0 4
  read_error

Notes:
- This app expects MiSmSerial.py to be importable from the same directory,
  or installed somewhere on your PYTHONPATH.
- MiSmSerial supports methods including read/write, read_bit/write_bit,
  input/output, read_float/write_float, read_timer, write_counter, and read_error.
"""

from __future__ import annotations

import ast
import atexit
import json
import os
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from MiSmSerial import MiSmSerial
except ImportError:
    print(
        "Could not import MiSmSerial.\n"
        "Put this script next to MiSmSerial.py "
        "or install the library so Python can import it.",
        file=sys.stderr,
    )
    raise

try:
    import readline
except ImportError:
    readline = None


CONFIG_PATH = Path.home() / ".plc_terminal_config.json"
HISTORY_PATH = Path.home() / ".plc_terminal_history"


BUILTIN_COMMANDS = [
    "help",
    "methods",
    "check",
    "set-time",
    "config",
    "connect",
    "disconnect",
    "status",
    "clear",
    "q",
    "quit",
    "exit",
]

PLC_COMMANDS = [
    "read",
    "write",
    "read_bit",
    "write_bit",
    "input",
    "output",
    "read_float",
    "write_float",
    "read_timer",
    "write_counter",
    "read_error",
]

CONFIG_KEYS = [
    "port",
    "device",
    "baud",
    "timeout",
    "bytesize",
    "parity",
    "stopbits",
    "debug",
    "bcc_mode",
]

COMMON_REG_PREFIXES = [
    "D",
    "M",
    "I",
    "Q",
    "X",
    "Y",
    "R",
    "T",
    "C",
]

COMMON_REGISTERS = [
    "D8004",
    "D8005",
    "D8006",
    "D8015",
    "D8016",
    "D8017",
    "D8018",
    "D8019",
    "D8020",
    "D8021",
    "D8029",
    "M8000",
    "M8002",
    "M8010",
    "M8020",
    "M8025",
    "M8070",
    "M8071",
    "M8072",
    "M8172",
    "M8173",
    "M8174",
    "M8175",
    "M8250",
    "M8252",
    "I0",
    "I1",
    "I2",
    "I3",
    "Q0",
    "Q1",
    "Q2",
    "Q3",
    "Y0",
    "Y1",
    "Y2",
    "Y3",
]

YES_WORDS = {"y", "yes", "1", "true", "on"}
NO_WORDS = {"n", "no", "0", "false", "off"}


@dataclass
class AppConfig:
    port: str = "/dev/ttyUSB0"
    device: str = "FF"
    baud: int = 19200
    timeout: float = 1.0
    bytesize: int = 8
    parity: str = "N"
    stopbits: int = 1
    debug: bool = False
    bcc_mode: str = "auto"


class PLCCompleter:
    def __init__(self, app: "PLCTerminalApp") -> None:
        self.app = app

    def _get_candidates(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        try:
            tokens = shlex.split(line[:begidx], posix=True)
        except ValueError:
            tokens = line[:begidx].split()

        current = text or ""

        if begidx == 0:
            pool = BUILTIN_COMMANDS + PLC_COMMANDS
            if self.app.plc is not None:
                pool.extend(self.app.dynamic_method_names())
            return sorted([p for p in set(pool) if p.startswith(current)])

        if not tokens:
            return []

        cmd = tokens[0].lower()

        if cmd == "config":
            pool = CONFIG_KEYS
            return sorted([p for p in pool if p.startswith(current)])

        if cmd in {"connect", "disconnect", "status", "help", "methods", "check", "set-time", "clear", "q", "quit", "exit"}:
            return []

        if cmd in {"read", "write", "read_bit", "write_bit", "read_float", "write_float"}:
            if len(tokens) == 1:
                pool = COMMON_REGISTERS + COMMON_REG_PREFIXES
                return sorted([p for p in set(pool) if p.startswith(current.upper()) or p.startswith(current)])
            return []

        if cmd in {"input", "output"}:
            if len(tokens) == 1:
                pool = ["I0", "I1", "I2", "I3", "Q0", "Q1", "Q2", "Q3", "Y0", "Y1", "Y2", "Y3", "0", "1", "2", "3"]
                return sorted([p for p in pool if p.startswith(current.upper()) or p.startswith(current)])
            if len(tokens) == 2 and cmd == "output":
                pool = ["0", "1"]
                return sorted([p for p in pool if p.startswith(current)])
            return []

        if cmd in {"read_timer", "write_counter", "read_error"}:
            pool = ["0", "1", "2", "4", "8", "12", "16"]
            return sorted([p for p in pool if p.startswith(current)])

        if cmd in self.app.dynamic_method_names():
            pool = COMMON_REGISTERS + COMMON_REG_PREFIXES + ["0", "1", "true", "false"]
            return sorted([p for p in set(pool) if p.startswith(current.upper()) or p.startswith(current)])

        return []

    def complete(self, text: str, state: int) -> str | None:
        if readline is None:
            return None

        line = readline.get_line_buffer()
        begidx = readline.get_begidx()
        endidx = readline.get_endidx()

        matches = self._get_candidates(text, line, begidx, endidx)
        return matches[state] if state < len(matches) else None


class PLCTerminalApp:
    def __init__(self) -> None:
        self.config = self._load_config()
        self.plc: MiSmSerial | None = None
        self.running = True
        self._setup_readline()

    def _load_config(self) -> AppConfig:
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                return AppConfig(**data)
            except Exception as exc:
                print(f"Warning: failed to load config: {exc}")
        return AppConfig()

    def _save_config(self) -> None:
        CONFIG_PATH.write_text(json.dumps(asdict(self.config), indent=2))

    def _setup_readline(self) -> None:
        if readline is None:
            return

        try:
            readline.parse_and_bind("tab: complete")
        except Exception:
            pass

        try:
            readline.parse_and_bind("set show-all-if-ambiguous on")
        except Exception:
            pass

        try:
            readline.parse_and_bind("set completion-ignore-case on")
        except Exception:
            pass

        completer = PLCCompleter(self)
        readline.set_completer(completer.complete)

        if HISTORY_PATH.exists():
            try:
                readline.read_history_file(str(HISTORY_PATH))
            except Exception as exc:
                print(f"Warning: failed to read history file: {exc}")

        try:
            readline.set_history_length(2000)
        except Exception:
            pass

        atexit.register(self._save_history)

    def _save_history(self) -> None:
        if readline is None:
            return
        try:
            readline.write_history_file(str(HISTORY_PATH))
        except Exception as exc:
            print(f"Warning: failed to save history file: {exc}")

    def dynamic_method_names(self) -> list[str]:
        if self.plc is None:
            return []
        names = []
        for name in dir(self.plc):
            if name.startswith("_"):
                continue
            try:
                attr = getattr(self.plc, name)
            except Exception:
                continue
            if callable(attr):
                names.append(name)
        return sorted(set(names))

    def prompt(self) -> str:
        state = "connected" if self.plc else "disconnected"
        return f"plc[{state}]> "

    def run(self) -> None:
        print("PLC Terminal")
        print("Type 'help' for help, 'config' to configure the port, 'q' to quit.")
        if readline is not None:
            print(f"History file: {HISTORY_PATH}")

        while self.running:
            try:
                line = input(self.prompt()).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line:
                continue

            try:
                self.handle_line(line)
            except Exception as exc:
                print(f"Error: {exc}")

        self.disconnect()
        print("Bye.")

    def handle_line(self, line: str) -> None:
        parts = shlex.split(line)
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in {"q", "quit", "exit"}:
            self.running = False
            return

        if cmd == "help":
            self.show_help()
            return

        if cmd == "methods":
            self.show_methods()
            return

        if cmd == "check":
            self.run_check()
            return

        if cmd == "set-time":
            self.set_time()
            return

        if cmd == "config":
            self.configure_interactive()
            return

        if cmd == "connect":
            self.connect()
            return

        if cmd == "disconnect":
            self.disconnect()
            return

        if cmd == "status":
            self.show_status()
            return

        if cmd == "clear":
            self.clear()
            return

        if self.plc is None:
            print("Not connected. Run 'config' and then 'connect' first.")
            return

        self.execute_plc_command(cmd, args)

    def show_help(self) -> None:
        print(
            """
Built-in commands:
  config         Configure connection settings interactively
  connect        Open serial connection
  disconnect     Close serial connection
  status         Show config and connection status
  methods        List supported MiSmSerial methods
  check          Run SERIAL/EXAMPLES/debug.py and return
  set-time       Set the PLC clock from this computer
  help           Show this help
  clear          Clear the terminal
  q | quit | exit
                 Quit

PLC commands:
  read <addr>
  write <addr> <value>
  read_bit <addr>
  write_bit <addr> <0|1>
  input <bit>
  output <bit> <0|1>
  read_float <addr> [endian]
  write_float <addr> <value> [endian]
  read_timer [tnum] [count]
  write_counter <cnum> <preset>
  read_error [addr] [nbytes]

Examples:
  config
  connect
  check
  set-time
  read D0100
  write D0100 42
  read_bit M8004.15
  write_bit M8004.15 1
  input I0
  output Q0 1
  read_float D0200
  write_float D0200 12.5
  read_timer 0 4
  read_error

Readline features:
  - Up/down arrow history
  - Persistent history saved to ~/.plc_terminal_history
  - Tab completion for commands and common register names
            """.strip()
        )

    def show_methods(self) -> None:
        methods = [
            "read(addr, endian=0, dtype=None)",
            "write(addr, value, endian=0, dtype=None)",
            "read_bit(addr, endian=0, dtype=None)",
            "write_bit(addr, on, endian=0, dtype=None)",
            "input(bit)",
            "output(bit, on=1)",
            "read_float(addr, endian=0, dtype=None)",
            "write_float(addr, value, endian=0, dtype=None)",
            "read_timer(tnum, count=1)",
            "write_counter(cnum, preset)",
            "read_error(addr=0, nbytes=12)",
            "close()",
        ]
        print("Supported MiSmSerial methods:")
        for item in methods:
            print(f" - {item}")

        if self.plc is not None:
            extra = [m for m in self.dynamic_method_names() if m not in {
                "read", "write", "read_bit", "write_bit", "input", "output",
                "read_float", "write_float", "read_timer", "write_counter",
                "read_error", "close"
            }]
            if extra:
                print("\nDetected additional callable methods on current MiSmSerial object:")
                for item in extra:
                    print(f" - {item}")

    def show_status(self) -> None:
        print("Connection status:", "connected" if self.plc else "disconnected")
        print(json.dumps(asdict(self.config), indent=2))

    def configure_interactive(self) -> None:
        print("Press Enter to keep the current value shown in [brackets].")
        self.disconnect()

        self.config.port = self.ask_str("Port", self.config.port)
        self.config.device = self.ask_str("Device", self.config.device).upper()
        self.config.baud = self.ask_int("Baud", self.config.baud)
        self.config.timeout = self.ask_float("Timeout (seconds)", self.config.timeout)
        self.config.bytesize = self.ask_int("Bytesize", self.config.bytesize)
        self.config.parity = self.ask_str("Parity", self.config.parity).upper()
        self.config.stopbits = self.ask_int("Stopbits", self.config.stopbits)
        self.config.debug = self.ask_bool("Debug", self.config.debug)
        self.config.bcc_mode = self.ask_choice(
            "BCC mode",
            self.config.bcc_mode,
            ["auto", "enq", "no_enq"],
        )

        self._save_config()
        print(f"Saved config to {CONFIG_PATH}")

    def ask_str(self, label: str, default: str) -> str:
        value = input(f"{label} [{default}]: ").strip()
        return value or default

    def ask_int(self, label: str, default: int) -> int:
        value = input(f"{label} [{default}]: ").strip()
        return default if value == "" else int(value)

    def ask_float(self, label: str, default: float) -> float:
        value = input(f"{label} [{default}]: ").strip()
        return default if value == "" else float(value)

    def ask_bool(self, label: str, default: bool) -> bool:
        default_text = "y" if default else "n"
        value = input(f"{label} [y/n, default {default_text}]: ").strip().lower()
        if value == "":
            return default
        if value in YES_WORDS:
            return True
        if value in NO_WORDS:
            return False
        raise ValueError("Expected y/n, yes/no, true/false, 1/0, on/off")

    def ask_choice(self, label: str, default: str, choices: list[str]) -> str:
        value = input(f"{label} {choices} [{default}]: ").strip().lower()
        if value == "":
            return default
        if value not in choices:
            raise ValueError(f"Expected one of: {', '.join(choices)}")
        return value

    def set_time(self) -> None:
        if self.plc is None:
            print("Not connected. Run 'config' and then 'connect' first.")
            return

        from datetime import datetime

        now = datetime.now()
        self.plc.write("D8015", now.year % 100)
        self.plc.write("D8016", now.month)
        self.plc.write("D8017", now.day)
        self.plc.write("D8018", now.weekday())
        self.plc.write("D8019", now.hour)
        self.plc.write("D8020", now.minute)
        self.plc.write("D8021", now.second)
        self.plc.write_bit("M8020", 1)
        self.plc.write_bit("M8020", 0)

        print(
            "PLC time set to: "
            f"{now.year:04d}-{now.month:02d}-{now.day:02d} "
            f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}"
        )

    def clear(self) -> None:
        if os.name == "nt":
            os.system("cls")
        else:
            os.system("clear")

    def run_check(self) -> None:
        candidates = [
            Path(__file__).resolve().parent / "debug.py",
            Path(__file__).resolve().parent / "SERIAL" / "EXAMPLES" / "debug.py",
            Path.cwd() / "debug.py",
            Path.cwd() / "SERIAL" / "EXAMPLES" / "debug.py",
        ]

        debug_script = next((p for p in candidates if p.exists()), None)

        if debug_script is None:
            print("Could not find debug.py. Expected it beside this app or in SERIAL/EXAMPLES/.")
            return

        print(f"Running diagnostic: {debug_script}")
        was_connected = self.plc is not None

        if was_connected:
            self.disconnect()

        try:
            result = subprocess.run([sys.executable, str(debug_script)], check=False)
            print(f"Diagnostic finished with exit code {result.returncode}")
        except Exception as exc:
            print(f"Failed to run diagnostic: {exc}")
        finally:
            if was_connected:
                try:
                    self.connect()
                except Exception as exc:
                    print(f"Could not reconnect automatically: {exc}")

    def connect(self) -> None:
        self.disconnect()
        self.plc = MiSmSerial(
            port=self.config.port,
            device=self.config.device,
            baud=self.config.baud,
            timeout=self.config.timeout,
            bytesize=self.config.bytesize,
            parity=self.config.parity,
            stopbits=self.config.stopbits,
            debug=self.config.debug,
            bcc_mode=self.config.bcc_mode,
        )
        print(
            f"Connected to {self.config.port} "
            f"(baud={self.config.baud}, device={self.config.device}, "
            f"bcc_mode={self.config.bcc_mode})"
        )

    def disconnect(self) -> None:
        if self.plc is not None:
            try:
                self.plc.close()
            finally:
                self.plc = None
                print("Disconnected.")

    def execute_plc_command(self, cmd: str, args: list[str]) -> None:
        assert self.plc is not None

        if cmd == "read":
            self.require_args(cmd, args, 1)
            print(self.plc.read(args[0]))
            return

        if cmd == "write":
            self.require_args(cmd, args, 2)
            value = self.parse_value(args[1])
            print(self.plc.write(args[0], int(value)))
            return

        if cmd == "read_bit":
            self.require_args(cmd, args, 1)
            print(self.plc.read_bit(args[0]))
            return

        if cmd == "write_bit":
            self.require_args(cmd, args, 2)
            print(self.plc.write_bit(args[0], int(self.parse_value(args[1]))))
            return

        if cmd == "input":
            self.require_args(cmd, args, 1)
            io_arg = self.parse_io_arg(args[0])
            print(self.plc.input(io_arg))
            return

        if cmd == "output":
            self.require_args(cmd, args, 2)
            io_arg = self.parse_io_arg(args[0])
            print(self.plc.output(io_arg, int(self.parse_value(args[1]))))
            return

        if cmd == "read_float":
            self.require_args(cmd, args, 1)
            endian = int(self.parse_value(args[1])) if len(args) > 1 else 0
            print(self.plc.read_float(args[0], endian=endian))
            return

        if cmd == "write_float":
            self.require_args(cmd, args, 2)
            value = float(self.parse_value(args[1]))
            endian = int(self.parse_value(args[2])) if len(args) > 2 else 0
            print(self.plc.write_float(args[0], value, endian=endian))
            return

        if cmd == "read_timer":
            tnum = int(self.parse_value(args[0])) if args else 0
            count = int(self.parse_value(args[1])) if len(args) > 1 else 1
            print(self.plc.read_timer(tnum, count))
            return

        if cmd == "write_counter":
            self.require_args(cmd, args, 2)
            cnum = int(self.parse_value(args[0]))
            preset = int(self.parse_value(args[1]))
            print(self.plc.write_counter(cnum, preset))
            return

        if cmd == "read_error":
            addr = int(self.parse_value(args[0])) if len(args) > 0 else 0
            nbytes = int(self.parse_value(args[1])) if len(args) > 1 else 12
            print(self.plc.read_error(addr, nbytes))
            return

        if hasattr(self.plc, cmd):
            method = getattr(self.plc, cmd)
            parsed_args = [self.parse_value(a) for a in args]
            result = method(*parsed_args)
            if result is not None:
                print(result)
            return

        print(f"Unknown command: {cmd}. Type 'help' or 'methods'.")

    def require_args(self, cmd: str, args: list[str], min_count: int) -> None:
        if len(args) < min_count:
            raise ValueError(f"{cmd} needs at least {min_count} argument(s)")

    def parse_io_arg(self, raw: str) -> Any:
        return int(raw) if raw.isdigit() else raw

    def parse_value(self, raw: str) -> Any:
        text = raw.strip()

        if text.lower() in {"true", "false"}:
            return text.lower() == "true"

        try:
            if text.startswith(("0x", "0X")):
                return int(text, 16)
            if text.startswith(("0b", "0B")):
                return int(text, 2)
            if text.startswith(("0o", "0O")):
                return int(text, 8)
        except ValueError:
            pass

        try:
            return ast.literal_eval(text)
        except Exception:
            return text


def main() -> int:
    app = PLCTerminalApp()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
