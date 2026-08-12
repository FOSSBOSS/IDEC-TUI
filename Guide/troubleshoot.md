# Using IDEC-TUI

IDEC-TUI has come a long way, and there are probably still bugs.

Please report all issues on GitHub.

There are also some issues you might see that are normal and expected.

## Communication Port Already in Use

```text
plc[disconnected]> connect
Error: could not open port 'COM3': PermissionError(13, 'Access is denied.', None, 5)
```

Here, another device or program is accessing the communication port you are trying to use.

In this case, it was a monitoring session of WindLDR.

Close the program or session using the port, then try connecting again.

## Communication Port Not Found

```text
plc[disconnected]> connect
Error: could not open port 'COM3': FileNotFoundError(2, 'The system cannot find the file specified.', None, 2)
```

Here, the USB cable is not plugged in.

You could also get the same error by attempting to use the wrong communication port, or by having the wrong communication port configured.

If your PLC is connected, run:

```text
config
```

and set the correct communication port.

Windows and Linux communication port names are case-sensitive, and IDEC-TUI makes no effort to correct mistyped ports.

For example:

```text
plc[disconnected]> connect
Error: could not open port 'com9': FileNotFoundError(2, 'The system cannot find the file specified.', None, 2)
```

Here, `com9` is at fault.

## Weird Output: Maybe It's Debugging!

If you are seeing strange-looking protocol messages, debug mode may be enabled.

Run:

```text
plc[disconnected]> config
Press Enter to keep the current value shown in [brackets].
Port [com9]: COM3
Device [FF]:
Baud [9600]:
Timeout (seconds) [1.0]:
Bytesize [8]:
Parity [N]:
Stopbits [1]:
Debug [y/n, default n]: y
BCC mode ['auto', 'enq', 'no_enq'] [auto]:
Saved config to C:\Users\User\.plc_terminal_config.json
```

Here, debug mode has been turned on.

With debug enabled, normal commands may look like this:

```text
plc[connected]> read D100
TX(ascii): FF0RD010002
TX(hex):   05464630524430313030303232300d
RX(hex):   063031303030303533320d
5
```

Debug mode does not fix issues. It shows what is being sent and received as raw Maintenance Protocol commands.

This output could be disconcerting to some folks, but don't worry. You can turn debug mode back off by typing:

```text
config
```

Running `config` will end the current connection.

For normal use, besides entering the communication port, you can usually just press **Enter** through the remaining configuration options.

To turn debugging off, enter `n` when prompted:

```text
Debug [y/n, default y]: n
```

Your settings will be saved.