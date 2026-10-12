# dsPIC33AK512MPS512 — continuous ADC sampling into RAM via DMA, processed on the fly

**In short.** A bare-metal example for the dsPIC33AK512MPS512 on the EV74H48A dsPIC33
Curiosity Platform (a build for the EV17P63A Curiosity Nano exists, not yet run on a
board): the ADC samples at a rate you choose, the DMA writes the samples into a ping-pong
buffer in RAM, and the CPU processes each completed half - a filter, a tone detector -
while the DMA fills the other one. A console on the board's USB-UART controls it. Two PC
tools come with it: **FilterDesign** designs an IIR filter and puts it into the firmware
(install, build, flash), and the **dsPIC33 GUI** streams from the board and shows the time
signal, the spectrum and whether a sample was lost.

**How to use the two tools, step by step, with a demo video:
[docs/GUI-MANUAL.md](docs/GUI-MANUAL.md).**

Where it stands: on the board the stream runs without loss up to about 8 MSPS with the CPU
processing; DMA overruns appear from about 10 MSPS and lost triggers from about 16 MSPS.
Every board run, the newest last: [docs/HARDWARE-LOG.md](docs/HARDWARE-LOG.md); sorted by
question, what holds and what is open (status 25.09.2026): [docs/ANALYSIS.md](docs/ANALYSIS.md).
Which of the documents in `docs/` you need: [docs/README.md](docs/README.md).

## Contents

- [What this example is](#what-this-example-is)
- [Getting started](#getting-started)
  - [The board](#the-board)
  - [The other board: the EV17P63A Curiosity Nano](#the-other-board-the-ev17p63a-curiosity-nano)
- [First run on hardware](#first-run-on-hardware)
  - [Step 1 — the console answers](#step-1--the-console-answers)
  - [Step 2 — run the parts of a test](#step-2--run-the-parts-of-a-test)
  - [Step 3 — read the LED](#step-3--read-the-led)
  - [If it does not work](#if-it-does-not-work)
- [Your own filter: from the design tool to the board](#your-own-filter-from-the-design-tool-to-the-board)
- [Documentation](#documentation)
- [In the MPLAB X simulator](#in-the-mplab-x-simulator)
- [License](#license)

## What this example is

A small, complete MPLAB X project showing **how to configure the device** so the
ADC runs at its maximum rate and the DMA moves the samples into RAM — and **how to
measure whether it really keeps up**. A command console on the board's USB-UART
channel controls it from a terminal or a script.

It is cut to the **EV74H48A** (dsPIC33 Curiosity Platform Development Board) with the
**dsPIC33AK512MPS512 General Purpose DIM** plugged in — the same hardware Microchip's own
40 MSPS example runs on. Order the two, open the project, press Program, and the LED
tells you whether the chain works, before you connect any signal. The source builds
unchanged for the other dsPIC33AK512MPS5xx parts; only the project's device selection and
the pin table differ.

Bare metal, no MCC. Every register write in the source cites the datasheet table or
page it comes from, so nothing has to be taken on trust.

## Getting started

**You need:** an EV74H48A (dsPIC33 Curiosity Platform Development Board) with the
dsPIC33AK512MPS512 GP DIM — or a dsPIC33AK512MPS506 Curiosity Nano (EV17P63A), then
pick the MPLAB X configuration `EV17P63A_Curiosity_Nano_MPS506` — a USB cable, MPLAB X with the XC-DSC compiler and the
dsPIC33AK-MP device pack (MPLAB X offers to download the pack when you open the
project). A signal source is optional — the self-test does not need one. A terminal
program (Tera Term, PuTTY, MPLAB Data Visualizer's terminal) is optional too — the LED
and the debugger tell you the same things.

1. Plug the board in. The PKOB4 debugger enumerates for programming, and the
   MCP2221A's COM port appears for the console (user guide DS70005562D 2.1.1).
2. Open `adc_dma_40msps.X`, press **Build**, then **Program** (or **Debug**).
3. The project's tool is the board's **PKOB4** (`pkob4hybrid`). Check it once in the
   Dashboard or under *Project Properties → Conn.* — it has to be a real debugger, or
   the code never reaches the board and the silent COM port looks exactly like a
   broken one.
4. Watch LED0 (green, the row of eight): **slow blink = everything works.** The
   self-test on the internal reference has passed, the ADC, the DMA and the interrupt
   are running at 40 MSPS. What the other patterns mean is under "First run on
   hardware".
5. Open the MCP2221A's COM port at 115200 8N1, press Enter, type `status`. The reply
   is the counter table; `help` lists the rest. See [docs/CONSOLE.md](docs/CONSOLE.md).

Verified on 2026-09-22 with:

| Tool | Version |
|---|---|
| MPLAB X IDE | v6.35 (project format `version="65"`, which v6.25 also reads) |
| XC-DSC compiler | v3.31.00; the source also builds with v3.21 when the pack supplies the device |
| Device pack | dsPIC33AK-MP_DFP **1.4.260 and 1.3.185** — the source builds against both, `-Wall -Wextra` clean |
| Target | dsPIC33AK512MPS512 (project); the source also builds for the MPS506 |
| Board | EV74H48A + dsPIC33AK512MPS512 GP DIM, user guide DS70005562D, DIM info sheet DS70005563A |

**If MPLAB X complains about the toolchain version** when you open the project: the
`.X` has a version recorded in it, and yours will differ. Go to *Project Properties →
XC-DSC* and pick the version you have. Nothing in the source depends on it — we have
built this with v3.21 and v3.31, and the configuration bits are written so that the
pack version does not matter either (see "One trap worth knowing about" in [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md#one-trap-worth-knowing-about)).

### The board

Everything this example touches on the EV74H48A with the dsPIC33AK512MPS512 DIM, from
the DIM info sheet DS70005563A (Table 1, DIM pin → device pin → board function) and the
board user guide DS70005562D:

| What | Device pin | DIM pin | Where on the board | Note |
|---|---|---|---|---|
| **Analog input** AD3AN5 (default) | RA0 | P77 | **mikroBUS A, pin AN** | 0 … 3.3 V against GND. Same input as Microchip's 40 MSPS example. `ADC_INSTANCE 3`, `ADC_PINSEL 5` |
| Potentiometer AD5AN0 | RA7 | P66 | the 10 kΩ pot | for a knob-driven demo: `ADC_INSTANCE 5`, `ADC_PINSEL 0`, and `samc` ≥ 9 — the pot is a high-impedance source |
| Internal reference ADxAN6 | — | — | inside the ADC | 15/16·VDD, used by the self-test on every core |
| **LED0** | RC8 | P28 | leftmost of the eight green LEDs | driven high to light. LED1…7 are RC9…RC15 |
| S1, S2, S3 | RF3, RF0, RB2 | P45, P43, P41 | push buttons | active low, pull-up on the board; not used by this example |
| **Console UART2** | TX RH1 (RP114), RX RD1 (RP50) | P98, P96 | **MCP2221A USB-UART channel** — its own COM port | 115200 8N1, the channel Microchip's example streams to Data Visualizer on |
| Second UART | TX RH0 (RP113), RX RD10 (RP59) | P102, P100 | PKOB4 USB-UART channel, another COM port | not used by this console |
| Debugger | — | — | PKOB4 via the USB connector J24 | programming and debugging; the console's COM port is on the same USB cable, via the MCP2221A |
| GND | — | — | mikroBUS GND pins, test points | signal ground for the generator |

AD1AN0 of this device sits on RA2, which the board routes to a capacitive touch pad
(P38) — that is why the example uses ADC3 here and not ADC1.

The sources sit under `src/`, split since 02.10.2026 into a **core** — what a customer
takes into their own project, `docs/CORE.md` — and the **lab** this project adds on top:

- core: `src/drivers/` (`clock`, `adc`, `dma`, `sccp`, `dac`, `timebase`, `led`, `uart`,
  one `.c/.h` pair each, plus `disi.h`), `src/port/` (`log.h`, `panic.h`, `wait.h`,
  `regs.h` — headers only: the one path by which a driver may log, wait or stop),
  `src/lib/` (`crc16`, `fmt`, `stats`, `frame`, `wavegen` — hardware-free, with host tests
  under `tests/host/` — and the not yet called building blocks `iir1`, `goertzel_f`,
  `goertzel_i`, `detect`), and `src/core/`: the stream (`capture`, `acquisition`,
  `pingpong`), the processing callback (`sigproc`), the routing core (`routing`), the
  signal generator (`siggen`), the console (`cli.c`, `console.h`, the parser pair
  `cmd_parser.c/.h`), the GUI's grab (`gui_link`), fault handling (`diag`), `sim.h`, and
  `example_main.c`, the core build's `main()`;
- glue, which a customer writes for their own board: `src/app/` (`main.c`,
  `config_bits.c`, `board.h`, `port_impl.c` — this project's implementation of the port
  layer) and `src/boards/` (`board_cfg.h` and one `const board_cfg_t` per board,
  `ev74h48a.c`/`ev17p63a.c`, exactly one linked per build);
- lab: `src/lab/` (`chaintest`, `bench`, `dactest`, `meter`, `tri_eval`, the lab's
  console commands `cli_lab.c`, and `snap`/`rate`/`blk` in `b2b_link`) and `src/sim/`
  (`sim_dma.c`, the simulator's stand-in for `dma.c`).

`tools\build.bat core` builds the core alone (no file of `src/lab/` or `src/sim/`, neither
on the include path); every other build links the lab on top, and the MPLAB X project
references the same files — nothing is duplicated. Every folder is on the include path,
so the files include each other as `"name.h"`. `src/app/main.c` is the place to read
first: it is the start-up order and the main loop, and nothing else.

A **routing core** (`src/core/routing.c/.h`) tracks which resources — DMA channel, SCCP,
DAC output, UREF, RAM — a route such as `ROUTE_STREAM` needs, refuses a conflict or an
unreachable pin before any driver call, and is what `stream on` goes through; `route
list` prints the active route and the resource table. `CLAUDE.md`'s module table is the
complete, authoritative file list and who may call what; [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
draws it as a block diagram (layers, and the data path while streaming); `docs/FIRMWARE-STRUCTURE.md`
and `docs/REFACTORING-PROPOSAL.md` are the analysis and the plan that led here.

**This needs real hardware.** The clock generators, the PLLs, the ADC and the DMA are
the four things this example is about, and all four only exist on silicon. The number
that matters — `dma_overrun` staying at 0 at full rate — cannot be produced anywhere
else. The project is therefore set up for the board: the tool is the PKOB4
(`pkob4hybrid`). A second configuration, `sim`, runs the same code in the MPLAB X
simulator with a stand-in for the DMA — useful for the software above the DMA, useless
for the four things above; see "In the MPLAB X simulator" below.

One part is worth exercising on its own: `process_buffer()`. Write test values into
`buf`, call it directly, and you can check your arithmetic and its cycle count on a
host compiler without a board.

The `tools/` folder builds the same file from the command line without the IDE. **You
can ignore it** — we use it to check that the code compiles against different
compiler and pack versions.

### The other board: the EV17P63A Curiosity Nano

The same source builds for the dsPIC33AK512MPS506 Curiosity Nano (`tools\build.bat nano`). It has not run on a board yet. The profile, its pins and how to try it: [docs/EV17P63A.md](docs/EV17P63A.md).

## First run on hardware

**The firmware runs no test by itself.** It boots, brings the console up, sets the
slowest sample rate and waits. Everything else is typed. That is deliberate: through
seven board runs the console never received a byte, and it could not be told whether the
bytes never arrived or whether the receive interrupt was starving behind the DMA
interrupt. With nothing converting after the boot, that question answers itself — and it
turned out to be the starvation.

### Step 1 — the console answers

Open the board's USB-UART channel at 115200 8N1 and reset. About a dozen lines appear,
ending in `[boot] READY`. Then type a character: it echoes. Then type `help`.

If nothing echoes, stop here — it is the terminal, the COM port or the wiring, not the
firmware. Nothing is converting at this point, so nothing can starve the receiver.

### Step 2 — run the parts of a test

```
test              lists the parts and what each one proves
test all          self, clock, clkoff, sweep, dac, in that order, with a verdict
test self         ADC -> DMA -> RAM on the internal 15/16*VDD reference
test clock        switch every CLKGEN6 ratio and read it back (no measurement)
test clkoff       switch CLKGEN6 off: does the ADC still convert?
test rate         delivered rate at the rate set now, from one clean burst
test sweep        the rate ladder, slowest first, with the counters
test dac          the DAC triangle through the chain: is everything there, in order?
```

`test all` stops only if `test self` fails — without a working chain every number after
it is meaningless. Everything else runs to the end and reports.

Two commands set the rate by hand: `pll <p1> <p2>` (the one that works) and `clk <ratio>`
(the CLKGEN6 divider, which does not change the rate on this silicon and is kept for the
record). `regs` prints the register dump.

### Step 3 — read the LED

| LED0 | Meaning |
|---|---|
| **slow blink, 1 Hz** | running, no error counter has moved. This is the goal. |
| fast blink, 5 Hz | running, but an error counter is non-zero — `dma_overrun`, `late_service`, `proc_missed`, `dma_addr_err` or `dma_bus_err`. |
| *n* short blinks, pause, repeat | stopped at a checkpoint; *n* is the code below. `fail_code` holds the same number. |
| dark, or steadily on | nothing runs at all: not programmed, no power, or stopped in a debugger |

The stop codes:

| Code | Stopped because | Look at |
|---|---|---|
| 1 | PLL1 (ADC clock) did not configure or lock | `PLL1DIV`, `OSCCTRL` |
| 2 | PLL2 (system clock) did not configure or lock | `PLL2DIV`, `OSCCTRL` |
| 3 | CLKGEN1 did not switch to PLL2 | `CLK1CON` |
| 4 | CLKGEN6 did not switch to PLL1 | `CLK6CON` |
| 5 | the ADC core never reported ready | `AD3CON`, `CLK6CON.CLKRDY` |
| 6 | no DMA blocks arrived, or the stream stopped later | `AD3CH0CNT.CNTSTAT`, `DMA0CNT`, `DMA0SEL`, `IEC2` |
| 7 | self-test value out of range | `selftest_mean` — expected ≈ 3840, window 3648 … 4032 |
| 8 | the DMA channel switched itself off | `dma_addr_err`, `DMALOW`, `DMAHIGH` |
| 9 | a CPU trap or an interrupt with no handler | the `[TRAP]` block on the console — it names the vector, the boot stage and the `INTCON*` cause bits. `docs/TROUBLESHOOTING.md` §2.0b |
| 10 | the fail-safe clock monitor moved the CPU to the backup FRC | the `[CLKF]` lines: `OSCCTRL`, `PLL2CON`, `CLK1CON` |
| 11 | something wrote past the end of the sample buffer | the `[guard]` lines: which of the 16 guard words behind `buf` changed and what it holds. A 12-bit value there means the DMA ran past the buffer |

**What the self-test proves, and what it cannot.** It runs the identical clock, ADC, DMA
and interrupt chain on the ADC's internal 15/16·VDD reference (AD3AN6, Table 16-2) and
checks that the mean of a buffer half is 3840 ± 5 %. That is a real end-to-end check of
the wiring — but it samples a **constant**, so a result register that never changed would
give exactly the same mean. Only the DAC test can tell those apart, which is why it
exists.

**The counters**, readable with `status` or a debugger:

| Variable | Should be |
|---|---|
| `blocks_done` | increasing while a test runs a stream |
| `selftest_mean` | ≈ 3840 |
| `last_sample` | changing once a signal is connected; noise around some level on an open pin |
| `dma_overrun` | **0** at a usable rate. Above that it is a *lower bound* on the samples lost: `OVERRUN` is one bit and the counter moves once per handler entry that finds it set, so several losses between two entries count as one. `blocks_done` against `burst_starts` is the exact relation - one burst is a whole buffer, so blocks must be twice bursts |
| `dma_addr_err` | **0** — non-zero means the DMA address window is wrong |
| `late_service`, `proc_missed` | **0** |
| `fail_code` | 0 |

### If it does not work

`docs/TROUBLESHOOTING.md` is the guide, and it is written symptom first: it starts with
the places where we doubt our own code, then walks the symptoms in the order you will
meet them — it does not compile, it lands in a break session, the LED blinks a code,
`dma_overrun` counts up, the values look wrong, the console is silent. `docs/HARDWARE-LOG.md`
is the other half: every run on this board, dated, with what the log said and what was
changed because of it. If something here surprises you, it has probably surprised us
first and is written down there.

## Your own filter: from the design tool to the board

Design an IIR filter in FilterDesign (`filterdesign.bat`), install it into the firmware as `sigproc user`, build, flash, and measure it on the board with the dsPIC33 GUI. Step by step, with pictures: [docs/GUI-MANUAL.md](docs/GUI-MANUAL.md) chapter 2; the firmware side (sample rate, fixed point, the default filter): the manual's chapter 5.

## Documentation

| Document | What is in it |
|---|---|
| [docs/GUI-MANUAL.md](docs/GUI-MANUAL.md) | the two PC tools, FilterDesign and the dsPIC33 GUI |
| [docs/CONSOLE.md](docs/CONSOLE.md) | every console command, a test run, the chain test |
| [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md) | clock tree, ADC, DMA, CPU; the sample rates you can get; what to measure; the device's traps |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | debugging, symptom first |
| [docs/CORE.md](docs/CORE.md) | taking the core into your own project |
| [docs/PROJECT-FILES.md](docs/PROJECT-FILES.md) | what is where: the files, `tools/`, the MPLAB X simulator |
| [docs/HISTORY.md](docs/HISTORY.md) | the revision history and the Microchip examples this started from |
| [docs/README.md](docs/README.md) | all documents in `docs/`, sorted by reader |

## In the MPLAB X simulator

The simulator build, what it proves and what it cannot (no PLL, ADC or DMA): [docs/PROJECT-FILES.md](docs/PROJECT-FILES.md#in-the-mplab-x-simulator). The firmware's simulator message points here.

## License

Microchip's example license, see [LICENSE.txt](LICENSE.txt): you may use this
software and its derivatives exclusively with Microchip products. Every source file
carries the same notice in its header.

One exception: the command parser `src/core/cmd_parser.c/.h`, taken from
[zabooh/cmd_parser](https://github.com/zabooh/cmd_parser), is under the Apache License 2.0;
its own header states the terms, and they apply to those two files.

A second: the filter design library and its command line front end under
`tools/filterdesign/fdesign/` (from FilterDesign, 2019) are under the MIT license, as their
headers state.
