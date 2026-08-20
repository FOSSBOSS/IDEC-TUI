#!/usr/bin/env python3
from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any


class ScriptReturn(Exception):
    """Stop the current script without exiting the terminal."""


class ScriptEngine:
    """Execute IDEC-TUI .plc scripts through a PLCTerminalApp-like object."""

    def __init__(self, app: Any, plc_commands: list[str]) -> None:
        self.app = app
        self.plc_commands = set(plc_commands)

    def run(self, filename: str) -> None:
        path = Path(filename)

        if not path.is_file():
            raise FileNotFoundError(f"Script not found: {path}")

        lines = []

        with path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue

                if line.startswith("#"):
                    continue

                lines.append(line)

        try:
            self.execute_lines(lines)
        except ScriptReturn:
            pass

    def expand_vars(
        self,
        line: str,
        variables: dict[str, Any],
    ) -> str:
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            return str(variables.get(name, match.group(0)))

        return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", replace, line)

    def tokens(self, line: str) -> list[str]:
        return shlex.split(line, comments=True)

    def assign_variable(
        self,
        line: str,
        variables: dict[str, Any],
    ) -> bool:
        match = re.match(
            r"^([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)\s*(.+)$",
            line,
        )

        if match is None:
            return False

        name = match.group(1)
        rhs = match.group(2)
        parts = self.tokens(rhs)

        if not parts:
            raise ValueError(f"Missing value for assignment: {name} =")

        command = parts[0].lower()
        is_command = command in self.plc_commands

        if not is_command and self.app.plc is not None:
            method = getattr(self.app.plc, command, None)
            is_command = callable(method)

        if is_command:
            if self.app.plc is None:
                raise RuntimeError(
                    "Not connected. Run 'config' and then 'connect' first."
                )

            value = self.app.execute_plc_command(
                command,
                parts[1:],
                echo=False,
            )
        else:
            if len(parts) != 1:
                raise ValueError(
                    "Assignment must contain one value or a PLC command"
                )

            value = self.app.parse_value(parts[0])

        variables[name] = value
        return True

    def find_block(
        self,
        lines: list[str],
        start: int,
        allow_else: bool = False,
    ) -> tuple[list[str], list[str] | None, int]:
        body: list[str] = []
        else_body: list[str] | None = None
        target = body
        depth = 1
        i = start

        while i < len(lines):
            parts = self.tokens(lines[i])

            if parts:
                cmd = parts[0].lower()
                if cmd in {"for", "if"}:
                    depth += 1

                elif cmd == "end":
                    depth -= 1

                    if depth == 0:
                        return body, else_body, i

                elif cmd == "else" and depth == 1:
                    if not allow_else:
                        raise ValueError("Unexpected 'else'")

                    if else_body is not None:
                        raise ValueError("Multiple 'else' blocks in one if")

                    else_body = []
                    target = else_body
                    i += 1
                    continue

            target.append(lines[i])
            i += 1

        raise ValueError("Missing 'end'")

    def evaluate_condition(self, parts: list[str]) -> bool:
        operators = {"==", "!=", "<", "<=", ">", ">="}
        op_index = -1

        for i, token in enumerate(parts):
            if token in operators:
                op_index = i
                break

        if op_index < 2 or op_index >= len(parts) - 1:
            raise ValueError(
                "Usage: if <value|PLC command> <operator> <value>"
            )

        left_parts = parts[1:op_index]
        operator = parts[op_index]
        right_text = " ".join(parts[op_index + 1:])

        command = left_parts[0]
        is_command = command in self.plc_commands

        if not is_command and self.app.plc is not None:
            method = getattr(self.app.plc, command, None)
            is_command = callable(method)

        if is_command:
            if self.app.plc is None:
                raise RuntimeError(
                    "Not connected. Run 'config' and then 'connect' first."
                )

            left = self.app.execute_plc_command(
                command,
                left_parts[1:],
                echo=False,
            )
        else:
            if len(left_parts) != 1:
                raise ValueError("Left side must be a value or PLC command")

            left = self.app.parse_value(left_parts[0])

        right = self.app.parse_value(right_text)

        if operator == "==":
            return left == right
        if operator == "!=":
            return left != right
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
        if operator == ">":
            return left > right
        if operator == ">=":
            return left >= right

        raise ValueError(f"Unsupported operator: {operator}")

    def execute_lines(
        self,
        lines: list[str],
        variables: dict[str, Any] | None = None,
    ) -> None:
        if variables is None:
            variables = {}

        i = 0

        while i < len(lines):
            raw_line = lines[i]
            line = self.expand_vars(raw_line, variables)
            parts = self.tokens(line)

            if not parts:
                i += 1
                continue

            if self.assign_variable(line, variables):
                i += 1
                continue

            cmd = parts[0].lower()

            if cmd == "return":
                if len(parts) != 1:
                    raise ValueError("Usage: return")

                raise ScriptReturn

            if cmd == "for":
                if len(parts) != 4:
                    raise ValueError(
                        "Usage: for <variable> <start> <stop>"
                    )

                var = parts[1]
                start_value = int(self.app.parse_value(parts[2]))
                stop_value = int(self.app.parse_value(parts[3]))

                body, else_body, end_index = self.find_block(
                    lines,
                    i + 1,
                )

                if else_body is not None:
                    raise ValueError("Unexpected 'else' in for loop")

                step = 1 if stop_value >= start_value else -1

                for value in range(
                    start_value,
                    stop_value + step,
                    step,
                ):
                    child_vars = variables.copy()
                    child_vars[var] = value
                    self.execute_lines(body, child_vars)

                i = end_index

            elif cmd == "if":
                body, else_body, end_index = self.find_block(
                    lines,
                    i + 1,
                    allow_else=True,
                )

                if self.evaluate_condition(parts):
                    self.execute_lines(
                        body,
                        variables,
                    )
                elif else_body is not None:
                    self.execute_lines(
                        else_body,
                        variables,
                    )

                i = end_index

            elif cmd == "else":
                raise ValueError("Unexpected 'else'")

            elif cmd == "end":
                raise ValueError("Unexpected 'end'")

            else:
                self.app.handle_line(line)

            i += 1


def run_script(app: Any, filename: str, plc_commands: list[str]) -> None:
    ScriptEngine(app, plc_commands).run(filename)
