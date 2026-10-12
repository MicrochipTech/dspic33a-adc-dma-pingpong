# What is in docs/ - and which part you need

Twenty-two documents, written for different readers. Start with the group that fits you;
the rest you can leave alone.

## Using the example

| Document | What it is |
|---|---|
| [GUI-MANUAL.md](GUI-MANUAL.md) | How to operate the two PC tools, FilterDesign and the dsPIC33 GUI, task by task, with a picture of every card and a demo video. **Start here** if you want to see the example run. |
| [CONSOLE.md](CONSOLE.md) | Every console command, what a test run looks like, and the chain test (`chain all`). |
| [HOW-IT-WORKS.md](HOW-IT-WORKS.md) | Clock tree, ADC, DMA and CPU; the sample rates you can get; what to measure; errata and the device's traps. Much of it describes the old back-to-back mode - its first note says which parts. |
| [EV17P63A.md](EV17P63A.md) | The second board profile, the dsPIC33AK512MPS506 Curiosity Nano: pins, build, how to try it. Not yet run on a board. |
| [PROJECT-FILES.md](PROJECT-FILES.md) | What is where: the source files, the `tools/` folder, the MPLAB X simulator. |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Debugging guide, symptom first: console silent, clock wrong, ADC or DMA not doing what it should. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | The firmware in two block diagrams: which modules exist and who calls whom, and the data path while the chain streams. The dots show which modules were tested on silicon. |

## Taking the code into your own product

| Document | What it is |
|---|---|
| [CORE.md](CORE.md) | Which part of the code is the core you take over, what you write yourself for your board, and how the hand-over ZIP is made and checked. |

## Where the example stands

| Document | What it is |
|---|---|
| [HARDWARE-LOG.md](HARDWARE-LOG.md) | Every run on the board, dated, including the predictions that turned out wrong. The newest entries are the current state. |
| [ANALYSIS.md](ANALYSIS.md) | Sorted by question: what was checked, with which instrument, which results were withdrawn, what holds and what is open. Its status line is of 25.09.2026; later board runs are in the hardware log. |
| [RESULTS.md](RESULTS.md) | Results report of 25.09.2026 (run 19, the first `chain all`). |
| [TEST-COVERAGE.md](TEST-COVERAGE.md) | Per module: which board run tests it and what no run reaches (as of run 20, 29.09.2026). |
| [ASM-FILTER-COMPARISON.md](ASM-FILTER-COMPARISON.md) | The user filter as generated dsPIC33A assembler against the C variants, measured on the board (04.10.2026). |
| [ADC-DSP-DAC-ANALYSIS.md](ADC-DSP-DAC-ANALYSIS.md) | Analysis and proposal for a continuous output path ADC -> processing -> DAC (04.10.2026). Not built. |

## Design and history - for working on the firmware itself

Written before or during the work. Their status lines describe the day they were
written; what was actually built and run is in the code, `CLAUDE.md` and the hardware log.
They stay because the source cites them section by section.

| Document | What it is |
|---|---|
| [HISTORY.md](HISTORY.md) | The revision history of the example as it was written, the Microchip examples looked at first, and what was taken from where. |
| [PLAN-BINARY-TRANSFER.md](PLAN-BINARY-TRANSFER.md) | The binary frame format the board sends to the PC (`GRAB`, `blk`): header line, payload, CRC. Still the specification. |
| [DESIGN-MULTICHANNEL.md](DESIGN-MULTICHANNEL.md) | Design of routing, several ADCs, the signal generator and the Goertzel detector (26.09.2026). Much of it has been built since. |
| [CHAIN-TEST-PLAN.md](CHAIN-TEST-PLAN.md) | Plan and reasons behind the chain test (`chain all`, `chaintest.c`). |
| [FIRMWARE-STRUCTURE.md](FIRMWARE-STRUCTURE.md) | Analysis of the module structure before the restructuring (26.09.2026). |
| [REFACTORING-PROPOSAL.md](REFACTORING-PROPOSAL.md) | The restructuring proposal (V1..V10) and what became of each item. |
| [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) | The task-by-task plan of the restructuring ("N+1") with its status and decisions. |

## Pictures

`architecture_*.svg` (made by `gen_architecture.py`), the four `0x_*.png` diagrams with
their Mermaid sources `*.mmd` (used in `HOW-IT-WORKS.md`), and `gui/`, the
screenshots of the GUI manual (made by `gen_gui_screenshots.py`).
