# Hardware log - what has been measured on silicon

Boards: EV74H48A (dsPIC33 Curiosity Platform, dsPIC33AK512MPS512 GP DIM, PKOB4, console
on the MCP2221A virtual port, 115200 8N1). The EV17P63A Curiosity Nano (dsPIC33AK512MPS506)
builds clean (`tools\build.bat nano`, smoke run in the simulator) but **has not run on
silicon**; everything below is the EV74H48A unless said otherwise.

This file is a condensed version of the lab diary that was kept run by run from 23.09.2026.
It keeps the dates, run numbers, instruments, numbers, the claims that were later withdrawn
and the predictions that turned out wrong. Datasheet references are DS70005591D. Rule for
every later entry: say what has and has not run on silicon, and add the dated entry for each
board run and for each change made in reaction to one.

Reading guide, by topic: 1 console and boot, 2 rate control attempts (runs 4-17), 3 the DMA
mode defect (run 18), 4 the chain streams (run 19), 5 restructuring and A/B run (run 20),
6 DAC triangle, 7 signal generator, 8 console transmit ring, 9 ping-pong pairs, 10 signal
processing, 11 limits and open questions, 12 not run on silicon.

## 1. Console and boot (runs 1-3, 8)

- **Run 1 (23.09.2026):** clocks, console, ADC ready, DMA armed, then a trap: `INTTREG.VECNUM = 2`,
  `ILR = 14`. Vector 2 is `XRAMECCInterrupt` per the pack's interrupt list, not an address
  trap. PLL1 320 MHz, PLL2 200 MHz, switch to PLL2 and UART re-clock all worked. The tail of
  "[clk] PLL2 locked" came out as garbage: `console_puts()` returns when the last character is
  in the FIFO, the clock switched while it was still in the shift register. Fix:
  `console_flush()` before the CLKGEN1 switch.
- **Run 2:** self-test passed (mean 3815 on the internal 15/16 VDD reference), then `fail 6`:
  `DMA0STAT = OVERRUN | DONE` with `IFS2 = 0` - a DONE happened and its interrupt flag was
  wiped. Fix: the DMA interrupt clears `DMA0IF` first and reads the status afterwards;
  `dma0_clear()` writes the status word once instead of bit-field read-modify-write (a flag
  set between the read and the write was written back as 0). Both rules are still in force.
- **Run 3:** part reset as soon as the stream ran at SAMC 0 with the main loop processing; no
  trap block. Added: `RCON` decoded at boot (this device has POR, BOR, WDTO, SWR, EXTR, CM,
  BUCKR, VREG2R..4R - no TRAPR), guard words behind the buffer (`fail 11`), the buffer as a
  dedicated object in its own section with the DMA window exactly that buffer.
- **Runs 6 and 7: the console received nothing** (`rx = 0`, no UART error flags, receiver
  idle, pin routing as intended). **Run 8 (24.09.2026):** after the firmware was changed to
  boot idle (nothing converting until a command is typed), `help` and `test all` worked.
  Cause: the priority-1 receive interrupt was starved behind the priority-4 DMA interrupt at
  ~1.6 million entries per second. Pin routing, PPS and terminal were never the problem.
- Run 7 also stopped silently inside the DAC test with no trap and no reset; run 8 stopped
  mid-sweep the same way. Explanation that fits: at the undivided rate the overrun interrupt
  fires every 625 ns (125 CPU cycles at 200 MHz), about the cost of an entry plus handler, so
  the CPU never returns to the main loop. The OVERRUN event has no enable bit of its own
  (13.6.1: `DMA0CH` has HALFEN, DONEEN, MATCHEN only), so the handler brakes itself past
  `OVERRUN_LIMIT` (500 000): it masks its interrupt and ends the stream. Run 9: the whole
  `test all` ran to the end and the console still answered. A first version of the brake
  compared a cumulative counter and tripped on every later test; fixed with a per-start
  counter.
- A banner containing `+local changes` means the working tree differs from the named
  commit; such logs were hard to interpret (runs 2 and 15). The banner carries the git
  revision since run 5.

## 2. Rate control attempts (runs 4-17, 23-25.09.2026)

All rate, overrun and missed figures of runs 1-18 were taken with the DMA in the wrong mode
(section 3). The sequence is kept because the instruments and the retractions matter.

- **Run 4:** auto sweep, 2000 halves per point, nominal 1.25-40 MSPS by `SAMC`: overrun
  61-88 thousand and missed 1773-1940 of 2000 in every row. `SAMC` does not set the rate
  with back-to-back triggering. Run 5-6: ADC repeat timer (RPTCNT 16, nominal 5 MSPS)
  delivered 36.5 / 36.1 MSPS, SCCP1 timer (20 ticks) 37.9 / 37.4, back-to-back 35.3 / 37.5:
  one rate whatever the source. Registers read back as written (`AD3CH0CON1 = 0x05000381`:
  TRG1SRC 1, MODE 2, TRG2SRC 3, SAMC 0, PINSEL 5; `AD3CON` RPTCNT 2). Timer1 time base
  checked against `__delay32()` every run (1 250 001 ticks per 100 ms).
- **Run 6 and 7 findings on overrun:** about 4 % overrun at ~38 MSPS, digit for digit
  identical in two phases with a floating input and with the DAC driving the pin, so the
  loss was independent of the signal. The `[half]` line showed the unconnected input at
  8-35 counts of 4096.
- **Run 7 (24.09.2026):** the ADC core switch at run time works (core 3 to core 5, `DMA0SEL
  0x3B -> 0x48`, `DMA0SRC 0x0B64 -> 0x0DA4`); DAC2 comes up on CLKGEN7 (`DACCTRL1 =
  0x3F7F8000`, `DAC2CON = 0x8100`). Both SCCP1 paths reported "no data at period: 20".
- **Three errors in the SCCP1 path, all ours (24.09.2026):** (1) the trigger number was
  "corrected" from 32 to 34 following Table 16-4; the pack's ATDF (`AD_CH_CON1__TRG1SRC`)
  names 0x20 = 32 "SCCP1 OC/IC Event" and 0x22 = 34 SCCP3; the datasheet table was wrong
  and the original value was right. (2) `CCP1CON2.AUXOUT` carried the timer rollover (1)
  instead of the special event trigger (2). (3) the module ran off the peripheral clock
  (`CLKSEL = 0`, PLL2) while the ADC runs from PLL1; it must be CLKGEN13 (`CLKSEL = 1`).
  Any one was enough for "no conversion". Runs 5-7 therefore never tested SCCP1.
- **Run 8-9: the CLKGEN6 divider.** All fifteen ratios written and read back identically
  (`test clock` passed - a false positive, it proves only that the register holds the
  value), yet measured 39.3-41.1 MSPS at every setting. Run 8 switched the generator off
  around the write; run 9 kept it on as Example 12-2 (p771) prescribes: same result. Also
  found: FRACDIV does not work with INTDIV = 0 (12.4.2 step 4b), so no ratio between 1 and
  2 exists. **Withdrawn later:** the conclusion "the CLKGEN6 divider does not set the ADC
  rate" - the cause was the DMA mode (run 19, S8 reads 320/160/80 MHz at ratios 1/2/4).
- **Run 10:** PLL1 output dividers `POSTDIV1/2` (VCO 1600 MHz, 7/7 = 32.65 MHz = 4.08 MSPS
  up to 5/1 = 320 MHz = 40 MSPS, p778) arrived in the registers (`clock_adc_hz()` read
  32.65 MHz at 7/7) but the loaded rate stayed 41.4-44.2 MSPS; `test clkoff` (CLKGEN6 off)
  still converted 260 halves. Read at the time as "the ADC ignores its clock"; later
  explained by the DMA copying the same result register at its own speed. Self-test on a DC
  reference cannot tell a frozen register from real conversions.
- **Runs 11-13: the chain carries data.** UREF route (`UREFCON.INSEL`, DAC2 on the internal
  line, read as AN7 on any core): run 11 min 221 / max 3864 (the conversions are real) but
  torn windows under the interrupt storm (8552 halves between copies); one-shot capture
  built. Run 12: PASS that did not hold (reversal check vacuous, Timer1 not started, window
  barely moved). Run 13 (`dac on 64`, 2048-sample one-shot window): a clean triangle
  2416..3851, largest step 113 of a 1440 swing, one turning point, no gap; window 513.3 us,
  3990 ksps against 4081 nominal. The judging is from the data now; `dac2_period_ns()`
  (computed period 54.9 us vs. measured about 449 us) is not judged against.
- **Run 14:** clean single-burst rate by Timer1 follows the PLL setting; the shortfall (2.2 %
  at 4 MSPS to 17.8 % at 40) is a constant 11 us offset because the clock started before
  `capture_settle()`. Corrected, 5/1 gives 40157 against 40000. DAC test PASS: 3728 falling
  to 629, step 90 of a 3240 swing.
- **Run 15:** all fourteen PLL rows inside 0.5 % after subtracting the offset. Every loaded
  point took about 50 ms regardless of rate (40.65-42.0 MSPS "loaded"). A prediction written
  down before run 16: if the handler booked stale events, a 2000-block point would show
  about 98 bursts (4 MSPS) instead of 1000.
- **`dma_overrun` is a lower bound (24.09.2026).** `OVERRUN` is one bit in `DMA0STAT`; the
  handler increments once per entry in which it is found set, not per lost sample.
- **Run 16, prediction wrong:** half + done = 2 x bursts in every row (isr 48 429-69 792):
  the handler counts honestly. A single burst follows the PLL, a thousand bursts deliver
  ~40 MSPS whatever the PLL. A display fault of ours compared the free-running `blocks_done`
  with a per-point count and made the result look like a factor of 3-40.
- **Run 17 (25.09.2026):** `clean1` vs. `clean10`: first burst takes the PLL-predicted time
  (506 us at 4.08 MSPS), bursts 2-10 take 1-52 us each - DMA speed, not conversions. Read
  at the time as repeats; explained by run 18.

## 3. Run 18 (25.09.2026): the DMA mode was wrong

First `chain all` (SCCP1 -> ADC core 5 Single mode -> DMA0 -> ping-pong -> CPU, DAC2 on RA8
as the signal; stages S0..S9). Log cut at S5.6.

- S0: Timer1 1 250 002 per 100 ms; clock monitor CLKGEN6 319.996 MHz, CLKGEN7 399.996 MHz.
  The three PLL-output readings failed (codes 0xB read 7.996 MHz, 0xC 159.996 = CLKGEN13,
  0xE 399.996): the ATDF's CNTSEL codes do not select what they say - instrument, not clock.
- S1: SCCP1 159.999 MHz (the CLKGEN13 divider divides); timer mode 100/1000/10006 events in
  100 ms exact; output-compare mode no event at all.
- S2: SCCP1 -> ADC 100/100, 1000/1000, 10006/10006 results per event: the triggered path
  works on silicon for the first time. Static transfer over RA8: gain 1.030, offset -2.7 LSB,
  largest deviation 27 LSB.
- S3: 6144 transfers for 15 conversions, buffer in runs of about 400 equal values. S4: ~2.05 M
  transfers in 50 ms at 100 kSPS and 1 MSPS (41 M/s). S5: staircases, no triangle.
- **Cause:** `dma.c` had `TRMODE = 3` (Repeated Continuous): a single trigger starts
  back-to-back transfers until the block is full (13.4.8.4 p833, 13.4.8.5 p834). The mode
  for one transfer per trigger is Repeated One-Shot, `TRMODE = 1` (13.4.8.3 p832). Set on the
  first day and never questioned; it explains "40 MSPS whatever the setting", the overrun
  storms, run 17's `clean10`, and most likely the support statement "a few transfers per
  trigger". **Every figure of runs 1-18 was measured in the wrong DMA mode.**

## 4. Run 19 (25.09.2026): the chain streams

First `chain all` with `TRMODE = 1`; complete log.

- **The example's sentence holds up to 8 MSPS on silicon.** S3: 6144 transfers for 6144
  conversions, overrun 0, every buffer index holds the code the CPU stepped for it.
- S4 (triggers vs. transfers in 50 ms): 100 kSPS, 1, 4 MSPS exact; 8 MSPS 400 004 of
  400 011 with overrun 0; 10 MSPS overrun 732 of 0.5 M; 16-20 MSPS overrun ~2000-2700;
  from 26.7 MSPS transfers far below triggers, brake at 32 MSPS.
- S5 (triangle through the chain): grid clean (slip 0.03-0.09 samples) at 0.1, 1, 4, 8,
  10 MSPS; slope against model 1.000, also with the DAC on PLL2 at 500 MHz. 16 and 20 MSPS:
  slip 6.2/5.0 (samples lost). 26.7/32/40 MSPS: slope 0.666/0.554/0.499 - the ADC converts
  only at about 18-20 MSPS in triggered Single mode, at 40 MSPS every second trigger is lost.
- S6/S9 (CPU processes every half): 8 MSPS for 15 s, 120 000 509 transfers, overrun 0, late
  0, missed 0, isr = half + done. The first placeholder loop took ~23 cycles per sample,
  92 % of the half period at 8 MSPS, 46 % at 4 MSPS.
- S7 all pass. S8: the CLKGEN6 divider divides (320.0 / 160.0 / 80.0 MHz at 1 / 2 / 4);
  `CLK6CON.ON = 0` does not stop the generator (monitor still 320 MHz), which is why
  "converts with CLKGEN6 off" held. Back-to-back at 8 MSPS: burst 1 and burst 100 give the
  same slope (127.67 / 127.69 samples, model 127.47), 7864 / 7963 kSPS: the rate is
  selectable in streaming. Back-to-back at 40 MSPS: no data.
- Withdrawn: the "no effect" readings of the CLKGEN6 divider, the PLL rate, and the
  "rate not settable in streaming" reading of run 16 - all were the DMA mode.
- The summary said "NO RATE" because counts were judged against a trigger rate taken from
  S1's 10 ms measurement (+4.9 ppm, resolution 8 ppm) with no latency allowance; the data
  never disagreed. Fixed: nominal 160 MHz unless S1 finds >1 % off, S1 over 100 ms, 1 us
  latency in the tolerance.
- DAC fixed in the same round (all earlier DAC figures predate it): clock 320 -> 400 MHz
  (Table 40-24 p2016 minimum 400), `UPDTRG = 11` (p1409), SCCP1 320 -> 160 MHz (maximum
  200), period formula factor 2.

## 5. Restructuring and the first A/B run (27-29.09.2026, run 20)

**27.09.2026: not run on silicon.** The restructuring (files into `src/` by role, port layer,
UART driver, split of `cli.c` and `capture.c`, routing core, board data) was verified without
a board: register-trace goldens 14/14 bit for bit, host tests 17/17, simulator boot-and-command
check, simulator acceptance run (default PASS 100 halves 0 mismatches, 256 samples per half
PASS, deliberate fault FAIL at half 9 index 0 - the fault run had been vacuous earlier because
it waited for a marker that no longer existed). `_DMA0Interrupt` 42 instructions / 0 indirect
calls through all of it; `_U2RXInterrupt` 65 -> 55 once. The only intended console change:
`stream on` at a custom core/pinsel is checked against the routing core and refuses a PINSEL
the core cannot reach.

**Run 20 (29.09.2026): A (`b41af3b`, the pre-restructuring firmware) against B (`dead53c`).**
Both flashed and driven from a host through the console, `test all` skipped.

- B behaves like A for the version/status, register dump, `chain all`, non-DAC input and
  `route list` blocks. Stack 276 of 50 200 bytes used, buffer at 0x4154 (`% 4` = 0), guard ok.
- `chain all` as in run 19: S6 overrun/late/missed 0 at 1/4/8 MSPS, S9 chose 8 MSPS 1 s
  clean. The rewritten processing loop (32-bit reads, unrolled): 3.0 cycles per sample, load
  12.3 % at 8 MSPS (run 19: 92 %); the prediction "well below half" held.
- **Predictions that turned out wrong:** S5.5 (10 MSPS triangle clean) failed in A and B
  (slip 3.00/2.03) although run 19 had it clean - the 10 MSPS boundary is not reproducible.
  `stream grab` at 1/4/8 MSPS, 50 grabs each: every frame CRC-clean (300 grabs) but the
  triangle verdict failed on about half (A 70/80, B 57/93 pass/fail), usually with `missed=1`.
  `test all` hung A's firmware after the 13.3 MSPS row (overrun brake `STOPPED` from 10 MSPS).
- One unexplained A/B difference: at 26.7 MSPS (S4.15/16) the brake tripped in B and not in
  A; at S4.20 the other way round.
- **Why half the grabs failed:** not lost samples (a period-shift test found none), but the
  DAC2 triangle on RA8 loses its lower end a few hundred milliseconds after start: the first
  grab shows a sharp minimum at 248 (DACLOW 240), later ones a flat floor at 630-670 counts,
  20-98 samples long. `chain all` never saw it (measures 1 ms after start). Measured 3 s
  after start at 1 MSPS: low 240 flat 55-98 samples, 600 flat 21, 900 and 1200 clean. Fix:
  the triangle starts at `TRI_LOW = 0x400` (peak-to-peak ~2800 instead of ~3600); then 1, 4
  and 8 MSPS gave 10/10 PASS with slip 0.01-0.06, and `chain all` S5 PASS to 8 MSPS with
  slope 0.999-1.000. What clips the lower end (DAC output, the load on RA8, the ADC input) is
  open; this is probably the "DACLOW is not reproduced" of run 13.
- A separate sequence (`dac 2 on 1200` while streaming, grabs, `stream off`) printed `[FAIL]
  code: 8` after the reply and stopped: the "timeout" at the end of the 8 MSPS series.
  Explained on 01.10.2026 (section 8).
- Recovering without a re-flash: the firmware's own `reset` command, banner back after
  0.22 s with counters 0; a debugger-level connect-and-release reset took 29.4 s, same
  revision, counters 0.
- 29.09.2026: `dac 2 on 32 3840 20` was refused ("low must be >= 0xCD + slpdat", p1422); with
  `force` it was accepted ("OUTSIDE the datasheet's limits"). What the DAC outputs below
  0xCD was not looked at.
- 29.09.2026, buffer size: `buf` while streaming is refused; after `stream off` accepted, but
  the next `stream on` set the half length back to 1024 (`acq_chain_setup()`); fixed, then
  `buf 256` + `stream on 8000` grabbed n = 256.
- 29.09.2026: `stream`'s "free CPU cycles per sample" read 200 MHz / rate exactly (mean
  processing time 0) and "processing max per half" 0 at 128 samples, 8 MSPS: the figure was
  wrong, not the loop free (run 20 measured 3.0 cycles per sample). Not explained that day.
- 29.09.2026, GUI trigger on real grabs: 60 grabs (1/4/8 MSPS, both edges, N = 1024, L = 512,
  hysteresis 16) all found a crossing; windows resampled on the crossing match the first of a
  series within rms 3.0-6.1 (max 8.6) against 800-1210 untriggered. Counters 0/0/0 except at
  8 MSPS: overrun 1 / missed 1 per grab cycle (the halt/restart, not the trigger).

## 6. DAC and test signal

- DAC2 Triangle mode, DACOUT2 = RA8 = AD5AN3 (DACOUT1 = RA1 = AD5AN1, shared with PGC2),
  both on core 5. RA8 is also the capacitive touch pad 2 of the board.
- Below table code about 780 the DAC output does not follow (min 607 for a table from 205;
  triangle "fall to 629" in run 14). The generator's default range stays above it.
- Static transfer over RA8 (run 18, S2): gain 1.030, offset about -2.7 LSB; a 1000-entry
  sine fitted offset 2123 against 2150 expected (-27 LSB, 29.09.2026).
- Open: what limits the lower end (see section 5).

## 7. Signal generator (29.09-02.10.2026)

A wavegen table played by a DMA channel into DAC1/DAC2 at SCCP2's rate (first channel 1,
channel 2 since 01.10.2026).

- **29.09.2026 first pass:** SCCP2 triggers the DMA in the dual 16-bit timer mode (TMR16),
  not in 32-bit output compare: `siggen on 2 1000 100000 snap` gave `transfers_per_s`
  100000, `sccp2_flags` 3 (CCT2IF and CCP2IF), `DMA1STAT` 0x30, no ADRERR. With `oc`: 0
  transfers, no flag, `CCP2TMR` ran past `CCP2PR` - OC32 is dead on this path. Play rates
  100 k / 250 k / 500 k / 1 M transfers/s measured exact (501000 once, a window edge).
- A RAM source inside the shared DMA window is accepted (DMALOW 0x41B8 = the table, DMAHIGH
  0x91B7 = the buffer's end; `DMALOW/HIGH` exist once, 13.4.5 p826). The value reaches
  `DACDAT` through a 16-bit write to `DAC2DAT + 2`.
- Loop DAC2 -> RA8 -> core 5 (`stream on <ksps> 5 3`), table 800..3500: a 1 kHz sine from
  1000 entries at 100 kHz, sampled at 1 MSPS, fits amplitude 1352 (table 1350); against the
  table as a staircase 11-14 LSB rms, median 8. At 10 kHz (10 entries per period, steps up
  to ~850 LSB) median 45 LSB, rms 80, concentrated at the steps: the DAC's settling
  (0.75-2 us, Table 40-42) in a 10 us step.
- The generator survives the ADC chain (`stream on` / `stream off` leave it playing; `dma0_init`
  and `dma0_deinit` no longer switch `DMACON` off while it runs): 30 s at 4 MSPS beside it
  overrun/late/missed 0; 20 random cycles no new fault, single overruns at 8 MSPS as without.
  The conflict (test form of `stream on` while the generator plays on DAC2) is refused.
- **One unexplained `fail 8` after `stream off`** (twice on 29.09.2026, about 2 in 176
  `stream off`): found on 01.10.2026 to be a race in main()'s check, not the generator
  (section 8).
- 29.09.2026, GUI card: only the triangle ever showed; two GUI faults (a stale DAC2 card sent
  after every `stream on`, which stops the generator by design; `siggen on 2` refused while
  the test stream runs). After the fix the loop preset worked.
- **Open (02.10.2026):** in the generator loop (f0 1 kHz, h3 0.3, `stream on 1000 5 3`) some
  grabs show the full swing (782..3501) and some show RA8 nearly still for a whole half
  (e.g. 1593..1639, at least 2 ms), in no fixed order; fundamental 977 Hz when the signal is
  there. The pre-split baseline does the same. A later check found a continuous 1000/s
  stimulus with no gap over 10 s while grabs ran every 0.2 s, so the stand-still more likely
  arises between buffer and grab than in the generator. Not explained.

## 8. Console transmit ring and a race in main() (01.10.2026)

Compared against the commit before the change (built in a clean worktree), flashed with the
vendor command-line programmer.

- Before (polled transmit): `help` (1629 characters, 175 ms) held the CPU in the receive
  interrupt; the next grab reported `missed` 68 / 274 / 550 halves at 1 / 4 / 8 MSPS.
- 2 KB ring, `TXWM = 0`, every command asynchronous: `chain all` lost S0.2, S4.7/8, S4.11-14,
  S9.3 (the transmit interrupt still sent the previous `@` line during the next measurement);
  the measuring commands now send polled (`console_quiet_begin()/_end()`).
- `TXWM = 7`: the console fell silent after two characters (flag raised on reaching the
  watermark, not held). Back to 0.
- 8.5 KB ring: grabs clean but `chain 6` at 16/20 MSPS overrun ~7 000 / ~9 700 per second,
  four of four runs, against 0 before: the linker put the ring between the generator table
  and the ADC buffer (both `.dma_buffer`), moving the buffer across 0xC000 so the table no
  longer lay directly below it. Which of the two costs the overruns was not separated.
- 8 KB ring (smaller than the 0x2040-byte buffer section, so placed after it): `chain 6` four
  times 0 overruns at 8..20 MSPS, `chain all` every verdict identical to before, `help` while
  streaming `missed` 0/0/0, 20 grabs per rate CRC-clean, ~435 ms per grab. `status`:
  stack_size 16624, used 816. After a build, `xc-dsc-objdump -h` must show one
  `.dma_buffer` of 0x6040 bytes.
- **The `fail 8` found:** reproduced 1 in 9 `stream off` at 1 MSPS. main() read
  `capture_running()`, `capture_chain_active()`, `dma0_enabled()` one after the other; a
  `stream off` in the receive interrupt between the reads gave a state that never existed.
  `capture_stream_lost()` reads the three under `DISICTL 2`: 120 `stream off` since, 0
  failures. The race predates the ring; the ring made it likelier.
- 01.10.2026, buffer 2 x 2048 samples on the board: `buf` 2048 accepted, stack_used 444;
  `stream on 1000`, three grabs of 2048, 0.42-0.43 s per grab, triangle grid-clean. Not run:
  the evaluator's `TP_MAX = 160` turning points on a 4096-sample window at 100 kSPS.

## 9. Ping-pong pairs, grab without stopping (01-02.10.2026)

- **Experiment (01.10.2026), one channel:** a write to `DMA0DST` while the channel runs moves
  the live pointer at once and becomes the reload value; `DMA0CNT` is untouched; the channel
  has no separate reload register. A single channel therefore switches cleanly only between
  the last transfer of a block and the first of the next (100 us at 10 kSPS, 125 ns at
  8 MSPS) - not from an interrupt.
- **Two channels in hardware ping-pong (13.4.11, `PPEN` on both, `PCHEN` on the initiator):**
  `TRMODE = 0` stops after two blocks unless software re-arms; `TRMODE = 1` alternates with
  no software. Pair switch at speed (1024-sample blocks, waiting channel's DST moved to the
  other pair): 1/4/8 (five runs)/10/16 MSPS no sample lost or repeated, `grid_ok` True, steps
  across all three hand-overs within the triangle's normal slope (8 MSPS -23..-28 LSB), STAT
  0x30. At 100 kSPS `grid_ok` False only through the evaluator's turning-point limit.
- **02.10.2026, the design on silicon:** two pairs A/B, channels 0+1 as the stream, generator
  on channel 2, `stream grab` freezes the completed pair by moving the waiting channel.
  Grabs at 1/4/8/10 MSPS, 12 each: 2048 samples, `from` alternating 2048/0, triangle
  contiguous, overrun/late/missed 0, ~440 ms per grab, stream never stopped (~3400 halves
  between two grabs at 8 MSPS). Two fixes found on the board: the frame's CRC and ring copy
  took 2-3 ms (`missed` 2/12/25 at 1/4/8 MSPS; now `capture_service()` runs between frame
  chunks); a grab's own `capture_service()` could land inside the main loop's (`missed` -2;
  now commands are held back during every `capture_service()`). After both: 72 grabs, all 0.
- **16 / 20 MSPS:** 16 MSPS 12 grabs, 7 overruns, data contiguous, missed 0; 20 MSPS 56
  overruns and 59 missed halves, triangle still contiguous. `chain all` S4.13/14 (20 MSPS)
  FAIL with overrun 487 while the transfer count is exact (1000010 of 1000010): the flag
  fires without a lost sample. Single-channel had 0 there. Open: whether the hand-over
  raises OVERRUN at these rates, and why 20 MSPS then misses halves. Later builds showed the
  16 MSPS flag as stochastic (390 in one build, 0 in the next).
- ISR sizes: `_DMA0Interrupt` 46/0 (42 before), `_DMA1Interrupt` 41/0, `_U2RXInterrupt` 55/0,
  `_U2TXInterrupt` 48/0.

## 10. Signal processing in `sigproc_block()` (02.10.2026)

Processing is in place on the completed half, in the main loop, never in an interrupt.

- **4th-order Butterworth low-pass at fs/4** (bilinear, two sections with a1 = 0): on the
  board (`stream on 100`, the triangle's harmonics, sigproc off vs. on) within 0.6 dB of the
  design down to the noise floor (-0.37 dB at 0.199 fs, design -0.30; -30.78 at 0.375 fs,
  design -30.63). Cost 59 cycles per sample with statics, 43 with locals: up to 2 MSPS.
- **Cut-off halved to fs/8** (a1 no longer 0): -1.26 dB at 0.110 fs (-1.25), -19.18 at 0.199 fs
  (-19.28), -29.21 at 0.243 fs (-29.03); worst 0.7 dB. About 63 cycles per sample (1 MSPS 137
  free, 2 MSPS 37, 3 MSPS 4 free and 70 halves missed): up to 2 MSPS.
- **CPU load in the GRAB header (`load=`, per mille):** low-pass 310 / 621 / 938 at 1 / 2 /
  3 MSPS, 62 cycles per sample every time; at 3 MSPS 31 halves missed in 5 grabs.
- **Selectable low-, high-, band-pass at fs/8 plus a Goertzel at fs/16** (generator sine at
  400 kSPS, best of 5 grabs): measured gain equals design to below 0.0005 at fs/32, fs/16,
  fs/8, fs/4 (e.g. lp 0.707 at 50 kHz, hp 0.053 at 25 kHz, bp 1.000 at 50 kHz). Goertzel 1341
  LSB / 100 % at fs/16, at most 11 LSB elsewhere. Filter ~66 cycles per sample at first.
- **Goertzel folded** (one integer pass into `acc[i mod 16]` plus the sum of squares, 16 complex
  multiplies per block, exact mean and variance; host test against a double DFT, 74 checks):
  55 cycles per sample became about 7; load alone 33 / 132 / 264 per mille at 1 / 4 / 8
  MSPS, missed and overrun 0; low-pass plus Goertzel 358 per mille at 1 MSPS.
- GUI check setups: 25 kHz 1344 LSB detected 5 of 5; 50 kHz 0 LSB 0 of 5; 25 kHz with high-pass
  on 1345 LSB 5 of 5 (the Goertzel measures before the filter); 28 kHz 49 LSB (predicted
  47) 0 of 5. **A prediction that turned out wrong:** the near-tone first set to 26 kHz
  ("expect not detected") read 167 LSB and was detected 5 of 5: 26 kHz is only 2.56 bins from
  fs/16 in a 1024-point unwindowed DFT, |sinc| = 12 % (1340 x 0.122 = 164).
- `-O0` vs. `-O1`: with MPLAB X's default -O0, 8 MSPS stream missed up to 13 halves per grab
  interval with no processing on and the filter load was twice as high (618..687 per mille
  at 1 MSPS); with -O1 stream 0/0/0 and load 278..310. The core example project sets -O1.
  The main project's IDE build also builds at -O0 and is slower; not measured further.
- 02.10.2026 core/lab split: code moved, not changed; `chain all` identical to the pre-split
  image except the stochastic 16 MSPS OVERRUN flag; the core build (14 console commands)
  gives the same stream and processing figures. `__builtin_write_DISICTL(variable)` stops
  xc-dsc v3.21/v3.31 at -O0 with an internal compiler error; replaced by inline asm
  (`disi_set()`), same `disictl wN` as the builtin at -O1.
- **03.10.2026, the user filter from tools/filterdesign (EV74H48A, by hand, flashed from the
  filter tool's dsPIC33 tab):** an elliptic band-pass 800-1200 Hz, order 6, fixed32 for
  8 kSPS (id EF36DD44) built and programmed with `ipecmd -TPPKOB4 ... -M -OL` - 27.7 s,
  "Program Succeeded", the device found as `0xa77c`. What went wrong first, and why: the
  tab showed ipecmd's output only at its end, a first run looked hung, and it was killed
  while it was erasing/programming (exit 1 after 155 s, the log ended at "configuration
  memory"). Killing `ipecmd.exe` alone left its java child running; from then on the PKoB4
  answered nothing (`Transmission on endpoint 2 failed (err = -10121)`, "Connection Failed",
  later "Target Device ID (0x0)" and "PKoB4 was unloaded while still busy"), and the
  console on COM26 did not answer (`connect failed: no ACK/NAK`) - the part was half
  programmed. A MPLAB X without a window (`mplab_ide64.exe` from the day before, 400 MB)
  was still running and may have held the tool as well. Unplugging the USB cable (twice,
  after that MPLAB X was ended) and flashing again from the tab worked. Changed because of
  it: the tab shows build and flash output line by line as it comes, with the seconds
  running and a note not to interrupt; a hung run is stopped after 240 s with its whole
  process tree (`taskkill /T`), stdin closed; "Failed" in ipecmd's output counts as a
  failure whatever its exit code; a running MPLAB X is named in the hint. The filter itself
  and the noise test (white noise from the generator, response measured with and without
  the filter) have **not** been measured on the board yet - a highpass 1800 Hz was
  installed afterwards, results to follow.
- **03.10.2026, the generator's noise on the board (by hand, GUI, filter off):** the noise
  setup's table (8192 entries, noise 1, f0 0) played at 400 000 entries/s on DAC2, read on
  RA8 at 8 MSPS and at 2 MSPS, the spectrum averaged over 16 grabs. It shows the DAC's
  zero-order hold as predicted: |sin(pi f/400 kHz)/(pi f/400 kHz)| with nulls at 400, 800,
  1200 ... kHz (both rates), and at 2 MSPS about -27 dBFS near DC, 3-4 dB less at 200 kHz
  (the hold's -3.9 dB at half the play rate). The time plot at 8 MSPS shows the held steps,
  about 20 samples each. So the noise reaches the ADC as designed; it is flat only up to
  half the play rate, which is why the noise test plays at twice the stream rate.
- **04.10.2026, why the noise does not look flat at high rates (`tools/path_response.py`,
  board on COM26, filter off):** white noise (8192 entries) on DAC2, read on RA8, 16 grabs
  per configuration, Welch spectra (512). The expected spectrum of an ideal DAC + ADC -
  the table bit-exact from `wavegen_model`, the reported play rate, hold and aliasing - is
  subtracted; the rest is the path's. Results, rest at 400 / 800 kHz / 1.2 MHz:
  - **The test signal explains most of what the GUI showed**: the hold's sin(x)/x of the
    play rate and its aliases (e.g. 400 k entries/s seen at 1 MSPS: -10 dB at 300 kHz from
    the signal alone).
  - **What is left is a linear low-pass of the analog path**, about -3 to -5 dB at
    400 kHz, -6 to -8 dB at 800 kHz, -10 to -13 dB at 1.2 MHz, -16 to -25 dB at 1.6 MHz,
    the same at 1, 2, 4 and 8 MSPS (it follows the absolute frequency, not the ADC's rate)
    and the same at noise amplitude 1, 0.25 and 0.1 (not the DAC's slew rate). Candidates:
    DAC2's output settling into the pin's load (RA8 carries capacitive touch pad 2; the
    datasheet's 750 ns to 1 % alone would put -3 dB near 1 MHz, not ~450 kHz) and the ADC's
    sample capacitor at SAMC 0 (at 2 MSPS SAMC 8 instead of 0 left ~1.5 dB less loss at
    400-600 kHz - small, one pair). Not separated yet: needs a scope on DACOUT2 or an
    outside source, or DAC1 -> RA1 for comparison.
  - **Found on the way, a gap in the counters**: SAMC > 0 at high rates silently changes
    the real sample rate - the hold's 1 MHz null moved to 1.5-1.6 MHz at "8 MSPS" with
    SAMC 8 and 31 (effectively ~5 MSPS) and to 816 kHz at 2 MSPS with SAMC 31, while the
    GRAB header said 8000/2000 kSPS and overrun/late/missed stayed 0. Conversions longer
    than the trigger period are not counted anywhere.
  - Run A (15 configurations) stopped at its 17th: `stream off` with the generator on did
    not answer within 5 s (the board printed `[half]` lines, then answered normally;
    fail_code 0). The script now waits 15 s, retries once and saves after every
    configuration. Data: `build/path_response/` (A as the log, B and C as results.json,
    summary.txt, response.png).
  - **Part D, the rule play = min(2 fs, 1 MHz):** the raw spectrum (no model subtracted)
    relative to 2-5 % of fs: within about +-2 dB up to 0.45 fs at 100, 250 and 500 kSPS
    (the +-2 dB are the table's line pattern after 16 grabs, not a slope); at 1 MSPS -2 dB at
    200 kHz and -10 dB at 400 kHz, at 2 MSPS -6 dB at 400 kHz, at 8 MSPS -16 dB at 800 kHz.
    Flat noise from this DAC ends near 200 kHz. The GUI's "flat noise for this rate" uses the
    rule and shades the spectrum above min(0.45 x play rate, 200 kHz).
- **04.10.2026, the user filter as dsPIC33A assembler against C (board on COM26, EV74H48A,
  each built with `tools\build.bat` -O1 and flashed with ipecmd/PKOB4; banner `git 82ed5d7+local
  changes`, 12:33-12:38):** the same design (elliptic band-pass 800-1200 Hz, order 6, 3
  sections, fs 8 kHz) in three arithmetics of tools/filterdesign, `sigproc user`, `load=` of
  the second grab, the stream run at rates the coefficients are not meant for (the cost per
  sample does not depend on them):

  | arithmetic | load at 1 / 2 / 3 MSPS (per mille) | cycles per sample | highest rate without missed halves |
  |---|---|---|---|
  | float, dsPIC33A assembler (`asmgen.py`) | 281 / 562 / 848 | 56 | 3 MSPS (4 MSPS: 678 missed) |
  | float (C) | 926 / 1855 | 185 | 1 MSPS |
  | fixed point 32 bit (C) | 1252 / 2507 | 250 | below 1 MSPS (1 MSPS: 290 missed) |

  The assembler costs 3.3 x less than the C float code and 4.5 x less than fixed32. At 8 kSPS
  the output was filtered (2022..2076 against 992..3802 unfiltered on the same input), late/missed 0.
  **Prediction that turned out wrong:** from the instruction counts (33 against ~90 per
  sample) and the built-in float loop's 1.4 cycles per instruction (44 instructions, 62 cycles) I expected 45-60 cycles for the assembler
  and 120-130 for C float, factor 2-2.5; measured 56 and 185, factor 3.3 - the C float
  loop costs about 2 cycles per instruction (its coefficient and state loads), the
  assembler 1.7. The response against the design (the GUI's noise test) was not run.

## 11. Limits and open questions

Settled on silicon (EV74H48A):
- The chain SCCP1 -> ADC core 5 -> DMA (Repeated One-Shot) -> ping-pong -> CPU streams
  without loss up to 8 MSPS (15 s, 120 M samples, overrun/late/missed 0); the triangle
  passes through complete and in order up to 10 MSPS in run 19 (not reproduced in run 20),
  slope 1.000 of the model.
- The rate follows the PLL1 output dividers (single burst within 0.5 % from 4 to 40 MSPS,
  back-to-back streaming at 8 MSPS identical in burst 1 and burst 100). The CLKGEN6 divider
  divides (320/160/80 MHz); `CLK6CON.ON = 0` does not stop the generator.
- A few hundred DMA overruns per 0.5 M transfers from 10 MSPS; lost triggers from 16 MSPS;
  the ADC converts at only 18-20 MSPS in triggered Single mode (every second trigger lost at
  40 MSPS). DMA ceiling quoted by support: about 33 M transfers/s in total.

Open:
- What clips the DAC output below about 600-780 counts (DAC, RA8 load, or ADC input).
- Why OVERRUN rises at 16-20 MSPS in pair mode, and why 20 MSPS misses halves there.
- Output-compare mode of SCCP1 and SCCP2 raise no event (TMR16 is the working mode); the
  clock monitor's CNTSEL codes for the PLL outputs read other clocks than documented.
- The generator-loop grabs that show a still signal (section 7).
- The 10 MSPS boundary and the 26.7 MSPS brake difference between A and B in run 20.
- The 02.10.2026 observation that `stream`'s CPU figure read the full budget (29.09.2026) was
  later superseded by the `load=` field, which matches the free-cycle figures.

## 12. Not run on silicon

- The EV17P63A Curiosity Nano with this firmware (build and simulator smoke run only).
- The user filter's response on the board (its cost per sample: section 10, 04.10.2026), the GUI's noise test and
  filter switch against a board (the noise itself was seen on the board, section 10), the Nano's copy-to-drive flash (03.10.2026: all checked on the host, the
  simulator and the GUI's stand-in only).
- `test all` on the restructured firmware (R3 skipped; it hangs the older firmware after
  the 13.3 MSPS row), and the `sweep` at the current revision.
- DAC1 as the generator's output, generator `decay` > 0 on the board.
- Rates above 8 MSPS with processing on; longer runs at 16-20 MSPS in pair mode.
- The GUI page against a board for every card (checked against the built-in stand-in; some
  cards were tried on the board without a record of which).
- `blk` of 4096 samples and the evaluator's turning-point limit on a 4096-sample window.
- A comparison of the stack high-water mark and the `console_force_up()` PPS/TRIS path under
  load beyond what run 20's `status` showed.
