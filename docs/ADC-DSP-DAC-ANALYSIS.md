# ADC → signal processing → DAC: analysis of a continuous output path

**Status 04.10.2026: analysis and proposal. Nothing in this document has been built, and
the complete chain ADC → processing → DAC has not run on silicon.** The parts it is built
from have, each on its own; section 2 says which, with the `docs/HARDWARE-LOG.md` entry
behind each claim.

The question: the example samples a signal with the ADC, the DMA streams it into a
ping-pong buffer, and the CPU filters each completed half (`sigproc_block()`). How does
the filtered signal get back out, continuously, through a DAC - so that the board
becomes a real-time filter between an analog input and an analog output?

## Contents

1. What is asked for, in numbers
2. What exists and what has been measured
3. The hard limits of the output side
4. Three architectures
5. Recommended design: block output through a second DMA ping-pong
6. Latency
7. CPU budget
8. Rate coupling and synchronisation
9. Signal quality of the analog output
10. Resources and conflicts
11. Implementation plan in this repository
12. Verification plan (simulator, host, board)
13. Open questions

---

## 1. What is asked for, in numbers

| Quantity | Meaning | Where it comes from |
|---|---|---|
| `fs_in` | ADC sample rate | SCCP1 trigger, `stream on <ksps>` |
| `n` | samples per half | `buf`, 16..1024, default 1024 |
| `D` | decimation factor input → output (1 = none) | new |
| `fs_out = fs_in / D` | DAC update rate | new |
| latency | analog in → analog out, for every sample the same | section 6 |
| load | processing time / half period | `load=` in the GRAB header |

"Continuous" means here: every input sample produces an output (or every D-th, with
decimation), the output never stalls or repeats a block while the input runs, and the
delay between input and output is constant - not just on average.

## 2. What exists and what has been measured

| Link | State | Evidence |
|---|---|---|
| SCCP1 → ADC (triggered single conversion) → DMA0/1 ping-pong → RAM | runs on silicon, clean to 8 MSPS | HARDWARE-LOG sections 4-5, `ANALYSIS.md` C.8 |
| `sigproc_block()` per half in the main loop: lp/hp/bp at fs/8, user filter, Goertzel | runs on silicon, response measured against the design | HARDWARE-LOG, 02.-04.10.2026 entries |
| DMA (channel 2) → DAC, table from RAM, 16-bit write to `DACxDAT + 2`, paced by SCCP2 | runs on silicon, 100 k..1 M transfers/s measured exact | HARDWARE-LOG section 7 |
| DAC2 → RA8 → ADC core 5 (loop) | runs on silicon; static gain 1.030, offset about -3 LSB | HARDWARE-LOG section 6 |
| `dac2_set()` from an interrupt (one register write) | runs at up to 100 kHz in the chain test's low-rate stages | `dac.h`, `chaintest.c` |
| **processed samples → DAC** | **not built, not run** | - |
| DMA channel triggered by SCCP1 (`CHSEL 0x18`) | **never used**; code from the ATDF only | `ANALYSIS.md` C.12.7 |
| DAC1 on UREF (`INSEL = 6`) | **not measured**; only DAC2 (`INSEL = 7`) is | `DESIGN-MULTICHANNEL.md` 2, HARDWARE-LOG run 11-13 |

The pieces are therefore not new. What is new is joining them: a DMA channel that plays
a buffer the CPU fills while it plays, at a rate locked to the ADC.

## 3. The hard limits of the output side

| Limit | Value | Source |
|---|---|---|
| DAC resolution | 12 bits, DNL ±5 LSB, INL -15..+25 LSB | DS70005591D Table 40-42/43, p2035-2036 |
| DAC code range | 0x0CD..0xF32 (205..3890), 5..95 % VDD | 18.4.2, p1417 (`DAC_CODE_MIN/MAX`) |
| usable code range on RA8 on the EV74H48A | about 780..3890: below about 780 the output does not follow | HARDWARE-LOG section 6, cause open |
| settling | 750 ns typical, 2 µs maximum (to 1 %) | Table 40-42, DA07 |
| **update rate, clean** | **≤ 500 kHz** by the worst case, ≤ about 1.3 MHz by the typical figure | follows from the settling; the generator's ceiling `SIGGEN_PLAY_HZ_MAX` is 1 MHz |
| load | `CLOAD` ≤ 30 pF, ±15 mA | Table 40-42; RA8 also carries touch pad 2 |
| DAC clock | 400..500 MHz (PLL1 VCO / 4 = 400 MHz) | Table 40-24, `ANALYSIS.md` C.12.1 |
| output pins | 2: DACOUT1 = RA1 (shared with PGC2), DACOUT2 = RA8 | `dac.h` |

Consequence: **the DAC, not the CPU or the ADC, sets the ceiling of the output path.**
The ADC streams cleanly to 8 MSPS; the DAC follows cleanly only to about 0.5 MHz. Above
that rate the output has to be decimated (section 5.3), and the anti-aliasing for the
decimation becomes part of the processing.

## 4. Three architectures

### A. Per sample in an interrupt

ADC done interrupt (AD5CH0, IRQ 241) → read result → filter one sample → `dac_set()`.

- Latency: one sample period plus the computation - the lowest possible.
- Cost: interrupt entry and exit on every sample (estimated 30..50 cycles on top of the
  filter), no block-wise optimisation (the user filter's assembler loop gains from
  keeping coefficients in registers over a block, 56 against 154 cycles per sample in
  the naive C form, HARDWARE-LOG 04.10.2026).
- The DMA ping-pong is not used at all; the example's sentence (CPU works on the free
  half) does not hold for this path.
- A late interrupt shifts that one output sample in time: the output timing has jitter
  of the interrupt latency.
- Practical up to some 100 to 200 kSPS at 200 MHz (1000..2000 cycles per sample).

Suits a control loop where every microsecond counts. Not the subject of this example.

### B. Block output through a second DMA ping-pong (recommended)

ADC → DMA0/1 → input half → `sigproc_block()` → convert → **output half** → DMA channel →
DAC, the output DMA paced by a trigger locked to the ADC's trigger.

- Output timing is exactly as regular as the input: the DMA writes the DAC on a
  hardware trigger, the CPU's timing only has to hit a window of one half period.
- The processing keeps its block form (and its measured costs).
- Latency: two half periods (section 6) - adjustable through `n`.
- Needs one more DMA channel and a defined phase between input and output.

### C. Processing writes into the capture buffer, DMA plays the capture buffer

The output DMA reads the processed input half directly, no second buffer.

- Saves RAM and a copy.
- But: the capture buffer is shared with `stream grab` (the pair A/B switch moves the
  waiting channels to the other pair), the 12-bit range 0..4095 is not the DAC's range
  (conversion would have to be in place, and the GUI then sees DAC codes), and decimation
  is impossible. Couples two concerns that the current design keeps apart.

Rejected. The copy B needs costs about 2..3 cycles per sample (section 7), which is less
than the complications.

## 5. Recommended design (B)

```
            SCCP1 (160 MHz / N)                       same clock, period x D
                 |                                            |
                 v                                            v
 analog in -> ADC core x -> DMA0/1 -> in[A|B] pair     out[0|1] -> DMA3 -> DACxDAT+2 -> pin
                                       |                  ^
                                       | half complete    | write the half DMA3 is NOT playing
                                       v                  |
                      capture_service() -> sigproc_block() -> playout_push()
                                    (main loop, within one half period)
```

### 5.1 Output buffer

- Two halves of `n / D` 16-bit DAC codes, `out[0]` and `out[1]`, in the `.dma_buffer`
  section beside the generator table and the ADC buffer (`DMALOW`/`DMAHIGH` exist once;
  after a build `xc-dsc-objdump -h` must still show one `.dma_buffer` section).
- RAM: 2 × 1024 × 2 bytes = 4 KB at most (no decimation, `n` = 1024).
- The output DMA runs cyclically over the whole output buffer (Repeated One-Shot,
  `TRMODE = 1`, source reloaded at the end - exactly what `dma_tx_start()` does for the
  generator), no interrupt.

### 5.2 Conversion to DAC codes

`sigproc_block()` leaves 12-bit values 0..4095 (hp/bp/user centred on 2048). The DAC
takes codes 205..3890, on RA8 usable from about 780. The conversion maps the full ADC
range onto a chosen output range and clips:

```
code = out_lo + ((uint32_t)y * (out_hi - out_lo + 1)) >> 12     /* y = 0..4095 */
```

`out_lo`/`out_hi` default to 800..3500 (the generator's measured clean range on RA8),
settable, refused outside 205..3890 unless forced (as `siggen` does). One multiply, one
shift, one add per sample; with two samples per 32-bit access, as `process_buffer()`
reads, about 2..3 cycles per sample.

### 5.3 Decimation

For `fs_in` > 500 kSPS, every D-th filtered sample goes to the output. This is only
correct if the filter has removed everything above `fs_out / 2` first. The fixed filters
(lp at fs/8) allow D ≤ 4 with modest alias suppression; the user filter can be designed
for it in `tools/filterdesign` (its coefficients then hold at `USER_FILTER_FS_HZ` = the
input rate). A decimating filter computes only the output samples it keeps - for an IIR
filter it still has to run on every input sample, so decimation saves the DAC, not the
CPU.

### 5.4 Who writes which half

Input half k completes at time t_k. The output DMA plays `out[k mod 2]` from t_k + T_h on
(T_h = n / fs_in, one half period). `playout_push()` writes `out[k mod 2]` between t_k and
t_k + T_h - while the DMA still plays `out[(k-1) mod 2]`. The check that this holds is a
read of the output channel's remaining count (`DMAxCNT`, as `dma_tx_remaining()` reads it)
before and after the write: it must lie in the other half. If it does not, the half is
counted (`out_slip`) and filled with the last value (or mid-scale), never left with
stale data from two halves ago.

### 5.5 Gaps

`sigproc_info_t.gap = 1` (first block after `sigproc on`, a restarted stream, missed
halves): the filter restarts its state; the output fills the halves that were not
computed with the hold value and counts them. A missed input half is therefore audible as
a short constant level, never as a repeated block.

## 6. Latency

Sample i of input half k was taken at t_k - T_h + i/fs_in and is played at
t_k + T_h + i/fs_in (with D > 1 the kept samples i = 0, D, 2D, ... alike) - i.e.
every sample is delayed by the same amount:

```
latency = 2 · T_h + filter group delay + ZOH half sample + analog settling
        = 2 · n / fs_in + τ_g + 1/(2 · fs_out) + ~1 µs
```

| fs_in | n = 16 | n = 64 | n = 256 | n = 1024 |
|---|---|---|---|---|
| 100 kSPS | 320 µs | 1.28 ms | 5.1 ms | 20.5 ms |
| 250 kSPS | 128 µs | 512 µs | 2.05 ms | 8.2 ms |
| 500 kSPS | 64 µs | 256 µs | 1.02 ms | 4.1 ms |
| 1 MSPS (D = 2) | 32 µs | 128 µs | 512 µs | 2.05 ms |

(2 · T_h only; τ_g depends on the filter.) The latency could be cut to T_h plus the
processing time if the output started as soon as a half is finished instead of on a
fixed grid, but then it would vary with the processing time - against the "constant"
requirement of section 1. A fixed 2 · T_h is the honest choice.

Smaller halves cost per-half overhead (interrupt for HALF/DONE, `capture_service()`,
the filter's set-up per block): at n = 16 and 500 kSPS a half is 32 µs = 6400 cycles,
of which a few hundred go to the overhead. That has not been measured; the `load=` field
at n = 16 against n = 1024 measures it (section 12).

## 7. CPU budget

At 200 MHz the CPU has `200e6 / fs_in` cycles per input sample. Measured costs per
sample (HARDWARE-LOG, -O1):

| Processing | cycles / sample | measured |
|---|---|---|
| fixed low-pass fs/8 | 62 | 02.10.2026, `load=` |
| Goertzel (folded) | 7 | 02.10.2026 |
| user filter, 3 sections, float assembler | 56 | 04.10.2026 |
| user filter, float C (fmaf, locals) | 81 | 04.10.2026 |
| user filter, float C (generated stand-in) | 154..185 | 04.10.2026 |
| user filter, fixed32 C | 250 | 04.10.2026 |
| **conversion + copy into the output half** | **2..3, estimated** | not measured |

| fs_in | cycles / sample available | assembler user filter + output | load |
|---|---|---|---|
| 250 kSPS | 800 | ~59 | ~7 % |
| 500 kSPS | 400 | ~59 | ~15 % |
| 1 MSPS | 200 | ~59 | ~30 % |
| 2 MSPS | 100 | ~59 | ~60 % |

The output path adds almost nothing to the CPU. At the rates the DAC can follow, the
processing is far from its limit - there is room for much longer filters (about 18
sections at 500 kSPS before 90 % load, extrapolated from 56 cycles for 3 sections,
not measured).

DMA bandwidth: input one transfer per sample, output one per D samples; at 500 kSPS
that is 1 M transfers/s against the some 33 M/s from support (`ANALYSIS.md` C.12.9).

## 8. Rate coupling and synchronisation

**The output rate must be derived from the same clock as the input rate.** With two
independent clocks the output DMA runs a little faster or slower than the input; the
position check of section 5.4 then fails every few seconds (at 100 ppm and 500 kSPS: one
sample per 20 ms, one half of 64 samples per 1.3 s). Asynchronous sample-rate conversion
would be the cure - complex, not needed here, because the chip has one clock tree.

Two ways, both on CLKGEN13 (PLL1 out / 2 = 160 MHz):

1. **D = 1: the output DMA is triggered by SCCP1 itself** (`CHSEL 0x18`, "SCCP1", ATDF).
   No second timer, no drift, no phase to set: input and output DMA move on the same
   events. Not tried on silicon - `dma_tx.h` has codes for TMR1, TMR2 and SCCP2 only.
   Side effect: the DAC switches at the same instant the ADC starts its sample; if the
   ADC reads the DAC's own pin (a loop test), the DAC step's transient falls into every
   sample the same way (`ANALYSIS.md` C.11, point 4). For a separate input it does not
   matter.
2. **D > 1: SCCP2 with period D × (SCCP1 period)**, on the same 160 MHz. Locked in
   frequency; the phase between the two timers is whatever their start leaves - fixed,
   and measured once by the position check. SCCP2 is the generator's clock today: the
   generator and a decimated output cannot run at the same time with this choice
   (section 10).

The phase is checked on every half (5.4), so a slip is counted, not inferred.

## 9. Signal quality of the analog output

- **Zero-order hold.** The DAC holds each value for one output period: the spectrum is
  shaped by sinc(f/fs_out) - -0.9 dB at fs_out/4, -3.9 dB at fs_out/2 - and images
  appear around fs_out, 2·fs_out, ... An analog reconstruction low-pass at the pin (an
  RC is enough for a demonstration; the 30 pF `CLOAD` limit applies to the capacitance
  the pin sees, so a series resistor in front of the capacitor) removes the images. The
  droop can be pre-compensated in the digital filter (inverse sinc) - a design option for
  `tools/filterdesign`, not needed for a first version.
- **Resolution.** ADC ENOB about 10.5 bits, DAC DNL ±5 LSB and INL up to 25 LSB: the
  output is good for about 9..10 bits. The mapping of 5.2 onto 800..3500 costs another
  0.6 bits (2700 codes for 4096 values).
- **RA8 lower end.** Below about 780 codes the output on RA8 does not follow (HARDWARE-LOG
  section 6, cause open: DAC, touch-pad network or ADC input). Measure it with a scope
  on RA8 before choosing `out_lo`; RA1 (DACOUT1) is the cross-check, but carries PGC2.
- **Settling.** 0.75..2 µs per step: at 500 kHz a full-scale step settles inside the
  2 µs period only by the typical figure. Signals with small steps (filtered, low
  frequency against fs_out) are not affected; a square wave at fs_out/2 is.
- **DAC clock.** It has to run at 400..500 MHz (VCO divider); the earlier 320 MHz was
  below the specification (`ANALYSIS.md` C.12.1).

## 10. Resources and conflicts

| Resource | Today | With the output path |
|---|---|---|
| DMA channels (8) | 0/1 ADC pair, 2 generator | **+1: channel 3** for the output, so the generator can stay the test source |
| SCCP | SCCP1 ADC trigger, SCCP2 generator | none more for D = 1 (SCCP1); a third SCCP for D > 1 with the generator running |
| DAC outputs (2) | generator on DAC1 or DAC2 | output on the other one |
| RAM, `.dma_buffer` | ADC 2 pairs × 2048 × 2 B + table ≤ 16 KB | + ≤ 4 KB, inside the same window |
| UREF | DAC2 internal → ANn7 | unchanged |

`routing.c` must claim channel 3, the SCCP, the DAC output and the RAM, and refuse a
conflict before any driver call - as it does for `ROUTE_STREAM` and the generator.

`dma_tx` is written for channel 2 alone. The output needs either a channel parameter
there (and new trace goldens for the generator's register writes, if the addresses move
into a table) or a second, identical channel in `dma.c`. The first is the cleaner one:
the rule "nobody outside `dma.c` touches a DMA register" holds either way.

A self-test without any wire:

```
generator: DAC1 -> UREF (INSEL 6) -> ADC core x, AN7 -> ping-pong -> filter -> DAC2 -> RA8 -> scope
```

UREF with DAC1 has not been measured (only DAC2). Alternative with one wire: generator on
DAC1 at RA1 into core 5 (AD5AN1) - RA1 is PGC2, so the debugger must not use that pair.
Or an external signal generator into the default input AD3AN5 (mikroBUS A).

## 11. Implementation plan in this repository

All of it belongs to the **core** (a customer wants the output path), not the lab.

| Step | Files | Content |
|---|---|---|
| P1 | `drivers/dma.c`, `dma_tx.h` | output channel: channel parameter (2 = generator, 3 = output) or a second channel; trigger code `DMA_TRIG_SCCP1 0x18` with its ATDF reference; register writes in the trace goldens |
| P2 | `core/playout.c/.h` (new name, unique in the tree) | output buffer in `.dma_buffer`, `playout_start(dac, D, lo, hi)`, `playout_stop()`, `playout_push(x, n, info)` (conversion 5.2, decimation 5.3, half selection 5.4, gap handling 5.5), counters `out_slip`, `out_hold` |
| P3 | `core/capture.c` | call `playout_push()` after `sigproc_block()` in `capture_service()` - main loop, no ISR touched (`_DMA0Interrupt` 46/0, `_DMA1Interrupt` 41/0 stay; checked with `fncmp.py`) |
| P4 | `core/routing.c` | claim and conflicts (section 10); `route list` shows the output |
| P5 | `core/cli.c` | sub-command `stream out <dac> [D] [lo hi] [force]` / `stream out off` - no new top-level command (32 slots); `status` lines `out_*` |
| P6 | `core/gui_link.c`, `tools/protocol.py`, `adc_gui.py` | GRAB header fields `out=`, `out_slip=`; GUI card "analog output" |
| P7 | `sim/sim_dma.c` | stand-in for the output channel, so the simulator's acceptance run covers the bookkeeping |
| P8 | `docs/` | `README.md` (commands), `ARCHITECTURE.md` + `gen_architecture.py` (new module box), `TEST-COVERAGE.md`, `CORE.md` (handover) |

Verification after every step as in `CLAUDE.md`: all builds `-Wall -Wextra` clean (`core`
build included), `trace.bat`, `hosttest.bat`, `gen_core_project.py --check`, smoke runs
(the console changes: `--update-expected`, diff reviewed).

## 12. Verification plan

### Without a board

- **Host test** (`tests/host/test_playout.c`): conversion and clipping at both ends,
  decimation phase across half boundaries, half selection for every position of the
  remaining count, gap → hold value, slip counting.
- **Trace golden** (new scenario): register writes of `stream out 2` and `stream out off`
  - channel 3's `CHSEL`, source, destination `DAC2DAT + 2`, count, `TRMODE = 1`, the
  window covering all three buffers.
- **Simulator acceptance run**: the playout bookkeeping alongside the ping-pong logic
  (the simulator has no DAC; it proves the bookkeeping only).

### On the board - one session, ordered so that each step answers one question

| # | Setup | Question | Expected |
|---|---|---|---|
| 1 | `stream on 100`, `sigproc off`, `stream out 2`, generator sine 1 kHz on DAC1 | does the passthrough work at all? | the sine on RA8 (scope), `out_slip` 0 |
| 2 | as 1, scope on input and output, burst/step from the generator | latency | 2 · n / fs_in + ZOH, constant over 100 bursts |
| 3 | `buf` 16, 64, 256, 1024 at 100 and 500 kSPS | per-half overhead; does n = 16 hold? | `load=` per n, `out_slip` 0, latency per table 6 |
| 4 | output codes 205..3890 ramp (passthrough of a slow triangle) | where does RA8's lower end clip? | answers HARDWARE-LOG section 6's open point; choose `out_lo` |
| 5 | `sigproc lp` / `user`, sine sweep | does the output carry the filter's response? | output amplitude/input amplitude = design ± 0.5 dB up to fs_out/4 (sinc droop corrected) |
| 6 | 1 MSPS, D = 2 (SCCP2) | decimation and second timer locked? | `out_slip` 0 over 60 s |
| 7 | `stream grab` every 0.2 s during 3 | does the grab disturb the output? | `out_slip` 0, no glitch on the scope |
| 8 | DMA trigger `CHSEL 0x18` read back, DMA3 transfers per second against SCCP1 events | is SCCP1 a usable DMA trigger? | equal counts |

Every run gets its `docs/HARDWARE-LOG.md` entry, including the predictions above that do
not hold.

## 13. Open questions

1. Does `CHSEL 0x18` (SCCP1) trigger a DMA channel? (ATDF says yes; never used.)
2. Does `UREFCON.INSEL = 6` put DAC1 on UREF as 7 does DAC2?
3. What clips RA8 below about 780 codes - and does RA1 behave differently?
4. How large is the per-half overhead at n = 16? It decides the shortest latency.
5. Can SCCP2 start in a fixed phase to SCCP1, or is the phase only measured (5.4)?
6. Is 500 kHz the practical DAC ceiling for the signals of interest, or does the typical
   settling (750 ns) allow 1 MHz for filtered, band-limited output?
7. Should the output path hold or mute on a gap? (Proposal: hold - no click to mid-scale.)
