# IDEC-TUI

An interactive terminal for communicating with IDEC MicroSmart PLCs over the
IDEC Maintenance Protocol.

IDEC-TUI provides a persistent command shell around `MiSmSerial.py`. It is
intended for maintenance, testing, register inspection, diagnostics, and direct
PLC interaction without opening WindLDR.

![IDEC-TUI terminal](tui.png)

## Current capabilities

- Interactive serial connection to an IDEC PLC
- Persistent connection settings
- Command history and tab completion
- Read and write word registers
- Read and write individual bits
- Read inputs and control outputs using `I` and `Q` aliases
- Read and write IEEE-754 floating-point values
- Read timer information and write timer or counter values
- Read PLC error-code words
- Read and write blocks of registers
- Read and write multi-register unsigned integers
- Automatic Maintenance Protocol BCC-mode detection
- Optional raw TX/RX debugging
- PLC clock setting from the host computer
- Hardware and health diagnostics through the `check` command
- Direct access to additional public `MiSmSerial` methods

The interactive TUI currently uses the serial Maintenance Protocol. The
repository also contains TCP, SD-card, and HMI-related libraries, but those are
not the active transport used by `hoc_tui.py`.

## Compatibility

The current implementation has been exercised with FC5A and FC6A hardware over
USB serial connections.

The Maintenance Protocol is shared across several IDEC MicroSmart generations,
so some earlier CPUs may also work. CPU identification is intentionally
conservative:

- Legacy `D8002` CPU codes are reported as **FC5A or earlier**
- The broad CPU class, such as `10-I/O`, is printed when known
- Unique FC6A CPU codes are identified directly
- Attached expansion modules are checked independently from the CPU generation

Exact CPU and module identification depends on the information exposed by the
PLC. Some older expansion modules may not have a known type mapping.

## Requirements

- Python 3.10 or newer
- `pyserial`
- A serial or USB Maintenance Protocol connection to the PLC
- `readline` for history and tab completion on Linux and macOS

Install the Python dependency with either:

```bash
python3 -m pip install pyserial
```

or on Debian, Ubuntu, and Linux Mint:

```bash
sudo apt install python3-serial
```

## Installation

```bash
git clone https://github.com/FOSSBOSS/IDEC-TUI.git
cd IDEC-TUI
chmod +x hoc_tui.py
./hoc_tui.py
```

The program is currently run directly from the source tree. `hoc_tui.py` and
`MiSmSerial.py` must remain importable from the same project directory.

## Linux serial permissions

The current user must have permission to access the serial device. On many
Linux systems, that means membership in the `dialout` group:

```bash
sudo usermod -aG dialout "$USER"
```

Log out and back in after changing group membership.

Common PLC serial devices include:

```text
/dev/ttyACM0
/dev/ttyACM1
/dev/ttyUSB0
```

## Quick start

Start the terminal:

```bash
./hoc_tui.py
```

Configure the connection:

```text
plc[disconnected]> config
```

Typical USB settings are:

```text
Port: /dev/ttyACM0
Device: FF
Baud: 9600
Timeout: 1.0
Bytesize: 8
Parity: N
Stopbits: 1
Debug: n
BCC mode: auto
```

Connect and read a register:

```text
plc[disconnected]> connect
Connected to /dev/ttyACM0 (baud=9600, device=FF, bcc_mode=auto)

plc[connected]> read D8002
0
```

Disconnect or quit:

```text
plc[connected]> disconnect
plc[disconnected]> q
```

## Saved settings and history

Connection settings are saved to:

```text
~/.plc_terminal_config.json
```

Command history is saved to:

```text
~/.plc_terminal_history
```

On systems with `readline`, the up and down arrow keys navigate command history
and Tab completes commands, methods, and common register names.

## Built-in commands

| Command | Description |
|---|---|
| `config` | Configure and save serial connection settings |
| `connect` | Open the configured serial connection |
| `disconnect` | Close the current serial connection |
| `status` | Show connection state and saved configuration |
| `check` | Run the bundled PLC diagnostic and return to the TUI |
| `set-time` | Set the PLC clock from the host computer |
| `methods` | List supported and dynamically detected methods |
| `help` | Show command help |
| `clear` | Clear the terminal |
| `q`, `quit`, `exit` | Exit IDEC-TUI |

## PLC commands

### Word registers

```text
read <address>
write <address> <value>
```

Examples:

```text
read D0100
write D0100 42
read D8005
```

`read` returns an unsigned 16-bit value from `0` through `65535`.

### Bits

```text
read_bit <address>
write_bit <address> <0|1>
```

Examples:

```text
read_bit M0000
write_bit M0000 1
read_bit M8004.15
write_bit M8004.15 0
```

The `word.bit` form reads or modifies one bit within a word value.

### Physical inputs and outputs

```text
input <address>
output <address> <0|1>
```

Examples:

```text
input I0
input X0
output Q0 1
output Q0 0
```

`I` is accepted as an input alias for `X`. `Q` is accepted as an output alias
for `Y`.

### Floating-point values

```text
read_float <address> [endian]
write_float <address> <value> [endian]
```

Examples:

```text
read_float D0200
read_float D0200 1
write_float D0200 12.5
```

The optional word-order argument is:

```text
0 = low word first
1 = high word first
```

### Timers and counters

```text
read_timer [timer_number] [count]
write_counter <counter_number> <preset>
```

Examples:

```text
read_timer
read_timer 0 4
write_counter 10 500
```

### PLC error words

```text
read_error [address] [number_of_bytes]
```

Examples:

```text
read_error
read_error 0 12
```

The default reads the six documented error-code words.

## Additional `MiSmSerial` methods

When connected, `methods` also lists additional public methods found on the
current `MiSmSerial` object. These methods can be called directly from the TUI.

Examples:

```text
read_block D0100 4
read_uint D0105 2 1
write_block D0100 [1, 2, 3]
write_uint D0105 69420 2 1
write_timer 420 100
```

Arguments are parsed as Python-style values where possible. Decimal, binary,
octal, hexadecimal, booleans, strings, lists, and numeric values can be used:

```text
42
0x002A
0b101010
true
[1, 2, 3]
```

## Automatic BCC mode

The serial Maintenance Protocol does not use the same request-BCC convention on
every CPU, adapter, or bridge.

The available modes are:

```text
auto
enq
no_enq
```

`auto` first tries a BCC that includes the ENQ byte. If the PLC returns NAK code
`10`, the request is retried without ENQ in the BCC calculation. The successful
mode is retained for the current connection.

Use `auto` unless a specific connection requires a fixed mode.

## Debug output

Enable `debug` in `config` to print Maintenance Protocol traffic:

```text
TX(ascii): FF0RD800202
TX(hex):   05464630524438303032303232420d
RX(hex):   063031303030303033370d
```

This is useful for protocol investigation, BCC troubleshooting, and comparing
requests with WindLDR captures.

## PLC diagnostic

The `check` command launches the bundled `debug.py` diagnostic. In the current
layout, `hoc_tui.py` expects it at:

```text
SERIAL/debug.py
```

The diagnostic can:

- Scan available serial ports for a responsive PLC
- Report the host operating system and current host time
- Report the connected serial device
- Read the CPU type code from `D8002`
- Report a legacy CPU as `FC5A or earlier` with its broad I/O class
- Read the connected expansion-module count from `D8037`
- Identify known expansion modules from the `D8470` register range
- Decode the `D8005` general-error bitfield
- Read selected PLC status bits
- List active outputs
- Read the raw `D8056` value
- Read the firmware version from `D8029`
- Read the PLC date and time

Example:

```text
plc[connected]> check
Running diagnostic: .../SERIAL/debug.py
Disconnected.

PLC connection: OK on /dev/ttyACM0
Hardware inventory:
  CPU type D8002: 0x0000 (0)
  CPU: FC5A or earlier CPU detected
  CPU class: 10-I/O
  Connected expansion modules: 2 (D8037)
  Expansion slot 1: FC6A-J4CN1
  Expansion slot 2: FC6A-J4CN1

Diagnostic finished with exit code 0
Connected to /dev/ttyACM0
```

When `check` is started from an active TUI connection, the TUI closes the port,
runs the diagnostic, and then attempts to reconnect using the saved
configuration.

## Setting the PLC clock

With the PLC connected:

```text
plc[connected]> set-time
```

This writes the host computer's current local date and time to the PLC clock
registers and applies the new clock value.

## Safety

This project can write directly to PLC registers and physical outputs.

Commands such as these can immediately alter machine behavior:

```text
write
write_bit
output
write_block
write_uint
write_timer
write_counter
force
force_io
```

Before writing:

- Confirm the correct PLC is connected
- Confirm the register or output address
- Make sure the machine is in a safe state
- Do not rely on software alone for emergency-stop or safety interlocking
- Avoid forcing outputs on operating equipment unless the consequences are
  fully understood

The TUI exposes additional public library methods dynamically. That is useful
for development, but it also means advanced or experimental methods may be
available from the prompt.

## Current limitations

- The interactive TUI currently connects through `MiSmSerial`
- Operand addresses currently use the four-digit registers
- Exact CPU generation cannot always be determined from `D8002`
- Hardware type tables are incomplete for modules older than FC5A
- The TUI does not currently upload or download PLC user programs
- This is not a replacement for WindLDR project editing
- Hardware and protocol support is still being validated across PLC generations

## Repository files

| File | Purpose |
|---|---|
| `hoc_tui.py` | Interactive terminal application |
| `MiSmSerial.py` | Serial Maintenance Protocol client |
| `SERIAL/debug.py` | PLC connectivity, health, CPU, and module diagnostic |
| `setTime.py` | Standalone PLC clock-setting utility |

## License

IDEC-TUI is released under the MIT License. See `LICENSE` for the complete
license text.

## Project status

IDEC-TUI is usable for direct serial maintenance work, register inspection, and
diagnostics, but it remains an active protocol-development project. Raw protocol
debugging and conservative hardware reporting are intentional parts of the
current design.

## Tested on:
CPU Series Modules: FC5A, FC6A

Expansion Series modules: FC4A, FC5A, FC6A

Exact compatabliity is unknown, but modules remained responsive with a wide array 
of mixxing and matching hardware. Responsive hardware does not mean supported operation.

