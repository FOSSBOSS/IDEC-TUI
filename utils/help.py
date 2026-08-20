#!/usr/bin/env python3
def show_help() -> None:
    print(
        """
Built-in commands:
  config         Configure connection settings interactively
  connect        Open serial connection
  disconnect     Close serial connection
  status         Show config and connection status
  methods        List supported MiSmSerial methods
  check          Run PLC diagnostics
  set-time       Set the PLC clock from this computer
  get-time       Read the PLC clock
  lshw           Show the PLC hardware inventory
  ls [path]      List files
  run <file>     Run a PLC command script
  sleep <sec>    Pause execution for a number of seconds
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

Script syntax:
  for <variable> <start> <stop>
      <commands>
  end

  if <value|PLC command> <operator> <value>
      <commands>
  else
      <commands>
  end

  <variable> = <value|PLC command>
  return

Variable substitution:
  $variable

Example script:
  for q 30 37
      output Q00$q 1
      sleep 0.25
      output Q00$q 0
  end

Run it with:
  run test.plc

Examples:
  read D0100
  write D0100 42
  read_bit M8004.15
  write_bit M8004.15 1
  input I0
  output Q0 1
  read_float D0200
  write_float D0200 12.5
  read_timer 0 4

Features:
  - Up/down arrow history
  - Persistent history saved to ~/.plc_terminal_history
  - Tab completion for commands and common register names
    ( LINUX )
        """.strip()
    )
