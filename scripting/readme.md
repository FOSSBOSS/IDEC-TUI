# IDEC-TUI Scripting Language

IDEC-TUI includes a small scripting language for automating PLC commands.

The goal is not to create a general-purpose programming language. The scripting system is intended for PLC testing, commissioning, diagnostics, repetitive operations, and simple automated control tasks using the same commands available from the IDEC-TUI console.

Scripts are plain-text files and are executed from the IDEC-TUI prompt with:

```text
run test.plc
```

The `.plc` extension is used in the examples for clarity, but scripts are simply text files.

---

## Quick Example

```text
# Write and verify a register

echo Writing 690 to D100
write D100 690
read D100

if read D100 == 690
    print D100 was written successfully
else
    print D100 did not contain the expected value
end
```

Run it from IDEC-TUI:

```text
plc[connected]> run test.plc
```

---

# Commands

Most commands that work from the IDEC-TUI console can also be used from a script.

For example:

```text
read D100
write D100 42

read_bit Y0030
write_bit M0000 1

input I0
output Q0030 1

read_float D200
write_float D200 12.5

force Q3 1
```

Commands exposed by `MiSmSerial` may also be available through the TUI.

Because scripts use the same command dispatcher as the interactive console, improvements to the PLC command interface generally become available to scripts automatically.

---

# Comments

Whole-line comments begin with `#`.

```text
# This is a comment

write D100 100

# Read the value back
read D100
```

Whitespace before the comment is allowed:

```text
    # This is also a comment
```

## Inline Comments

Inline comments are currently **not recommended**.

Do not write:

```text
output Q0030 1    # Turn output on
```

Some script parsing recognizes `#`, but ordinary PLC commands are ultimately passed through the regular TUI command parser, where the remainder of the line may be interpreted as arguments.

Use:

```text
# Turn output on
output Q0030 1
```

---

# Printing Messages

Scripts can display human-readable information using either:

```text
print
```

or:

```text
echo
```

Examples:

```text
print Starting output test
echo Testing expansion module
```

Quoted strings are also accepted:

```text
print "Starting output test"
echo "Writing 690 to D100"
```

The quotes are not printed.

Output:

```text
Starting output test
Writing 690 to D100
```

Printing messages is useful for making test scripts easier to follow:

```text
echo Turning Q0030 ON
output Q0030 1

sleep 1

echo Turning Q0030 OFF
output Q0030 0
```

---

# Delays

Use `sleep` to pause script execution.

```text
sleep 1
```

Fractional seconds may also be used:

```text
sleep 0.5
```

Example:

```text
output Q0030 1
sleep 0.5
output Q0030 0
```

---

# For Loops

The basic loop syntax is:

```text
for variable start stop
    commands
end
```

The ending value is included.

Example:

```text
for i 1 5
    print Loop $i
end
```

The loop variable is referenced using `$`.

Output:

```text
Loop 1
Loop 2
Loop 3
Loop 4
Loop 5
```

---

## PLC Output Example

Cycle outputs Q0030 through Q0037:

```text
for q 30 37
    echo Turning Q00$q ON
    output Q00$q 1
    sleep 0.5

    echo Turning Q00$q OFF
    output Q00$q 0
end
```

When `q` is `30`:

```text
Q00$q
```

becomes:

```text
Q0030
```

---

# Descending Loops

Loops may also count downward.

```text
for q 37 30
    echo Testing Q00$q
    output Q00$q 1
    sleep 0.25
    output Q00$q 0
end
```

This tests:

```text
Q0037
Q0036
Q0035
...
Q0030
```

---

# Nested For Loops

For loops may be nested.

```text
for cycle 1 3
    echo Starting cycle $cycle

    for q 30 37
        echo Testing Q00$q

        output Q00$q 1
        sleep 0.25
        output Q00$q 0
    end
end
```

This cycles outputs Q0030 through Q0037 three times.

Each loop has its own variable:

```text
$cycle
$q
```

---

# Conditionals

Scripts support `if`, `else`, and `end`.

Basic syntax:

```text
if command operator value
    commands
else
    commands
end
```

Example:

```text
if read D100 > 250
    print D100 is above 250
else
    print D100 is 250 or below
end
```

The `else` block is optional:

```text
if read D100 == 690
    print D100 contains the expected value
end
```

---

# Comparison Operators

The following comparison operators are supported:

```text
==
!=
<
<=
>
>=
```

Examples:

```text
if read D100 == 100
    print Equal
end
```

```text
if read D100 != 0
    print D100 is not zero
end
```

```text
if read D100 >= 500
    print D100 reached 500
end
```

---

# Reading Bits in Conditions

Bit reads can also be used as conditions.

```text
if read_bit Y0030 == 1
    print Output Y0030 is ON
else
    print Output Y0030 is OFF
end
```

For PLC outputs, the underlying PLC bit type is currently `Y`.

For example:

```text
output Q0030 1
read_bit Y0030
```

`Q` is accepted by the high-level `output` command, while `read_bit` currently uses the native PLC bit type.

---

# Nested Conditionals

Conditionals may be nested.

```text
if read D100 > 250

    if read D100 == 690
        print D100 is exactly 690
    else
        print D100 is above 250 but is not 690
    end

else
    print D100 is 250 or below
end
```

---

# Combining Loops and Conditionals

Loops and conditionals can be combined.

```text
for q 30 37
    echo Testing Q00$q

    output Q00$q 1
    sleep 0.25

    if read_bit Y00$q == 1
        print Output state is ON
    else
        print Output state did not turn ON
    end

    output Q00$q 0
end
```

This makes it possible to create compact PLC hardware test scripts.

---

# Returning From a Script

`return` is intended to stop execution of the current script and return control to the IDEC-TUI console.

Example:

```text
write D100 690

if read D100 == 690
    print Test complete
    return
end

print This line only executes if the script did not return
```

After `return`, control should return to:

```text
plc[connected]>
```

`return` is different from:

```text
exit
```

`exit`, `quit`, and `q` are IDEC-TUI commands and terminate the entire terminal application.

The intended meanings are:

```text
return    Stop the current script
exit      Exit IDEC-TUI
quit      Exit IDEC-TUI
q         Exit IDEC-TUI
```

---

# Example: Register Test

```text
# Register write/read test

echo Writing 690 to D100
write D100 690

echo Reading D100
read D100

if read D100 == 690
    print PASS - D100 contains 690
else
    print FAIL - D100 does not contain 690
end
```

---

# Example: Output Sequencer

```text
# Cycle expansion outputs

echo Starting output test

for cycle 1 3
    echo Starting cycle $cycle

    for q 30 37
        echo Turning Q00$q ON

        output Q00$q 1
        sleep 0.5

        echo Turning Q00$q OFF

        output Q00$q 0
        sleep 0.25
    end
end

echo Output test complete
```

---

# Example: Conditional Output Control

```text
echo Checking D100

if read D100 > 250
    echo D100 is above the limit
    output Q0030 1
else
    echo D100 is below the limit
    output Q0030 0
end
```

---

# Example: Early Exit

```text
echo Starting register test

write D100 690

if read D100 > 250
    if read D100 == 690
        print D100 is exactly 690
        print Test finished early
        return
    end

    print D100 is above 250
end

print Continuing with remaining tests
```

---

# Script Execution Model

IDEC-TUI scripts deliberately reuse the normal terminal command interface.

For example, the interactive command:

```text
plc[connected]> read D100
```

can be placed directly into a script:

```text
read D100
```

This keeps the scripting language small and avoids creating a separate PLC API specifically for scripts.

The scripting layer primarily adds control-flow features around normal IDEC-TUI commands:

```text
for
if
else
end
sleep
print
echo
return
```

---

# Current Limitations

The scripting language is intentionally small and is still under development.

Currently, it does not provide a full general-purpose programming environment.

Notable limitations include:

- No `while` loops
- No `break`
- No `continue`
- No `elif`
- No general `set` command for user variables
- No arithmetic expressions
- No command-result assignment
- No functions or subroutines
- No structured exception handling
- Inline comments are not reliable
- PLC command behavior is still dependent on the underlying MiSmSerial implementation

Loop variables are currently the primary scripting variables.

For example:

```text
for q 30 37
    print $q
end
```

---

# Possible Future Features

Useful future additions may include:

```text
set
break
continue
while
wait
assert
quiet
```

For example, a future `assert` command could make automated hardware validation possible:

```text
output Q0030 1
sleep 0.25
assert read_bit Y0030 == 1
```

A future `wait` command could provide timeout-based PLC sequencing:

```text
output Q0030 1
wait input I0 == 1 timeout 5
```

These features are not part of the current scripting syntax unless explicitly implemented.

---

# Safety

IDEC-TUI can directly write PLC registers and control physical outputs.

A script such as:

```text
output Q0030 1
```

may energize real equipment.

Before running a script:

- Verify the target PLC.
- Verify register and I/O addresses.
- Understand what connected equipment can move or energize.
- Use appropriate machine safety procedures.
- Do not treat software conditions as a substitute for physical safety systems.

---

# Design Philosophy

The IDEC-TUI scripting language is intentionally simple.

The goal is to make tasks such as this easy:

```text
for q 30 37
    print Testing Q00$q
    output Q00$q 1
    sleep 0.5
    output Q00$q 0
end
```

without requiring a separate Python program for every repetitive PLC test.

IDEC-TUI provides the PLC commands.

The scripting layer provides just enough logic to automate them.
