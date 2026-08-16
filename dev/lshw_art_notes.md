| ID   | Module(s) currently recognized by `lshw` | Useful functional description                                               |
| ---- | ---------------------------------------- | --------------------------------------------------------------------------- |
| `00` | FC6A-N16B1, N16B3                        | **16 DI** — 24 VDC inputs                                                   |
| `01` | FC6A-R161, T16K1, T16P1, T16K3, T16P3    | **16 DO** — relay, transistor sink, or transistor source depending on model |
| `02` | FC6A-N32B3                               | **32 DI** — 24 VDC                                                          |
| `03` | FC6A-T32K3, T32P3                        | **32 DO** — transistor sink/source                                          |
| `04` | FC6A-N08B1, N08A11                       | **8 DI** — DC or AC depending on model                                      |
| `05` | FC6A-R081, T08K1, T08P1                  | **8 DO** — relay, transistor sink, or transistor source                     |
| `06` | FC6A-M08BR1                              | **4 DI + 4 relay DO**                                                       |
| `07` | FC6A-M24BR1                              | **16 DI + 8 relay DO**                                                      |
| `18` | FC6A-PH1                                 | **HMI / Ethernet expansion**, no field I/O                                  |
| `19` | FC6A-EXM2                                | **Expansion interface**, no field I/O                                       |
| `1A` | FC6A-EXM1S                               | **Expansion interface slave**, no field I/O                                 |
| `20` | FC6A-J2C1                                | **2 AI** — voltage/current                                                  |
| `21` | FC6A-J4A1                                | **4 AI** — voltage/current                                                  |
| `22` | FC6A-J8A1                                | **8 AI** — voltage/current                                                  |
| `24` | FC6A-K4A1                                | **4 AO** — voltage/current                                                  |
| `25` | FC6A-L06A1                               | **4 AI + 2 AO** — voltage/current                                           |
| `26` | FC6A-L03CN1                              | **2 AI + 1 AO** — AI supports voltage/current/TC/RTD                        |
| `27` | FC6A-J4CN1                               | **4 AI** — universal voltage/current/TC/RTD                                 |
| `28` | FC6A-J8CU1                               | **8 AI** — thermocouple/thermistor                                          |
| `29` | FC6A-F2M1                                | **2 AI + 2 SSR control outputs** — PID/temperature module                   |
| `2A` | FC6A-F2MR1                               | **2 AI + 2 relay DO** — PID/temperature module                              |
| `2B` | FC6A-J4CH1Y                              | **4 isolated thermocouple AI**                                              |
| `2C` | FC6A-EXM1M                               | **Expansion interface master**, no field I/O                                |
| `2E` | FC6A-SIF52                               | **1 RS-232 + 1 RS-485**; both can operate simultaneously                    |


IDEC's digital module documentation confirms the point counts and distinguishes the R relay, K sink, and P source versions;  
for example,  
R081 is 8 relay outputs, T08K1 is 8 sink outputs, and T08P1 is 8 source outputs.  
The mixed modules are explicitly 4-in/4-out for M08BR1 and 16-in/8-out for M24BR1.  

The analog cards break down particularly cleanly for your purposes: J = inputs, K = outputs, L = mixed. The L03CN1 is 2  
universal analog inputs + 1 analog output, while L06A1 is 4 AI + 2 AO. J4CN1 is four universal analog inputs,  
and J4CH1Y is four isolated thermocouple channels.

For communications, the SIF52 is especially easy to draw because it literally gives you two ports:  

# FC6A Hardware References

Official IDEC product pages for hardware recognized or relevant to IDEC-TUI `lshw`.

## CPU

- [FC6A-D16R1CEE](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-d16r1cee)
- [FC6A-D16R4CEE](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-d16r4cee)

## Digital Input Modules

### 16 Point

- [FC6A-N16B1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-n16b1)
- [FC6A-N16B3](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-n16b3)

### 32 Point

- [FC6A-N32B3](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-n32b3)

### 8 Point

- [FC6A-N08B1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-n08b1)
- [FC6A-N08A11](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-n08a11)

## Digital Output Modules

### 16 Point

- [FC6A-R161](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-r161)
- [FC6A-T16K1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-t16k1)
- [FC6A-T16P1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-t16p1)
- [FC6A-T16K3](https://www.idec.com/en-ca/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-t16k3)
- [FC6A-T16P3](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-t16p3)

### 32 Point

- [FC6A-T32K3](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-t32k3)
- [FC6A-T32P3](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-t32p3)

### 8 Point

- [FC6A-R081](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-r081)
- [FC6A-T08K1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-t08k1)
- [FC6A-T08P1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-t08p1)

## Mixed Digital I/O Modules

- [FC6A-M08BR1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-m08br1)
- [FC6A-M24BR1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-m24br1)

## Analog Input Modules

- [FC6A-J2C1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-j2c1)
- [FC6A-J4A1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-j4a1)
- [FC6A-J8A1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-j8a1)
- [FC6A-J4CN1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-j4cn1)
- [FC6A-J8CU1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-j8cu1)
- [FC6A-J4CH1Y](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-j4ch1y)

## Analog Output Modules

- [FC6A-K4A1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-k4a1)

## Mixed Analog I/O Modules

- [FC6A-L06A1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-l06a1)
- [FC6A-L03CN1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-l03cn1)
- [FC6A-L03CN4](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-l03cn4)

## Temperature / PID Modules

- [FC6A-F2M1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-f2m1)
- [FC6A-F2MR1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-f2mr1)

## Communications

- [FC6A-SIF52](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-sif52)
- [FC6A-PH1](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-ph1)

## Expansion Interface Modules

- [FC6A-EXM2](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-exm2)
- [FC6A-EXM1M](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-exm1m)
- [FC6A-EXM1S](https://www.idec.com/en-us/automation/programmable-logic-controller/micro-plc/fc6a-microsmart-plc/fc6a-exm1s)
