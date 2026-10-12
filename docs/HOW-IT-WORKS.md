# How the example works, and what it can and cannot do

Clock tree, ADC, DMA and CPU, the sample rates you can get, what to measure, and the
device's traps - for the **triggered chain**, the example's data path since 25.09.2026:
SCCP1 triggers one ADC conversion per sample, DMA channels 0 and 1 carry the results as a
hardware ping-pong pair into RAM, and the CPU processes each completed half.

Rewritten on 13.10.2026; until then this text was the top-level README's and described the
older back-to-back burst mode. That mode is still in the firmware for a terminal (`start`,
`test`, `blk`, `pll`); its description is kept in the [appendix](#appendix-the-back-to-back-burst-mode).
What has been measured on the board, and what is open: `ANALYSIS.md` section E and
`HARDWARE-LOG.md`.

## Contents

- [How it works](#how-it-works)
  - [1. Clock tree](#1-clock-tree)
  - [2. ADC — one conversion per SCCP1 trigger](#2-adc--one-conversion-per-sccp1-trigger)
  - [3. DMA into a ping-pong buffer](#3-dma-into-a-ping-pong-buffer)
  - [4. What the CPU does, and what to measure](#4-what-the-cpu-does-and-what-to-measure)
- [Which sample rates you can get](#which-sample-rates-you-can-get)
- [The point of the whole thing](#the-point-of-the-whole-thing)
- [What to measure](#what-to-measure)
- [If the bandwidth is not enough](#if-the-bandwidth-is-not-enough)
- [What this code does not do](#what-this-code-does-not-do)
- [Errata](#errata)
- [One trap worth knowing about](#one-trap-worth-knowing-about)
- [Appendix: the back-to-back burst mode](#appendix-the-back-to-back-burst-mode)

## How it works

### 1. Clock tree

![Clock tree](01_clock_tree.png)

The part that differs from many other devices: **the fast peripherals do not hang off
the system clock.** There are two dedicated PLLs and fourteen clock generators, so
320 MHz at the ADC alongside a 200 MHz CPU is no contradiction. This example uses both
PLLs — PLL1 at 320 MHz for the ADC path, PLL2 at 200 MHz for the system — so neither clock
needs a fractional divider.

**The switching order matters and is easy to get wrong.** Page 778 requires `PLLSWEN`
(apply input and feedback dividers), then `FOUTSWEN` (apply output dividers), then
`NOSC`, then `OSWEN`. Setting only the last two does not produce an error — it silently
leaves the old dividers in place and the part runs at the wrong speed.

Which generator feeds what is not stated in one place:

- **CLKGEN1 is the system clock** — §12.4.9, page 795: *"Clock Generator 1 is the
  clock source for the system clock (sys_clk) and peripheral clock."*
- **CLKGEN6 is the ADC clock** — Table 16-1, page 1223, column "Clock Source",
  together with "Max Input Clock 32 MHz to 320 MHz".
- **CLKGEN13 clocks SCCP1**, the sample trigger: PLL1's 320 MHz divided by 2, **160 MHz**
  (`CCP1CON1.CLKSEL = 1`). Not the peripheral clock: the trigger's resolution is what
  sets the selectable rates (see *Which sample rates you can get*).
- **CLKGEN7 clocks the DACs** at 400 MHz from PLL1's VCO divider - the DAC's minimum;
  320 MHz, as in the first version, is below it.

TAD derives from the ADC input clock: **TAD = 4 / F_IN** (parameter AD50, Table 40-39,
page 2034). At 320 MHz that is 12.5 ns, which is also the minimum — more than 320 MHz
is not specified (Table 40-24, page 2016). Hence the datasheet's 40 MSPS (AD51,
throughput including 1.5 TAD conversion time). **Triggered one conversion at a time, the
converter reaches only 18 to 20 MSPS on the board** (run 19): the conversion does not fit a
shorter trigger period.

A useful cross-check: the datasheet measures its own current consumption at exactly
this operating point — *"Input frequency 320 MHz, ADC clock 80 MHz, TAD 12.5 ns"*
(DC120/DC121, page 2008). So this is the intended setting, not brinkmanship.

`CLKxDIV` also has a 9-bit fractional divider `FRACDIV` next to the integer `INTDIV`,
so non-integer ratios are possible — but this example does not need one: the system and
ADC clock generators take their PLL output straight through, `CLK1DIV = CLK6DIV = 0`.

### 2. ADC — one conversion per SCCP1 trigger

`MODE = 0` is Single Conversion mode: **each trigger starts exactly one conversion** - no
burst, no count, nothing for software to restart (`adc_set_mode_single()`, `adc.c`).

| Field | Value | Why |
|---|---|---|
| `MODE` | 0 | Single Conversion: one conversion per trigger |
| `TRG1SRC` | `0x20` | "SCCP1 OC/IC Event" per the device pack's ATDF (value group `AD_CH_CON1__TRG1SRC`). The datasheet's trigger table names another code; the board sided with the ATDF. `0x22` is SCCP3. |
| `TRG2SRC` | 0 | unused in this mode (page 1322) |
| `IRQSEL` | 0 | the channel event after **every** conversion - the event that triggers the DMA |
| `SAMC` | 0 (test input) | sample time in TAD. **More than 0 lowers the real rate without any counter noticing**: at a set 8 MSPS with SAMC 8 or 31 the spectrum showed about 5 MSPS (04.10.2026). Raise it only with a high-impedance source, and check the rate. |

The trigger is **SCCP1 in timer mode**: it counts its 160 MHz clock up to the period
register `CCP1PR = N - 1` and raises its special event at every rollover
(`CCP1CON2.AUXOUT = 2`), so the ADC converts once every N clocks: **rate = 160 MHz / N**.
`sccp1_start()` (`sccp.c`) sets it; `CCP1RB`, the compare point, is written halfway in
both modes so that a mode change cannot inherit one beyond the period. **Output-compare
mode produced no events on the board** - use timer mode.

The per-conversion result is `ADxCH0RES[11:0]`. `ADxCH0DATA` is the accumulator of the
integrating and oversampling modes (page 1270) and is **not** what the DMA reads.

The stream reads one core and one input: by default core 5, PINSEL 3 = RA8, where DAC2
plays the firmware's test triangle inside the chip, so no wiring is needed. `stream on
<ksps> <core> <pinsel> <samc>` reads any other core and input.

### 3. DMA into a ping-pong buffer

**Two ping-pong pairs for the triggered stream (since 01.10.2026).** The 8 KB buffer holds
pair A and pair B, each a ping half and a pong half of up to 1024 samples. `stream on` runs
two DMA channels as the dsPIC33A's hardware ping-pong pair (DS70005591D 13.4.11): channel 0
fills the ping half, channel 1 the pong half, and the hardware hands over between them
without a lost sample (checked on the board with the DAC triangle up to 16 MSPS). For a
`stream grab` the channel that is waiting is pointed at the other pair, so the pair just
completed stands still and goes to the GUI while acquisition and processing carry on in
the other pair - nothing stops, the processing never sees a gap in its input. The GUI
sees snapshots of the signal, one pair at a time. The back-to-back commands (`start`,
`test`, `blk`, ...) still use one channel on pair A, as in the appendix.

"When one DMA channel completes its operation, it triggers the other active channel's
hardware enable input" (13.4.11, page 841): at the end of its half a channel reloads its
address and count at once, stays enabled with `PCHEN = 0` and waits; the two alternate
with no software at all (`dma0_pp_init()`, `dma.c`). **A write to a running channel's
`DMAxDST` moves its live pointer at once**, so `stream grab` only ever moves the waiting
channel (`dma0_pp_set_dst()`).

![DMA path](03_dma_path.png)

Both channels are set up alike:

| Field | Value | Why |
|---|---|---|
| `DMALOW` / `DMAHIGH` | the buffer's window | **mandatory.** Both reset to 0; every transaction is checked against them (page 829, step 5) and an access outside sets `ADRERR` and clears `CHEN` (pages 810, 826). They exist once for all channels: the window is the union of the ADC buffer and the signal generator's table, which lies directly below it. |
| `DMAxSEL` | "ADCn Done CH0" | the trigger: `0x2F`, `0x35`, `0x3B`, `0x41`, `0x48` for ADC core 1 … 5 (ATDF value group `DMA_SEL__CHSEL`), following the core the stream reads |
| `DMAxSRC` | `&ADnCH0RES` | the per-conversion result register |
| `SIZE` | 1 | **16-bit transfers** (page 812) |
| `SAMODE` | 0 | source address stays put |
| `DAMODE` | 1 | destination increments |
| `TRMODE` | 1 | **Repeated One-Shot: one transfer per trigger** (page 832). Was 3, Repeated Continuous - a whole block per trigger - until 25.09.2026; every rate and overrun figure of runs 1 to 18 was measured in that wrong mode. |
| `RELOADD`, `RELOADC` | 1 | back to the half's start after each block, in hardware (page 812) |
| `PPEN`, `PCHEN` | pair mode | channel 0 and 1 hand over to each other (13.4.11) |

**On 2 bytes per sample:** the DMA handles 8, 16 and 32-bit transactions, selected
through `SIZE[1:0]`. A 12-bit result therefore costs 2 bytes, not 4. `AD3CH0RES` is
32 bits wide with `RES[11:0]` in the low half and `RESF[11:0]` in bits 31:20 (register
summary, page 1229), so the 16-bit read of the low half is the sample.

**On the two halves:** the first version of this code used two separate buffers and
rewrote `DMA0DST` from the ISR to swap them. That cannot work at this rate — with
`RELOADD` the DMA restarts at the old address the moment a block completes, samples
keep arriving every few tens of nanoseconds, and by the time the ISR rewrites the pointer
a dozen of them have landed in the buffer the CPU is reading. The hardware has the right
tool for this: the ping-pong pair, and **no address is touched by software while a
channel runs**.

**On the status flags:** `DMAxSTAT` bits are *R/C/HS* — set by hardware, **cleared by
writing 0** (legend page 815; Example 13-4 page 835 does `DMA0STATbits.DONE=0`).
Writing 1, as the first version did, leaves them set. This code clears them by writing
the word once with 0 only in the bits to clear (`dma0_clear()`), never by a bit-field
read-modify-write, and at the start of the handler.

At 8 MSPS one half of 1024 samples is 128 µs of signal, an interrupt every 128 µs per
channel. The handlers only clear flags, note which half is complete and count errors:
`_DMA0Interrupt` 46 instructions, `_DMA1Interrupt` 41, no indirect call - deliberately
short, because at this rate a long ISR becomes the cause of the next overrun.

### 4. What the CPU does, and what to measure

![CPU and counters](04_cpu_and_counters.png)

**Your own processing goes into `src/core/sigproc.c`** (`sigproc_block()`). The firmware
calls it from the main loop once per completed half - ping and pong alike - with the
half's samples, its length and which half it is. It has one half period to return
(1024 samples at 8 MSPS: 128 µs, 25 CPU cycles per sample at 200 MHz); `status`, the chain
test's load figures and the GUI's "CPU load" chip (the GRAB frame's `load=`, per mille of a
half period) show what it takes, and `missed` counts the halves it was too slow for. The
loop around it costs 3.0 cycles per sample, 12.3 % of the half period at 8 MSPS (run 20).
`src/core/sigproc.h` has the rules.

As an example it holds, selectable since 02.10.2026 (`sigproc lp|hp|bp|off`, the GUI's
**signal processing** card), one of three **4th-order Butterworth filters at fs/8** -
low-pass, high-pass, or a band-pass one octave wide around fs/8 (high- and band-pass
centred on mid-scale, 2048) - and, independently, a **Goertzel detector for a tone at
fs/16** (`sigproc gz on|off`, `sigproc gz thr <lsb>`), which measures the input before the
filter and reports the tone's amplitude, its share of the signal's power and detected or
not (GRAB `gz=`/`gzs=`/`gzd=`, the card's fs/16 chip). Being fractions of fs, all of them
follow the sample rate by themselves. Coefficients: `tools/sigproc_design.py`. Each filter
is two biquad sections, float on the FPU, the state carried from block to block (the
ping-pong stream has no gaps) and restarted where the firmware reports one (`info->gap`)
or the filter changes. On the board (02.10.2026, the signal generator through DAC2 -> RA8
at 400 kSPS) all three match their design to three decimals at fs/32, fs/16, fs/8 and
fs/4, and the Goertzel finds a tone at fs/16 (1341 LSB, 100 % of the power) and nothing at
the other three. The GUI's **setup** list has four Goertzel checks that drive the signal
generator for it.

A fourth filter, `sigproc user` (03.10.2026), is whatever you design in
`tools/filterdesign` - see [Your own filter](GUI-MANUAL.md#your-own-filter-the-firmware-side).
Its coefficients hold at its design rate only.

The result goes back into the same half: `stream grab` then sends the processed data to
the GUI (the frame says which filter: `proc=1` low-pass, `2` high-pass, `3` band-pass, `4`
the user filter), with no second buffer. `chain all` and `test` judge raw samples - switch
the processing off for them.

**What the processing costs**, measured on the board as `load=` (main build at -O1; the
IDE build at -O0 doubles it):

| Processing | CPU cycles per sample | Clean up to |
|---|---|---|
| the loop alone | 3.0 | 8 MSPS at 12.3 % load (run 20) |
| Goertzel at fs/16 | about 7 more | 26 % load at 8 MSPS |
| built-in low/high/band-pass | about 63 | about 2 MSPS |
| user filter, generated dsPIC33A assembler | 56 | 3 MSPS |
| user filter, C float | 185 | 1 MSPS |
| user filter, fixed point 32 bit C | 250 | below 1 MSPS |

The user filter figures are for the 6th-order elliptic band-pass of 04.10.2026;
`ASM-FILTER-COMPARISON.md` has the run.

## Which sample rates you can get

All figures are **per ADC core**; the dsPIC33AK512MPS512 has five (Table 16-1, page
1223).

**The basis.** SCCP1 counts 160 MHz and the ADC converts once per period of N clocks:
**rate = 160 MHz / N**. `stream on <ksps>` takes the nearest N, at least 4 = 40 MSPS (`period_for()`,
`acquisition.c`); the GRAB frame and the GUI's **actual rate** chip report the rate that N
gives. The ADC clock stays
at 320 MHz for every rate (`acq_chain_setup()`).

| N | Rate | |
|---|---|---|
| 8 | 20 MSPS | above what the converter manages in this mode (18-20 MSPS) |
| 10 | 16 MSPS | lost triggers |
| 16 | 10 MSPS | a few hundred DMA overruns per 0.5 M transfers (run 19) |
| **20** | **8 MSPS** | **clean with the CPU processing: 15 s, 120 M samples, nothing lost (run 19)** |
| 40 | 4 MSPS | clean |
| 160 | 1 MSPS | clean |
| 1 600 | 100 kSPS | clean |
| 160 000 | 1 kSPS | the console's smallest rate (`stream on` takes whole kSPS) |

Between 8 and 20 MSPS the steps are coarse: 160 MHz / 17 = 9.41 MSPS, / 18 = 8.89 MSPS,
/ 19 = 8.42 MSPS. Below 1 MSPS they are fine enough for any rate in whole kSPS.
`CCP1PR` is 32 bits wide, so the trigger itself goes far below 1 kSPS; the console just
does not offer it.

**Where it degrades** (`ANALYSIS.md` section E):

- **Up to 8 MSPS** the stream is clean with the CPU processing every half.
- **10 MSPS**: run 19 had the triangle clean, run 20 did not reproduce it - open.
- **From about 10 MSPS** DMA overruns appear; in pair mode 16 MSPS gave 7 overruns in 12
  grabs (stochastic: 390 in one build, 0 in the next), 20 MSPS 56 overruns and 59 missed
  halves.
- **From about 16 MSPS** triggers are lost; the converter itself manages 18 to 20 MSPS in
  this mode.

Three caveats:

- The figures are per core. Five cores together are nominally 200 MSPS — whether the
  single DMA bus carries that is precisely the open question this example is meant to
  measure; it has only ever streamed one core.
- `SAMC` > 0 lowers the real rate below 160 MHz / N without a counter noticing (section 2).
- AD51 carries the footnote "design guidance only, not characterised or tested in
  manufacturing". 40 MSPS is the design target, not a tested limit.

## The point of the whole thing

One sentence in the datasheet matters more for this project than any ADC register,
§13.4.4 on page 825:

> *"While DMA channels can function independently to service different peripherals at
> the same time, they are still limited by the presence of a single DMA data bus and a
> single data channel to data space."*

**So the eight DMA channels are not eight parallel data paths.** They share one bus,
and when they contend an arbitration decides (fixed or round robin via
`DMACON.PRIORITY`). For scale: three channels at 40 MSPS and 2 bytes are 240 MB/s
across that one bus, five channels 400 MB/s. **How much it actually carries is not in
the datasheet** — there is no figure in transfers per second, and the DMA does not
appear in the peripheral clock table either. A Microchip support statement puts the
ceiling at about 33 M transfers/s; that is not our own measurement.

That is why this code has counters instead of claims.

## What to measure

`status` on the console prints these; the GRAB frame carries the per-grab ones to the GUI;
in the debugger they are plain variables:

| Variable | Meaning | Expectation |
|---|---|---|
| `blocks_done` | completed buffer halves | × half length / elapsed time = **actual sample rate** |
| `dma_overrun` | `DMAxSTAT.OVERRUN` seen: triggered again before the previous transfer finished (page 816) | **must stay 0**, otherwise samples were lost on the DMA bus. A lower bound: one status bit, counted once per interrupt entry |
| `late_service` | ISR found `HALF` and `DONE` pending together, i.e. it was more than one half late | **must stay 0** |
| `proc_missed` | `main()` did not reach a completed half before the next one finished | **must stay 0** |
| `dma_bus_err` | bus write error (`BWERR`; `BRERR` needs `RETEN`, see errata) | 0 |
| `dma_addr_err` | access outside `DMALOW`…`DMAHIGH` | 0 |
| `last_sample` | last value of the completed half | changing = data really moving |
| `ready_half` | which half completed last | alternating 0 / 1 |
| `selftest_mean` | mean of a half sampled on the internal 15/16·VDD reference | ≈ 3840 |
| `fail_code` | stop code, same number the LED blinks | 0 |

None of them sees a rate lowered by `SAMC`; the spectrum does.

A sequence we would suggest, on the board:

1. **The test input at 8 MSPS** (`stream on 8000`, or the GUI on its defaults) - overrun,
   late and missed at 0, the triangle verdict PASS. That proves the chain.
2. **Step the rate up** to find where your board stops being clean - between 8 and
   16 MSPS by the runs so far.
3. **Add your processing** and watch the CPU load and `missed` at the rate you need.
4. **Only then a second core.** Set up a second ADC core with its own DMA trigger
   (table in section 3). This is where the shared bus first shows its limit - not tried
   on this board yet.

## If the bandwidth is not enough

The ADC can average internally, before a DMA transfer even happens — Oversampling mode
(`MODE = 3`) with `ACCNUM[1:0]` in `AD3CH0CON1` (page 1266):

| `ACCNUM` | Samples | Result width |
|---|---|---|
| 0b00 | 4 | 13 bit |
| 0b01 | 16 | 14 bit |
| 0b10 | 64 | 15 bit |
| 0b11 | 256 | 16 bit |

At 16× averaging the DMA moves one transfer instead of sixteen, and the result still fits
in 2 bytes with 14 bits. Only the output rate drops. In that mode the averaged result
lives in `AD3CH0DATA` and the channel event with `IRQSEL = 1` fires once per average — so
`DMAxSRC` and `IRQSEL` change accordingly (`adc_set_mode_oversample()` exists in `adc.c`;
the triggered stream does not use it).

**Whether that is an option depends on your measurement method** — for a pure
amplitude measurement it helps, for a phase-based method averaging can destroy the
information. That is worth a phone call.

`MODE[1:0]` also offers Window mode (gated by an external signal), and the last three
setting channels have a second accumulator for second-order filters.

## What this code does not do

- **No PWM and no clock output.** For an external DAC above 120 MHz a controller pin
  is not the way: the output pins are specified with 2.3 ns rise and 1.7 ns fall time
  (Table 40-26, page 2017, at 25 pF). At 120 MHz one period is 8.3 ns — four of those
  nanoseconds would be edges. The datasheet states no maximum PWM output frequency,
  and none for the Reference Clock Output either.
- **No multiple cores at once.** The stream reads one core; two cores streaming together
  have never run on the board. On purpose: one should be provably working first.
- **No interrupt prioritisation, no error recovery, no calibration.** The ADC can
  recalibrate itself periodically (`ACALEN` and `CALRATE` in `AD3CON`) — worth a look
  for a longer measurement.
- **No statement on analog input bandwidth.** The datasheet does not give one, and the
  input parameters it does give (hold capacitance, pin capacitance, interconnect
  resistance) all carry the note "design guidance only, not tested". The ENOB of
  10.5 bits was characterised with a 1 kHz sine and says nothing about high input
  frequencies. On the board the path DAC2 -> RA8 -> ADC acts as a low-pass, about -3 to
  -5 dB at 400 kHz and -10 to -13 dB at 1.2 MHz; whether the DAC, the pin or the ADC causes
  it is open.
- **No continuous output.** The processed samples go to the GUI in snapshots, not to a
  DAC; `ADC-DSP-DAC-ANALYSIS.md` analyses what a continuous output path would take.

## Errata

Silicon errata DS80001162E (rev. E, July 2026) was checked. Nothing in it concerns
the ADC, the PLLs or the clock generators. Two items touch this code: `BRERR` is only
reported when `RETEN` is set (item 2 — this code leaves it clear, so `dma_bus_err`
counts write errors only), and on **rev A1 silicon** the compiler option
`-merrata=base_offset` is recommended (item 22). `TROUBLESHOOTING.md` has the
details.

## One trap worth knowing about

The symbolic values of two configuration bits were **renamed between pack versions**
(all other names are identical in both packs — ATDF value-groups compared):

| Bit | dsPIC33AK-MP_DFP 1.3.185 | dsPIC33AK-MP_DFP 1.4.260 |
|---|---|---|
| `FICD_NOBTSWP` | `ON` / `OFF` | `BTSWP_ENABLED` / `BTSWP_DISABLED` |
| `FWDT_RCLKSEL` | `BFRC256` | `BFRC244` |

Both spellings name the same bits (FICD mask 0x8000, value 0x0 = BOOTSWP enabled; FWDT
mask 0xC0, value 0x3 = WDT clock BFRC divided down to 32.78 kHz). If MCC
generates `config_bits.c` against one pack and the build uses another, the compiler
rejects a value that is perfectly valid elsewhere:

```
error: unknown value for configuration setting 'FICD_NOBTSWP': 'BTSWP_ENABLED'
```

**This is very likely why an MCC-generated `config_bits.c` suddenly stops compiling:**
MCC generated it against a different pack than the build is using. The value is not
wrong — the spelling belongs to another pack version.

This project sidesteps the problem by writing those two bits **numerically**:

```c
#pragma config FICD_NOBTSWP = 0x0   /* BOOTSWP enabled */
#pragma config FWDT_RCLKSEL = 0x3   /* BFRC/244 (1.4.260) = BFRC/256 (1.3.185) */
```

Every pack version accepts that. Verified: `config_bits.c` built against packs 1.3.185
and 1.4.260 produces a **bit-identical configuration area** in the HEX file (the only
bytes that differ between the two builds are the `__TIME__` string). So the numeric
form is not a workaround with side effects — it is the same setting, spelled in a way
that does not depend on the pack.

`config_bits.c` sets **every** configuration word of the device explicitly, so the
programmed state does not depend on what the programmer does with words a project
leaves out. Apart from the two above and `FWDT_WDTEN = SW` (watchdog off unless the
software turns it on), every value is the erased default; the file says for each
register why that is right for this example. The one to never change by accident is
`FPED_ICSPPED`: `ON` would stop the PKOB4 from programming the part.

The same trick works for any configuration bit whose symbolic names have moved: look
the value up in the ATDF (`<value-group name="FICD_NOBTSWP">`) and write the number.

## Appendix: the back-to-back burst mode

The example's first data path (runs 1 to 17), kept in the firmware for a terminal and
described here as it was written. **It is not continuous**: a software restart after every
buffer leaves a gap, which is why the example moved to the triggered chain
(`ANALYSIS.md` section C.7). Its figures up to run 18 were measured with the DMA in the
wrong mode (`TRMODE = 3`); notes in brackets say where a statement has been overtaken.

### The ADC in Integration mode

`MODE = 10` is Integration mode: a software trigger (`TRG1SRC = 1`, `AD3SWTRG`) starts a
burst, and every following conversion inside it is started by `TRG2SRC`. `CNT` is the
number of conversions in the burst and is tied to the DMA buffer, so one burst is one
full buffer and the DMA's `DONE` interrupt is also the moment to start the next one.
`IRQSEL = 0` raises the channel event after **every** conversion, and that event is what
triggers the DMA.

**`TRG2SRC = 2`, back-to-back, and nothing else.** The datasheet offers a repeat timer
(`TRG2SRC = 3` with the period in `RPTCNT`) and external triggers such as SCCP1
(`TRG2SRC = 34`). On this silicon none of them work:

| Tried | Result on the board |
|---|---|
| Repeat timer, `RPTCNT` 2 … 63 | register holds the value, rate does not change (runs 5, 6, 7) |
| SCCP1 as second trigger, code 34, `AUXOUT = 01` | **no conversion at all** (run 7) |
| One conversion per SCCP1 trigger, Single Conversion mode, `TRG1SRC = 34` | **no conversion at all** (run 7) |
| Sample time `SAMC` 0 … 31 | rate does not change (run 4) |

All four were removed from this example after run 7, together with `sccp.c/.h`. What
remains is the one mechanism the hardware honours, and the rate is set by the ADC clock.

[Overtaken: code 34 is SCCP3, not SCCP1. With code 32 in timer mode SCCP1 triggers the ADC,
and `sccp.c` is back - section 2. The `SAMC` result was taken in the wrong DMA mode; in the
triggered chain `SAMC` does lower the rate.]

At 40 MSPS one half is 25.6 µs of signal and the interrupt arrives at about 39 kHz.
The ISR clears flags, notes which half is complete, counts errors and — at `DONE` —
restarts the ADC burst.

### The rate: PLL1's output dividers

The ADC clock may run from 32 to 320 MHz (Table 16-1). The conversions run back-to-back
and eight ADC clocks make one conversion, so 320 MHz is 40 MSPS and 32 MHz is 4 MSPS.
Nothing inside the burst paces them, so **the ADC clock is the only knob.**

PLL1 feeds nothing but the ADC path (the CPU runs off PLL2), its VCO is 1600 MHz, and the
output is 1600 MHz / (POSTDIV1 · POSTDIV2) with both fields 1…7 and POSTDIV1 ≥ POSTDIV2
(page 778). `pll <p1> <p2>` sets it; the sweep walks this ladder from the slowest rate up:

| POSTDIV1/2 | ADC clock | Rate |
|---|---|---|
| 7/7 | 32.65 MHz | 4.08 MSPS — the slowest that clears the ADC minimum |
| 7/6 | 38.10 MHz | 4.76 MSPS |
| 6/6 | 44.44 MHz | 5.56 MSPS |
| 7/5 | 45.71 MHz | 5.71 MSPS |
| 6/5 | 53.33 MHz | 6.67 MSPS |
| 7/4 | 57.14 MHz | 7.14 MSPS |
| **5/5** | **64.00 MHz** | **8.00 MSPS** |
| 6/4 | 66.67 MHz | 8.33 MSPS |
| 5/4 | 80.00 MHz | 10.00 MSPS |
| 6/3 | 88.89 MHz | 11.11 MSPS |
| 5/3 | 106.67 MHz | 13.33 MSPS |
| 6/2 | 133.33 MHz | 16.67 MSPS |
| 5/2 | 160.00 MHz | 20.00 MSPS |
| 5/1 | 320.00 MHz | 40.00 MSPS — the boot setting of `clock_init()` |

Measured on the board (run 13): one clean burst at 7/7 delivered **3990 kSPS against
4081 nominal**, 2.2 % off. The switch takes the DMA channel down, the ADC core off, the
PLL's output dividers are changed (page 778: they must not move while the PLL is
operating), the core comes back with `ADRDY` and the DMA is set up from scratch — the
boot order, run backwards and forwards again. The burst restart costs one interrupt
latency per buffer, so the measured rate sits a few tenths of a percent below the
nominal value. [Run 19: back-to-back at 8 MSPS in a stream gave 7864 to 7963 kSPS.]

**The CLKGEN6 divider** (`clk`, `clock_adc_set_div()`). The divided clock should be
F_IN / (2 · (`INTDIV` + `FRACDIV`/512)) per Example 12-2. In runs up to 18 the conversion
rate did not move at any ratio, and the ADC kept converting with CLKGEN6 switched off
entirely (`test clkoff`). [Withdrawn: measured in the wrong DMA mode. Run 19 measured the
divider at the generator: it divides, 320/160/80 MHz; `ON = 0` does not stop it.] Two
datasheet details apply if you use it: "FRACDIV will not work if INTDIV is configured to 0"
(12.4.2 4b), so no ratio between 1 and 2 exists at all; and the divider is changed with the
generator **running**.

**Below 4 MSPS** the burst mechanism is the wrong tool: use Single Conversion mode with a
trigger as `TRG1SRC`. [That is the triggered chain of section 2, which goes down to
1 kSPS and, with `CCP1PR` 32 bits wide, much lower.]
