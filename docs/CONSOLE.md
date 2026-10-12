# The console and the chain test

Every command of the board's console, what a test run looks like, and the chain test. Moved out of the top-level README on 13.10.2026, unchanged; only links were adjusted to the new place.

## Contents

- [The console](#the-console)
  - [The parts of a test, and what each one proves](#the-parts-of-a-test-and-what-each-one-proves)
  - [What a run looks like](#what-a-run-looks-like)
  - [The DAC test measures inside the chip](#the-dac-test-measures-inside-the-chip)
- [The chain test - one command, one board run](#the-chain-test---one-command-one-board-run)

## The console

UART2 on the board's MCP2221A USB-UART channel, 115200 8N1, no flow control. The parser
is [zabooh/cmd_parser](https://github.com/zabooh/cmd_parser), copied unchanged except for
one line (the command table is 32 entries instead of 16 — `CMD_PARSER_MAX_COMMANDS`,
`cmd_parser.h`; 29 commands, including `route`, `siggen` and `sigproc`, plus the built-in `help` are
registered — 30 of 32 slots, 2 free, `nano-board`). It
runs in the UART receive interrupt, below the DMA interrupt — which is why a rate that
overruns makes the console unresponsive, and why the firmware boots idle. Output goes the other
way through an 8 KB ring buffer that the UART transmit interrupt empties (since
01.10.2026, `src/drivers/uart.c`): a command writes its reply and returns, so a long
reply no longer holds the CPU - `help` while streaming used to cost the main loop 550
halves at 8 MSPS, now none. The measuring commands (`chain`, `test`, `sweep`, `selftest`, `dactest`,
`snap`) still send polled, so nothing transmits while they measure; so do `fail()` and
the trap handler. Ctrl+C cuts only output that is still being generated, not what is
already in the ring.

| Command | Does |
|---|---|
| `help` | the command list |
| `version` | build id, git revision, board, configuration |
| `status` | run state, counters, the clock, the receive diagnostics, and — since the board-run preparation (BR.6) — the stack high-water mark and its margin to `SPLIM`, the sample buffer's address/alignment/guard-word check, and the boot stage/trap/`chain all` stage of the current run |
| `regs` | clock, ADC, DMA, DAC, UREF and UART registers |
| `siggen` | the signal generator's status: on/off, DAC, table size, play rate (set and actual), the parameters, the table's min/max, DMA 2 and SCCP2 state, the measured transfers per second. A table computed on the target (`lib/wavegen`, the `tab_wave_gen.py` formula) is played by DMA channel 2 into a DAC, paced by SCCP2, with no CPU involvement |
| `siggen set <f0\|h2..h7\|decay\|amp\|lo\|hi> <value>` | one generator parameter per line (the console line is 64 characters); decimals without an exponent, `lo`/`hi` are DAC codes. Takes effect with the next `siggen on` |
| `siggen on <dac 1\|2> <n 2..8192> <play_hz 100..1000000> [snap] [force] [oc]` | compute the table and play it on DACOUT1 = RA1 or DACOUT2 = RA8; `snap` moves f0 to a whole number of periods in the table, `force` allows `lo`/`hi` outside the DAC's 205..3890, `oc` paces SCCP2 in 32-bit output compare (dead on silicon; the default is the dual 16-bit timer). Refused while a route uses the same DAC (`stream on` on DAC2) |
| `siggen off` \| `siggen regs` | stop the generator; dump DMA 2 and SCCP2 registers |
| `sigproc [lp\|hp\|bp\|user\|off]` | the filter on every completed half, in place: three at fs/8 (`on` = `lp`), or `user`, the one from `tools/filterdesign` - its status then adds `user:` (description), `user_fs:` (the rate it was designed for) and `user_id:`; `sigproc` alone = status: filter, Goertzel on/off, its threshold and last result |
| `sigproc gz on\|off` \| `sigproc gz thr <lsb>` | the Goertzel detector for a tone at fs/16 on the input, and its threshold (1..4095, default 100 LSB) |
| `route list` | the active route (source, core, pinsel, DAC, sink) and the resource table — which DMA channel, SCCP, DAC output and UREF are in use, RAM used vs. budget (`docs/DESIGN-MULTICHANNEL.md`'s routing core) |
| `test [part] [halves]` | run a part of the measurement, or `all` — see below |
| `pll <p1> <p2>` | **the sample rate**: PLL1 output dividers, 1600 MHz / (p1·p2), p1 ≥ p2, both 1…7 |
| `clk <100…1000>` | the CLKGEN6 divide ratio ×100. Arrives in the register and does **not** change the rate on this silicon; kept for the record |
| `start` / `stop` | the burst stream |
| `input <0…15>` / `samc <0…31>` | analog input and sample time |
| `core <1…5> [pinsel]` | switch the ADC core |
| `buf [n]` | samples per buffer half, 16…1024 - the 8 KB hold two ping-pong pairs since 01.10.2026 (2048, one pair, that morning; 1024 before) |
| `dac <1\|2> <on\|off> [low] [high] [slpdat]` | triangle on DACOUT1 = RA1 or DACOUT2 = RA8, both sharing CLKGEN7 (the last unit to stop switches it off). `slpdat` is the step per DAC clock, so **larger is faster** (default 8; the DAC test itself starts DAC2 at 64, since 8 leaves the triangle almost standing still inside one captured buffer) |
| `dactest [halves]` | the DAC test on its own, against whichever DAC is active (`dac_active()` picks DAC2 first if both run) |
| `stats` / `dump [count] [offset]` | the completed half: min/max/mean, or the raw values |
| `blk [n]` | a contiguous block of up to 2048 samples (one ping-pong pair) as binary, with a CRC — `docs/PLAN-BINARY-TRANSFER.md`. The back-to-back capture command; kept for a terminal, no longer used by `tools/adc_gui.py` (25.09.2026 on, the GUI only drives the triggered chain, `stream grab`) |
| `chain all\|<n>\|from <n>\|run <ksps> [s]` | the chain test (`chaintest.c`) — see "The chain test" below |
| `stream on <ksps>\|off\|grab` | the chain as a standing stream: start it, stop it, or send one ping-pong pair to the GUI while the stream carries on in the other pair — see "The chain test" below |
| `clear` | zero the error counters |
| `led on\|off\|auto` | LED0 |
| `reset` | software reset |

### The parts of a test, and what each one proves

| `test …` | Proves |
|---|---|
| `self` | the chain is wired up: clock, ADC, DMA, interrupt, buffer. It samples a **constant**, so it cannot tell a working converter from a result register that never changes |
| `clock` | that a CLKGEN6 divider write arrives and is confirmed. It passes on this silicon **and the rate still does not follow** — passing here proves the register holds the value, nothing more |
| `clkoff` | whether CLKGEN6 feeds the ADC at all: the generator is switched off and the ADC is asked to convert anyway. On this board it **keeps converting** |
| `rate` | the delivered rate at the current setting, from one clean burst timed with Timer1 |
| `sweep` | the rate ladder from the slowest setting up, with overrun, late and missed per point, and the rate measured both clean and under load |
| `dac` | **the one that proves the data**: a known triangle through the chain, captured as one contiguous buffer, judged for a changing signal with even steps and no jump |

### What a run looks like

```
[boot] adc_dma_40msps Sep 24 2026 13:22:59 git b57e310 (master)
[boot] RCON: 0x00000080
[boot] reset cause: EXTR
[boot] pll1 postdiv1: 7
[boot] pll1 postdiv2: 7
[boot] adc clock Hz: 32653061
[boot] sample rate ksps (back-to-back): 4081
[boot] READY - nothing is converting, the console has the CPU
> dac on 64
dac slpdat: 64
dac period ns: 54880
> test dac
[dactest] DAC2 routed to the internal UREF line, INSEL: 7
[dactest]   measured on this core's AN7, ADC core: 3
[dactest]   samples in the window: 2048
[dactest] window ns: 513280
[dactest] sample rate ksps in this burst: 3990
[dactest] min: 2411   max: 3851   peak-to-peak: 1440
[dactest] largest step between two samples: 113
[dactest] slope reversals: 1
[dactest] every 64th sample across the window:
   2418 2541 2603 2714 2816 2960 3044 3128 3260 3386 3496 3581 3706 3789 3851
   3688 3581 3512 3397 3281 3195 3063 2998 2861 2755 2666 2539 2416 ...
```

That last block is the point of the whole project: a triangle, sampled by the ADC,
carried by the DMA into RAM, complete and in order.

### The DAC test measures inside the chip

`UREFCON.INSEL` puts one of DAC1…DAC8 on the device's internal UREF line, and `ADnAN7`
is the UREF input of **every** ADC core (Table 16-2). So the test routes DAC2 to UREF and
samples AN7 on whatever core is already in use: **no pin, no wire, no core switch.**

The pin route exists too and is documented in `board.h`: DACOUT1 is AD5AN1 = RA1 (shared
with PGC2), DACOUT2 is AD5AN3 = RA8 — one physical pin carrying both the DAC output and
the ADC input, so the loop closes without a wire. On the EV74H48A that pin also goes to
capacitive touch pad 2, which loads it; the internal route has neither problem.

Two things about the DAC are modelled wrongly in `dac.c` and are **not** used for any
verdict: the computed triangle period is about eight times off what the capture shows,
and `DACLOW` is not reproduced — the triangle's upper end matches `DACDAT` exactly, its
lower end does not match `DACLOW` at all. The test measures the period from the data
instead and prints the computed one beside it for the record.

## The chain test - one command, one board run

The firmware carries a test of the chain the example is about - SCCP1 as the
sample clock, the ADC converting once per trigger, the DMA moving every result
into the ping-pong buffer, the CPU processing each half - with the on-chip DAC2
as the signal, on RA8 (DACOUT2 = AD5AN3, ADC core 5). It checks every link on
its own at low rates first, then every rate from 100 kSPS to 40 MSPS, and ends
with an attempt at the real thing. What each stage checks and why:
`docs/CHAIN-TEST-PLAN.md`.

**For the person at the board:**

```
git pull
MPLAB X: configuration EV74H48A_Curiosity_Platform_MPS512, build, program
terminal on the MCP2221A COM port, 115200 8N1, logging to a file
wait for "[boot] READY", then type:   chain all
wait for "@END" (under a minute), send the log file back
```

If it stops without `@END`, reset the board and send the log including the new
boot banner: the next boot prints the stage the run was in
(`[boot] WARNING the last 'chain' run ended without @END, in stage S...`), and
`chain from <stage>` continues from there.

**The chain as the example itself:** `stream on <ksps>` starts SCCP1 -> ADC ->
DMA -> ping-pong at about that rate (the nearest 160 MHz / N, 1..40000 kSPS),
with the DAC triangle on RA8 as the signal, and returns; from then on the main
loop processes every half, exactly as an application would, and the console
stays free. `stream` shows its state - rate, seconds, halves, overrun, late,
missed, processing time, free CPU cycles per sample, min/max/mean of the last
half - and `stream off` stops it and restores the boot configuration. Printing
the report takes the main loop's CPU for a few milliseconds, so at high rates a
report can itself cost a few halves; they show as `missed` in the next one.

**`stream grab`** is the GUI's own command: with a stream already on, it halts
the trigger (trigger first, as `stream off` does), sends the half that stood
still as one binary frame - `GRAB n=... from=... ksps=... ov=... late=...
missed=... halves=... xfer=... slp=... dachz=...`, then the 2·n sample bytes
and a CRC line, framed exactly like `blk` (`docs/PLAN-BINARY-TRANSFER.md`) -
and restarts the same trigger. The counters in the header are *per cycle*
(since the previous grab), not the running total. See "The GUI's chain
tile" below for what uses it.

Other forms: `chain <n>` runs one stage (0..9), `chain run <ksps> [seconds]`
runs the chain at a chosen rate (the nearest 160 MHz / N) for as long as asked,
with one status line per second, printed after the stream so that printing does
not disturb it.

**The log** is one line per result, `@S<stage>.<n> key=value ... -> PASS|FAIL|SKIP|INFO`,
about 170 lines when everything passes; a window that fails the grid check is
added as a `@DUMP` of its samples. `python tools/eval_chain.py <log>` re-judges
every line from its fields, re-evaluates every dumped window and lists what the
run says about the open questions (`--png DIR` plots the dumped windows).
`python tools/eval_chain.py --selftest` checks the evaluator itself.

**Stages:** S0 preconditions (Timer1, every clock measured by the chip's clock
monitor, core 5, RA8) - S1 SCCP1 alone - S2 SCCP1 -> ADC at 1..100 kHz with both
ends counted and the DAC stepped by the CPU - S3 ADC -> DMA -> buffer at
100 kHz - S4 triggers against transfers at every rate - S5 the DAC triangle in
the data, turning points to a fraction of a sample - S6 one second of stream
with the CPU processing, per rate - S7 start, stop, restart, rate change - S8
the old open questions (CLKGEN6 divider and CLKGEN6 off measured at the clock
itself, back-to-back repeats) - S9 the attempt, 15 s at the best rate and at
8 MSPS, and the registers the chain ran with.
