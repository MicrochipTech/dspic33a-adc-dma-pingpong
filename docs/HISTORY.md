# History: how the example came about

The revision history as it was written, the Microchip examples looked at before, and what was taken from where. The current state is in `HARDWARE-LOG.md`. Moved out of the top-level README on 13.10.2026, unchanged; only links were adjusted to the new place.

## Contents

- [Read this first](#read-this-first)
- [Existing examples we looked at first](#existing-examples-we-looked-at-first)
  - [What comes from where](#what-comes-from-where)

## Read this first

**The result, in one document: [`docs/RESULTS.md`](RESULTS.md)** (25.09.2026). The
chain SCCP1 → ADC → DMA → ping-pong → CPU streams without loss up to 8 MSPS with the CPU
processing every half, proven on the board; the report explains how it was found, what
the limits are and what is still open. The history below is kept as it was written.

**What has run on hardware.** Since 23.09.2026 this code runs on the EV74H48A, and
thirteen runs are recorded with their logs in `docs/HARDWARE-LOG.md`. As of 24.09.2026
the following is proven on silicon, not argued from the datasheet:

- Clock tree, console, ADC core, DMA channel and the self-test on the internal
  reference.
- **The measurement chain itself.** With a known triangle from the on-chip DAC routed
  to the ADC, one captured buffer contains the triangle: a clean rise, one turning
  point, a clean fall, the largest step between two neighbouring samples 113 counts out
  of a swing of 1440, no jump and no gap (run 13). **The ADC converts a real changing
  signal and the DMA places every result in the ping-pong buffer, complete and in the
  order it was converted.**
- **The sample rate follows the setting.** One clean burst, timed with Timer1, delivered
  3990 kSPS against 4081 nominal — 2.2 % off (run 13).

**What is not settled.** How far up that stays true. At the undivided clock the DMA
loses samples to overruns - `dma_overrun` reaches about 4 % of the sample count, and
that is a lower bound, because the counter moves once per handler entry that finds the
flag set and not once per lost sample - and because every overrun raises the DMA
interrupt — 1.6 million per second, one every 625 ns — the CPU stops coming back to the
main loop at all. The rate at which the chain stays lossless is exactly what the sweep
is for, and the table from a board is still outstanding.

**One number to distrust.** Every rate figure measured *under load* in runs 4 to 11 —
the sweep's old `measured` column — is wrong by about a factor of ten. It was taken by a
CPU drowning in the overrun interrupt. The sweep now measures each rate on a single
clean burst as well and prints both, because the difference between the two columns is
the artefact itself.

**Two things about this device that cost us four days**, both in `docs/HARDWARE-LOG.md`
with register evidence, and both worth knowing before you trust a datasheet page here:

1. Nothing paces the conversions inside a burst. The ADC's repeat timer (`TRG2SRC = 3`,
   `RPTCNT`) and the SCCP1 trigger were configured correctly, read back correctly and
   ignored; `SAMC` does not change the rate either. The conversions run back-to-back and
   the only thing that changes the rate is the ADC clock.
2. The CLKGEN6 divider does not change the ADC clock. Every ratio was written, read back
   and confirmed by `DIVSWEN` and `CLKRDY` — with the generator switched off around the
   write and with it left running as Example 12-2 prescribes — and the rate did not
   move. The ADC also kept converting with CLKGEN6 switched off entirely. **The rate is
   set with PLL1's output dividers instead**, which works.

Parts of this example were **AI-assisted**. All register names, bitfields and value
ranges were taken from datasheet **DS70005591D**, the errata **DS80001162E** and the
ATDF files of the **dsPIC33AK-MP_DFP** device pack, and each one is cited at the point
of use — so every setting can be checked against the primary source.

**Revision history**

- **2026-09-24, nine more runs on the board, and the chain proved** (runs 5 to 13, all
  in `docs/HARDWARE-LOG.md`). The firmware was rebuilt around what the board actually
  does:
  - **Back-to-back only.** The repeat timer, the SCCP1 trigger as second and as first
    trigger, `sccp.c/.h`, the pacing selection and the `pacing`/`period` commands are
    gone: four mechanisms, four times ignored by the hardware.
  - **The rate comes from PLL1's output dividers**, 1600 MHz / (POSTDIV1 · POSTDIV2),
    40 down to 4.08 MSPS with 8 MSPS exactly on the ladder. The CLKGEN6 divider is kept
    as the `clk` command with a warning; do not build on it.
  - **Nothing runs by itself.** The firmware boots, sets the slowest rate and waits.
    `test` lists the parts of a run, `test all` runs them. The reason: through seven runs
    the console never received a byte, and only an idle board could show that this was
    the receive interrupt starving behind the DMA interrupt rather than a wiring fault.
  - **An emergency brake in the DMA handler.** Past 500 000 overruns in one measurement
    it masks its own interrupt and takes the channel down, so a rate that floods the CPU
    ends in a log line instead of a silent board.
  - **A DAC test that proves the data.** The on-chip DAC2 is routed to the ADC *inside
    the chip* over the UREF line, so no pin and no wire are involved; one buffer is
    captured with the stream stopped from the interrupt, and the judgement is made
    afterwards on the stored samples.
- **2026-09-23, first runs on the board** (four of them). Found and fixed: the console's
  tail garbled at the clock switch (flush first); a lost DMA `DONE` because the interrupt
  flag was cleared at the end of the handler and the status flags by read-modify-write;
  the sample buffer is a dedicated volatile object with guard words and the DMA window is
  exactly that buffer; `RCON` is reported at boot; the rate is measured with Timer1. The
  source was also split into modules (`board.h`, `clock`, `adc`, `dma`, `capture`, `led`,
  `diag`, `cli`) with a simulator build for the buffer logic.
- **2026-09-22, after the first report from a board** — the project's tool is the PKOB4
  (`pkob4hybrid`). A first attempt had run against a PC-side tool instead of the board
  and looked like a dead board; that was the whole cause. A second change made in the
  same breath — setting `OSCCTRL.PLLxEN` and waiting for `PLLxRDY` before the first
  divider switch — was reverted after review: it rests on Example 16-3, a snippet from
  the ADC chapter whose own arithmetic is wrong, and it waits for a lock on the POR
  dividers. The clock code follows the MCC sequence again, which has run on silicon.
- **2026-09-22, third revision** — moved to the **EV74H48A** with the dsPIC33AK512MPS512
  DIM (the board of Microchip's own 40 MSPS example): ADC3 on the mikroBUS A analog pin,
  LED0 on RC8, pin table below. A **command console** (`cli.c`, on the parser from
  [zabooh/cmd_parser](https://github.com/zabooh/cmd_parser)) on the MCP2221A USB-UART
  channel. The console runs in the UART receive interrupt below the DMA interrupt.
- **2026-09-22, second revision** — tailored so that the first run needs nothing but
  the board: a **self-test** on the ADC's internal 15/16·VDD reference runs before the
  external input is used; **LED0 reports** heartbeat, error and a stop code; every
  hardware wait loop is **bounded** and reports where it gave up instead of hanging.
- **2026-09-22** — full review against the datasheet, the errata and Microchip's MCC
  examples. Four mistakes found and fixed, all of which would have stopped the first
  run dead: (1) the ADC was set to single-conversion mode with a re-trigger source,
  which the datasheet says is ignored in that mode — it would never have converted;
  (2) `DMALOW`/`DMAHIGH` were left at their reset value 0, so the first DMA write would
  have faulted and disabled the channel; (3) the DMA status flags were "cleared" by
  writing 1 — they clear on 0 — so every counter would have stuck; (4) the two sample
  buffers were swapped by rewriting the DMA destination inside the ISR while the
  transfer was already running, which splits every block. Details in the sections below
  and in `docs/TROUBLESHOOTING.md`.
- **2026-09-21** — first version.

## Existing examples we looked at first

Before writing anything we searched Microchip's own example organisation
[`microchip-pic-avr-examples`](https://github.com/orgs/microchip-pic-avr-examples/repositories?q=dspic33a)
for something that already did this. These are the ones we evaluated:

| Repository | What it does | What we took from it |
|---|---|---|
| [dspic33ak-curiosity-adc-40msps](https://github.com/microchip-pic-avr-examples/dspic33ak-curiosity-adc-40msps) | **40 MSPS ADC on dsPIC33AK128MC106 and dsPIC33AK512MPS512** — MCC-generated, runs on a Curiosity board. Reads conversions in software; **no DMA**. | Studied in detail. **Our clock setup and our ADC trigger scheme follow it**, because that code has been on silicon and ours has not. |
| [dspic33a-dac-dma-sinewave](https://github.com/microchip-pic-avr-examples/dspic33a-dac-dma-sinewave) | DAC fed by DMA to emit a 100 Hz sine without CPU intervention. | Checked for DMA setup patterns: it sets the DMA address window and clears the status flags by writing 0 — both of which we had wrong before the 2026-09-22 review. |
| [dspic33a-curiosity-dma-spi-eeprom-demo](https://github.com/microchip-pic-avr-examples/dspic33a-curiosity-dma-spi-eeprom-demo) | SPI transfers driven by DMA. | DMA, but not from an ADC and not at rate. |
| [dspic33a-code-examples](https://github.com/microchip-pic-avr-examples/dspic33a-code-examples) | Collection of smaller dsPIC33A examples. | Scanned for an ADC-plus-DMA combination; there is none. |
| [dspic33ak512mps506-dppim-demo](https://github.com/microchip-pic-avr-examples/dspic33ak512mps506-dppim-demo) | PWM and ADC on the dsPIC33AK512MPS506. | PWM-triggered conversion, not continuous sampling into memory. |

**The gap this project fills: ADC and DMA together, at full rate, with counters.**
The official 40 MSPS example proves the ADC reaches 40 MSPS. It does not answer how
much of that actually arrives in RAM, because it does not use the DMA — and on this
device all eight DMA channels share a single data bus (DS70005591D §13.4.4, p825),
with no throughput figure given anywhere.

**If you only need the ADC and can read conversions in software, use the official
example instead of this one.** It has run on hardware.

### What comes from where

To be precise about how much of this code rests on something that has run on silicon:

| Part of this code | Origin | Has run on hardware? |
|---|---|---|
| Clock setup: PLL1/PLL2 divider values, CLKGEN1/CLKGEN6 settings, switching sequence | bit-identical to the MCC-generated `clock.c` of [dspic33ak-curiosity-adc-40msps](https://github.com/microchip-pic-avr-examples/dspic33ak-curiosity-adc-40msps) | yes, in that example |
| ADC trigger scheme: Integration mode, software trigger starts a burst, the conversions inside it run back-to-back (`MODE = 2`, `TRG1SRC = 1`, `TRG2SRC = 2`, `AD3SWTRG`) | the same as Microchip's 40 MSPS example, plus Example 16-6 (p1331) for the burst | yes — and by elimination. Every documented way to pace the conversions inside a burst was tried on the board and none worked (`docs/HARDWARE-LOG.md` runs 4 to 7): the repeat timer and `SAMC` are ignored, the SCCP1 trigger produces no conversion at all. Back-to-back is what is left, and the rate comes from the ADC clock |
| DMA basics: `DMALOW`/`DMAHIGH` window, status flags cleared by writing 0, control register layout | MCC `dma.c` of [dspic33a-dac-dma-sinewave](https://github.com/microchip-pic-avr-examples/dspic33a-dac-dma-sinewave) and datasheet Examples 13-1 to 13-4 (p832 ff.) | yes — but memory-to-DAC in Repeated One-Shot mode, the opposite direction and a far lower rate |
| **ADC burst → DMA in Repeated One-Shot mode (Repeated Continuous until 25.09.2026, see `dma.c`) → one buffer with `HALF`/`DONE` interrupts → burst restarted from the `DONE` ISR** | **our own construction**, assembled from datasheet §13.4.8 (Example 13-4, p835), §13.6.1.2 (HALF interrupt, p848) and §16.4.5 (p1322) | **no.** There is no Microchip example for this combination. This is the part `docs/TROUBLESHOOTING.md` §1.1 flags as the remaining risk |
| Self-test on the internal 15/16·VDD reference (ADxAN6) | the input and its sample time come from datasheet Example 16-3 (p1328), which uses it for gain calibration; the pass/fail logic is ours | the input yes, the check no |
| Board pins, UART2 on the MCP2221A channel, PPS codes, baud generator setting | the MCC-generated `pins.c` and `uart2.c` of the same 40 MSPS example (`RPINR13bits.U2RXR = 0x32`, `RPOR28bits.RP114R = 0x15`, `U2BRG = 0x364`) and the DIM info sheet | yes, in that example |
| Command parser (`cmd_parser.c/.h`) | [zabooh/cmd_parser](https://github.com/zabooh/cmd_parser), copied unchanged; it has run on a SAM E54 and a PIC32CM there | yes, on other targets — not yet on this one |
| Console commands, transport, receive interrupt (`cli.c`) | our own | no |
| Measurement counters, ISR, `main.c`, LED reporting, bounded waits, file structure | our own | no |

Nothing was copied verbatim. The examples served as the reference for register values
and patterns; every line here was written for this project and cites the datasheet
page it rests on.
