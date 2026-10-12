# What is in docs/ - and which part you need

Seventeen documents, written for different readers. Start with the group that fits you;
the rest you can leave alone.

## Using the example

| Document | What it is |
|---|---|
| [GUI-MANUAL.md](GUI-MANUAL.md) | How to operate the two PC tools, FilterDesign and the dsPIC33 GUI, task by task, with a picture of every card and a demo video. **Start here** if you want to see the example run. |
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
| [PLAN-BINARY-TRANSFER.md](PLAN-BINARY-TRANSFER.md) | The binary frame format the board sends to the PC (`GRAB`, `blk`): header line, payload, CRC. Still the specification. |
| [DESIGN-MULTICHANNEL.md](DESIGN-MULTICHANNEL.md) | Design of routing, several ADCs, the signal generator and the Goertzel detector (26.09.2026). Much of it has been built since. |
| [CHAIN-TEST-PLAN.md](CHAIN-TEST-PLAN.md) | Plan and reasons behind the chain test (`chain all`, `chaintest.c`). |
| [FIRMWARE-STRUCTURE.md](FIRMWARE-STRUCTURE.md) | Analysis of the module structure before the restructuring (26.09.2026). |
| [REFACTORING-PROPOSAL.md](REFACTORING-PROPOSAL.md) | The restructuring proposal (V1..V10) and what became of each item. |
| [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) | The task-by-task plan of the restructuring ("N+1") with its status and decisions. |

## Pictures

`architecture_*.svg` (made by `gen_architecture.py`), the four `0x_*.png` diagrams with
their Mermaid sources `*.mmd` (used in the main README's "How it works"), and `gui/`, the
screenshots of the GUI manual (made by `gen_gui_screenshots.py`).
