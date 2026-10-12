# What is where in the project

The files, the `tools/` folder and the MPLAB X simulator. Moved out of the top-level README on 13.10.2026, unchanged; only links were adjusted to the new place.

## Contents

- [Files](#files)
  - [About tools/](#about-tools)
- [In the MPLAB X simulator](#in-the-mplab-x-simulator)

## Files

Since the N+1 restructuring (27.09.2026) the sources sit under `src/`, one folder per
role — see "The board" above for the folder list and `CLAUDE.md`'s module table for
which file may call which. The table below is the reading order, not the full list:

| Path | Contents |
|---|---|
| `src/app/main.c` | start-up sequence and the main loop — the order of the inits, and why |
| `src/app/board.h`, `src/boards/board_cfg.h`, `src/boards/ev74h48a.c`/`ev17p63a.c` | board-specific choices: `board.h` for the compile-time ones (`ADC_INSTANCE`, `ADC_PINSEL`, `ADC_SAMC`, the LED and console pins), `board_cfg.h`/the two `.c` files for the one that turned out safe as run-time data — the boot sample rate as PLL1's output dividers |
| `src/app/config_bits.c` | every configuration word of the device, with the reason for each value — and why two of them are written as numbers |
| `src/drivers/clock.c/.h` | FRC → PLL1 320 MHz (ADC) and PLL2 200 MHz (CPU), the switching order, the clock-fail interrupt, the ADC clock's rate control (`clock_adc_set_pll()`, PLL1's output dividers — the knob that works) and `clock_adc_set_div()` (the CLKGEN6 divider, which does not change the rate on this silicon and is kept only so the behaviour can be reproduced) |
| `src/drivers/adc.c/.h` | the ADC core: channel 0 in Integration mode, burst trigger, input/sample-time register |
| `src/drivers/dma.c/.h` | DMA channel 0: address window, Repeated One-Shot mode, HALF/DONE interrupt, status flags — knows no ADC and no buffer |
| `src/sim/sim_dma.c`, `src/core/sim.h` | **simulator build only:** stand-in for `dma.c` that produces buffer halves (1 MHz sine) and the ping-pong check; see "In the MPLAB X simulator" |
| `src/core/pingpong.c/.h` | the two-half buffer's bookkeeping on its own since P9.1: which half just completed, the guard-word check, the main-loop service counters — no driver include, the buffer is passed in |
| `src/core/capture.c/.h` | the measurement: wires ADC and DMA together, the DMA event handler and the burst restart, start/stop/input, the buffer itself (with guard words), and `capture_chain_halt`/`_resume` — pausing and restarting the chain stream's trigger in place, for the GUI's grab cycle — what the console may read and control |
| `src/lab/meter.c/.h` | the counters, processing cost and rate measurement, out of `capture.c` on P9.3 |
| `src/core/acquisition.c/.h` | the rate setters, the variant matrix, and the standing chain stream `chain_stream_*()` (out of `chaintest.c` on P9.4) |
| `src/core/routing.c/.h` | the routing core: which resources (DMA, SCCP, DAC output, UREF, RAM) a route needs, checked and refused before any driver call; `route list`'s data source |
| `src/lib/crc16.c/.h` | CRC-16 over a sample block, for the `blk`/`stream grab` binary transfer |
| `src/lib/fmt.c/.h`, `src/lib/stats.c/.h`, `src/lab/tri_eval.c/.h` | the printf-free formatting helpers, min/max/mean over a completed half, and the chain test's triangle evaluator — hardware-free, each with a host test under `tests/host/` |
| `src/lib/frame.c/.h` | the binary frame writer `blk`/`stream grab` share: header, chunked payload with the CRC folded in, CRC tail |
| `src/lib/iir1.c/.h`, `goertzel_f.c/.h`, `goertzel_i.c/.h`, `detect.c/.h`, `wavegen.c/.h` | a first-order IIR filter, damped Goertzel in float and in Q16 fixed point, a hysteresis pulse detector, and a signal-generator table — included in every build, cross-checked against a Python reference on the host, and not yet called from anywhere: the building blocks for the multi-channel signal chain planned for N+4 |
| `src/drivers/sccp.c/.h` | SCCP1 as the chain test's trigger source (clock, mode, event), its timer and compare interrupts as event counters |
| `src/lab/chaintest.c/.h` | the chain test itself — `chain all`, the `@` log line format, and `chain_stream_grab_begin`/`_end` (in `src/core/acquisition.c` since P9.4) — one freeze/send/release cycle of a ping-pong pair for `stream grab`; see "The chain test" below |
| `src/lab/bench.c/.h` | the back-to-back test suite (`test ...`, `sweep`, `matrix`), out of `cli.c` |
| `src/drivers/led.c/.h` | LED0 |
| `src/core/diag.c/.h` | stop codes (`fail()`), trap and unhandled-interrupt handler, boot-stage record, reset cause, the register-dump visitor |
| `src/port/log.h`, `panic.h`, `wait.h`, `regs.h` | the port layer: the one path (`port_log*()`, `port_panic()`, `PORT_WAIT_WHILE`, a register visitor) by which a driver under `src/drivers/` may log, wait, stop or dump its registers, without including the console — implemented by `src/app/port_impl.c` |
| `src/drivers/timebase.c/.h` | Timer1 as a 12.5 MHz stopwatch — the independent clock the delivered sample rate is measured against (`test rate`, `test sweep`, and the window length of the DAC test). It does **not** pace the ADC |
| `src/drivers/dac.c/.h` | DAC1 and DAC2 in Triangle Wave mode on their pins DACOUT1 = RA1 and DACOUT2 = RA8 (CLKGEN7 as their shared clock), one table for both units. The DAC test itself instead routes DAC2 through `UREFCON` onto the chip's internal UREF line, where every ADC core can sample it as `ANn7` — no pin, no wire, no core switch |
| `src/lab/dactest.c/.h` | captures one contiguous buffer with the stream stopped from the DMA interrupt, then judges whichever DAC is running (`dac_active()` picks DAC2 first if both run): a changing signal, even steps, no jump, and the triangle period measured from the data. `[dactest]` lines, PASS/FAIL |
| `src/core/gui_link.c/.h` | the GUI's binary transport: `stream grab`'s body, built on `frame.c`, out of `cli.c` |
| `src/lab/b2b_link.c/.h` | `snap`/`rate`/`blk`, the back-to-back mode's binary transfer, out of `gui_link.c` on 02.10.2026 |
| `src/core/cli.c`, `console.h` | the console: on top of `src/drivers/uart.c`, the receive callback, the core's commands and their reply framing |
| `src/lab/cli_lab.c` | the lab's commands (`start`, `stop`, `samc`, `input`, `core`, `clk`, `pll`, `selftest`, `dactest`, `chain`, and through their own files `sweep`/`test` and `snap`/`rate`/`blk`), registered after the core's through `cli_register_lab()` |
| `src/core/example_main.c` | the core build's `main()`: the same start-up without the lab, then `capture_service()` in the loop — a customer's starting point |
| `docs/CORE.md` | **taking the core into your own project**: what to copy, the glue to write, where the processing goes, how to build |
| `src/drivers/uart.c/.h` | UART2 on the MCP2221A channel: pins/PPS, the baud generator, the non-blocking transmit and bounded flush, the receive interrupt — out of `cli.c` on P5.1 |
| `src/core/cmd_parser.c/.h` | the command parser, unchanged from [zabooh/cmd_parser](https://github.com/zabooh/cmd_parser) (Apache 2.0) |
| `adc_dma_40msps.X/` | MPLAB X project — build, program and debug from here |
| `tools/export_core.py` | the customer's handover from one commit: `build\core-<rev>.zip` with the core, the glue templates, `core_example.X`, `docs/CORE.md` and the GUI, compiled from the unpacked ZIP as a check |
| `core_example.X/` | the core alone as an MPLAB X project (EV74H48A and EV17P63A, `example_main.c`, -O1) — a customer's starting point, `docs/CORE.md`; generated from `adc_dma_40msps.X` by `tools/gen_core_project.py` |
| `tests/host/` | host-side (gcc) unit tests for every module in `src/lib/` plus `pingpong`/`routing`, run by `tools\hosttest.bat` |
| `tests/trace/` | the register-trace harness: golden logs of every register write a driver makes, reproduced bit-for-bit after each change (`tools\trace.bat`) |
| `docs/TROUBLESHOOTING.md` | **what to do when it does not work** — including where we doubt our own code |
| `docs/HARDWARE-LOG.md` | every run on the board, dated: what the log said, what was changed because of it |
| `docs/FIRMWARE-STRUCTURE.md`, `docs/REFACTORING-PROPOSAL.md` | the analysis of the pre-N+1 structure and the plan that led to the layout above; kept as the record of why it looks like this |
| `docs/IMPLEMENTATION-PLAN.md` | the N+1 restructuring plan and its task-by-task status; where "done" is checked against, for every task |
| `CLAUDE.md` | working notes for continuing with Claude Code: module rules, build and verification steps, open questions |
| `docs/*.png`, `docs/*.mmd` | the block diagrams above, with their Mermaid sources |
| `tools/sim_trap.py` | drives the simulator build in MDB: `--smoke` for the short boot/console check (**[SMOKE]**, under a minute), the default for the ~7-minute ping-pong acceptance run (**[SIM]**); see "In the MPLAB X simulator" |
| `src/core/user_filter.h`, `user_filter.json` | the user filter (`sigproc user`), **generated** by `tools/filterdesign` - the checked-in one is the default |
| `tools/filterdesign/` | the IIR filter design tool: `fdesign/` (C, the design library), `gui/` (NiceGUI, with the dsPIC33 tab, `firmware.py`); `filterdesign.bat` starts it |
| `tools/` | command-line build without the IDE, the host test/trace runners, the GUI; **ignore this unless you want it** |

### About `tools/`

Only needed to build without MPLAB X:

```
cd tools
python setup.py          # find compiler and pack, configure build.bat and Makefile
build.bat                # build
```

`setup.py` scans for installed XC-DSC compilers and dsPIC33AK-MP packs, in both
places they can live (`%USERPROFILE%\.mchp_packs` and MPLAB X's own `packs` folder),
lets you choose, and writes the paths into `build.bat` and `Makefile`. With
`--verify` it also runs a real test build. `--list` just shows what it found.

Two things that cost us time there, in case you build without the IDE:

1. `-mdfp` must point at the **`xc16` subdirectory** of the pack, not the pack root —
   otherwise the compiler reports "does not seem to support the selected device"
   although the pack does contain it. `c30_device.info` lives one level down.
2. The **linker script must be given explicitly** with `-T`
   (`support/dsPIC33A/gld/p33AK512MPS512.gld` inside the pack). Without it the
   compiler links against a 30F architecture and stops with "incompatible with
   30Fxxxx output".

## In the MPLAB X simulator

The simulator has no PLL, no ADC conversion and no DMA transfer, and in this project it
does not dispatch interrupts either (any pending interrupt aborts the run with
`E0110-SIM: Failed to execute instruction`; MPLAB X v6.35, checked 22.09.2026). So the
DMA interrupt — the only producer of data on silicon — never runs there. The simulator
build therefore swaps one module: `sim_dma.c` replaces `dma.c`. It implements the same
`dma.h` interface without a DMA and delivers a buffer half whenever the firmware would
otherwise wait for one (`SIM_DMA_TICK()` in `sim.h`, empty on silicon): a 1 MHz sine
on the measurement input, a flat 3840 on the self-test input, through the same
`dma0_event()` path the interrupt uses. Everything above that — counters, the burst
restart, `capture_service()`, the self-test, the console — runs unchanged. The clock and
ADC waits are no-ops (`WAIT_WHILE` in `diag.h`), and three spots in `cli.c` skip what
the simulator's UART model cannot do (no receiver, `TXMTIF` never set).

Two ways to build it:

- MPLAB X: configuration **`sim`** (tool Simulator, `dma.c` excluded, `sim_dma.c`
  included, `__MPLAB_DEBUGGER_SIMULATOR=1` defined).
- Command line: `tools\build.bat sim` or `make -C tools sim` → `build\adc_dma_40msps_sim.elf`.

`tools\sim_trap.py` drives that ELF in MDB, the command-line debugger, routes UART2 to a
file and prints the result. The expected log ends with

```
[selftest] mean on internal 15/16 VDD (expect ~3840): 3840
[simtest] halves compared against the sine vector: 100
[simtest] full ping-pong buffers: 50
[simtest] halves with a mismatch: 0
[simtest] PASS: ping-pong order and data intact
```

The **ping-pong check** is what the simulator build is for: `sim_dma.c` writes a known
vector, so every half that `process_buffer()` receives through `capture_completed_half()`
is compared with it, and the phase must continue from the previous half (1024 mod 40 =
24 samples). A half served twice, two halves swapped, a wrong pointer or a corrupted
region all show up as a mismatch with the index. The negative test,
`sim_trap.py --fault 65536`, drops one sine sample mid-run and must end in
`[simtest] FAIL` with a mismatch at index 0. DMA status masks written the same way
(`--fault 8` = OVERRUN) exercise the error counters.

What it does not cover: timing and throughput, the interrupt path, the DMA address
window and real DMA errors, the clock tree — everything the hardware run is for. A
simulator run takes about 2.5 minutes for the 100 halves.
