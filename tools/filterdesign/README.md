# tools/filterdesign - IIR filter design, down to the dsPIC33 board

An IIR filter design tool: Butterworth, Chebyshev (type I) and elliptic (Cauer) filters as
lowpass, highpass, bandpass and bandstop, with a browser GUI that analyses the design,
generates C code in float, double or 16/32-bit fixed point and tests it with gcc. Its
**dsPIC33** tab installs the filter into this repository's firmware (`sigproc user`), builds
and flashes it and opens the dsPIC33 GUI - see the main [README](../../README.md#your-own-filter-from-the-design-tool-to-the-board).

Taken over on 03.10.2026 from the FilterDesign project's `pc/` folder (its revision
`a1ab02a`); that project's PIC32 firmware library (`FilterDesign/filter_design.c`, the
original of `fdesign/lib/`) is not part of this repository.

- **`fdesign/`** is a command line tool written in C. It wraps the design library and builds
  with a Makefile - or by itself: the GUI builds it with gcc on its first start.
- **`gui/`** is a browser GUI written in Python with NiceGUI. It uses `fdesign` for the design,
  plots the usual filter characteristics and generates C code for the filter.

```
tools/filterdesign/
├── fdesign/
│   ├── Makefile
│   ├── lib/filter_design.c/.h   design library (fixed copy of FilterDesign's, see "Changes")
│   ├── src/fdesign.c/.h         specification front end (band edges -> F1..F4, SOS output)
│   ├── src/main.c               command line interface
│   └── test/verify.py           verification against SciPy
└── gui/
    ├── app.py                   NiceGUI application
    ├── fdcore.py                runs fdesign, analysis, fixed-point model
    ├── codegen.py               C code generator (filter, test bench, Makefile, firmware header)
    ├── firmware.py              dsPIC33 tab: install, build, flash, start the dsPIC33 GUI
    ├── ctest.py                 compiles and runs the generated C code ("C test" tab)
    ├── presets.py               parameter sets as JSON files
    ├── presets/default.json     parameter set loaded at start
    ├── test_codegen.py          compiles the generated code and compares it with Python
    ├── fw_ui_test.py            browser test of the dsPIC33 tab
    └── requirements.txt
```

## Command line tool `fdesign`

### Build

You need a C99 compiler and GNU make. On Windows this means MinGW-w64 (for example WinLibs) or
MSYS2.

```sh
cd tools/filterdesign/fdesign
make                 # Windows/MinGW: mingw32-make
make REAL=float      # optional: float arithmetic like the PIC32 firmware
make test            # optional: verify ~370 designs against SciPy (needs Python + scipy, ~2 min)
```

The PC build computes in `double` by default. With `float`, narrow filters can miss the
specification. For example, a Chebyshev lowpass at 100 Hz with fs = 48 kHz reaches 0.51 dB
ripple instead of 0.50 dB.

### Usage

```
fdesign -t TYPE -c CHAR -r FS -p FPASS -s FSTOP [--ap DB] [--as DB] [-f text|json|sos] [--no-normalize]
```

| Option | Meaning |
|---|---|
| `-t` | `lowpass`, `highpass`, `bandpass`, `bandstop` (or `lp`, `hp`, `bp`, `bs`) |
| `-c` | `butterworth`, `chebyshev`, `elliptic` (or `butter`, `cheby`, `ellip`, `cauer`) |
| `-r` | Sampling rate in Hz |
| `-p` | Passband edge(s) in Hz. Use two values `f1,f2` for bandpass and bandstop. |
| `-s` | Stopband edge(s) in Hz. Use two values `f1,f2` for bandpass and bandstop. |
| `--ap` | Maximum passband attenuation in dB (default 1) |
| `--as` | Minimum stopband attenuation in dB (default 40) |
| `-f` | `text` (default), `json` (all results), `sos` (one line per section: `b0 b1 b2 a0 a1 a2`) |
| `--no-normalize` | Keep the gain from the library. By default the peak gain is set to 0 dB. |

Exit codes: 0 means OK, 1 a usage error, 2 an invalid specification and 3 a failed design (for
example when the order exceeds the limit).

```
$ fdesign -t bp -c elliptic -r 8000 -p 800,1200 -s 400,1800 --ap 3 --as 40
Filter        : elliptic bandpass
Sampling rate : 8000 Hz
Passband edge : 800 1200 Hz (max. 3 dB)
Stopband edge : 400 1800 Hz (min. 40 dB)
Order         : 6 (3 sections)
Achieved      : pass 1.47 1.47 dB, stop 57.14 52.81 dB -> specification met

  #  ord          b0               b1               b2               a1               a2
  1  2   1.287123799e-01  0.000000000e+00 -1.287123799e-01 -1.339694022e+00  8.712876201e-01
  ...
```

The result is a cascade of sections
`H(z) = Π (b0 + b1 z⁻¹ + b2 z⁻²) / (1 + a1 z⁻¹ + a2 z⁻²)`. The `sos` output uses the same row
layout as `scipy.signal.sosfilt`.

Limits: up to 16 sections. That is order 28 for lowpass and highpass, and order 2×16 for
bandpass and bandstop.

## GUI

```sh
filterdesign.bat              # Windows, repository root: tools\.venv (gui_setup.bat) or the python on the PATH

cd tools/filterdesign/gui
pip install -r requirements.txt
python app.py                 # opens http://127.0.0.1:8090 in the browser
python app.py --port 9000 --no-browser
python app.py --host 0.0.0.0  # allow access from other machines
python app.py --light         # start in light mode (default: dark)
```

The sun/moon button in the header switches between dark and light mode. Plots and colors
follow the chosen mode.

The GUI looks for the `fdesign` executable in `../fdesign` and builds it there with gcc if it is
missing (`fdcore.build_fdesign()`; it is not git-tracked). You can set the environment variable
`FDESIGN` to use another path.

You enter the specification (type, characteristic, sampling rate, band edges, ripple, stopband
attenuation) and the implementation (arithmetic, section scaling, Q format, C name). The design
is recomputed on every change.

| Tab | Content |
|---|---|
| Magnitude | Magnitude response in dB or linear, with linear or log frequency axis. The tolerance scheme is shaded red, and the quantized implementation is drawn as a dashed line. |
| Phase | Phase response, unwrapped or wrapped |
| Group delay | In samples or in ms |
| Pole / zero | z-plane with unit circle, multiplicities, and a list of radius and frequency |
| Impulse / step | Time responses of the design and of the implementation (fixed point is simulated bit-exactly) |
| Sections | Coefficients (fixed point as integers), pole radius, frequency and Q, peak gain and L1 norm at each section output |
| C code | Generated `.h` and `.c` for download |
| C test | Compiles and runs the C implementations and compares them with the reference (see below) |
| dsPIC33 | Checks for the board (sample rate in whole kSPS, CPU budget, specification, overflow) and the steps install, build, flash, open the dsPIC33 GUI (see below) |

The summary above the tabs shows the order, the achieved attenuation at the band edges, the
maximum pole radius, the settling time, the group delay and the attenuation reached by the
quantized implementation. It also shows the number of saturations in a fixed-point impulse test.

Zoom: use the mouse wheel on the frequency axis, box zoom from the toolbox, or the slider below
the plot. `?tab=phase` (or `group`, `pole`, `impulse`, `sections`, `ccode`, `ctest`) in the URL
opens a tab directly.

### Parameter sets

All parameters are saved together as a JSON file in the folder `gui/presets/`:
- the specification, including the band edges of every filter type you have edited
- the implementation settings
- the view options, including dark mode
- the settings of the C test

At start the GUI loads `presets/default.json`. If the file does not exist, it is created from the
built-in defaults. To change what the GUI starts with, save over `default.json`.

The **Parameter set** card at the top of the left panel offers:

| Control | Function |
|---|---|
| Drop-down | Lists the `*.json` files in the presets folder. Selecting a file loads it. The refresh button rescans the folder. |
| Save | Overwrites the current file |
| Save as | Saves under a new name in the presets folder. File names are reduced to safe characters, and `.json` is added. |
| Load file | Loads a JSON file from anywhere. It is not copied into the presets folder until you press Save. |

The card shows the current file name. "modified" means that there are unsaved changes, and
loading another file then asks whether to discard them. Invalid or missing entries in a file are
ignored and reported, and the affected fields keep their value.

Use another folder with `python app.py --presets DIR` or the environment variable
`FDESIGN_PRESETS`. The values in `default.json` take precedence over `--light`.

```json
{
  "format": "fdesign-gui", "version": 1,
  "spec": {"type": "bandpass", "characteristic": "elliptic", "fs": 8000, "ap": 1.0, "as": 40.0,
           "edges": {"bandpass": [400.0, 800.0, 1200.0, 1800.0]}},
  "implementation": {"arithmetic": "fixed32", "section_scaling": true, "auto_q": true,
                     "frac_bits": 30, "c_name": "iir_filter"},
  "view": {"dark": true, "magnitude_scale": "db", "frequency_axis": "lin", "tolerance_scheme": true,
           "implemented_response": true, "phase": "unwrap", "group_delay_unit": "samples",
           "time_response": "impulse", "test_view": "out"},
  "test": {"implementations": ["float", "double", "fixed32", "fixed16"], "signal": "noise",
           "f1": 979.8, "f2": 1980.0, "amplitude": 0.9, "samples": 2048, "compiler": "gcc"}
}
```

In `spec.edges`, the band edges are listed in ascending frequency order for each filter type. For
example, bandpass is lower stop, lower pass, upper pass, upper stop.

#### Example parameter sets

All examples meet their specification, also with the quantized coefficients of the selected
arithmetic. The generated C code passes the C test (bit-exact for fixed point). The only
exception is the overload demo, which saturates on purpose.

| File | Filter | fs | Arithmetic | Test signal |
|---|---|---|---|---|
| `dspic33_default_lowpass_200k` | Elliptic lowpass 15 kHz, 0.5/60 dB - the dsPIC33 firmware's default user filter (`src/core/user_filter.h`), against the signal generator's harmonics | 200 kHz | float | chirp |
| `firmware_example_bp_8k` | Elliptic bandpass 800–1200 Hz, 3/40 dB (as in the FilterDesign project's PIC32 example) | 8 kHz | fixed32 | noise |
| `telephone_band_bp_8k` | Chebyshev bandpass 300–3400 Hz, order 14 | 8 kHz | fixed16 | chirp, 0.5 FS |
| `dtmf_697hz_bp_8k` | Elliptic bandpass around the 697 Hz DTMF tone | 8 kHz | fixed32 | sine |
| `mains_hum_notch_50hz_1k` | Elliptic bandstop 48–52 Hz | 1 kHz | fixed32 | two tones |
| `audio_lowpass_48k` | Butterworth lowpass 3 kHz, 60 dB | 48 kHz | float | chirp |
| `audio_highpass_100hz_48k` | Chebyshev highpass 100 Hz | 48 kHz | float | chirp |
| `anti_alias_lowpass_44k1` | Elliptic lowpass 9 kHz, 0.1/80 dB, for decimation by 2 | 44.1 kHz | double | chirp |
| `speech_highpass_16k` | Butterworth highpass 120 Hz | 16 kHz | fixed16 | chirp, 0.5 FS |
| `overload_demo_speech_hp_fixed16` | Same filter, driven at 0.9 FS: shows saturation in the C test | 16 kHz | fixed16 | chirp, 0.9 FS |
| `sensor_lowpass_1k_fixed16` | Chebyshev lowpass 10 Hz | 1 kHz | fixed16 | step, 0.5 FS |
| `motor_current_lowpass_20k` | Chebyshev lowpass 1 kHz, 50 dB | 20 kHz | fixed16 | noise |
| `vibration_bandpass_10k` | Butterworth bandpass 100–1000 Hz, order 14 | 10 kHz | fixed32 | chirp, 0.5 FS |
| `ultrasonic_bandpass_40k_200k` | Elliptic bandpass 38–42 kHz | 200 kHz | fixed32 | sine |
| `wide_bandstop_audio_48k` | Chebyshev bandstop 1.5–4 kHz | 48 kHz | float | chirp |

Two findings from creating these sets:
- **Headroom:** section scaling only limits the steady-state peak gain. With a chirp or a step,
  high-order filters overshoot. The worst-case gain (L1 norm in the Sections tab) is 3–4.4 for
  the telephone, speech and vibration filters. That is why these sets are tested at 0.5 FS.
- **16-bit coefficients:** Butterworth filters meet their band edges exactly, so they have no
  margin for coefficient quantization. With 16-bit coefficients, the speech highpass first missed
  its stopband by 0.6 dB, and the sensor lowpass missed its passband edge by 0.02 dB. The sets
  were therefore given design margin or a different characteristic.

### Generated C code

| Arithmetic | Structure | Types |
|---|---|---|
| `float`, `double` | Transposed direct form II | Coefficients and state in the chosen type |
| `fixed32`, `fixed16` | Direct form I with rounding and saturation | `int32_t` / `int16_t` for samples and coefficients, `int64_t` for the accumulator |

Each filter provides the API `<name>_init()`, `<name>_process()` (one sample) and
`<name>_process_block()`. For fixed point, the code assumes an arithmetic right shift of negative
`int64_t` values. GCC, Clang, XC16, XC32, IAR and Keil all do this.

**Section scaling** (on by default) distributes the gain over the cascade so that the peak gain
at every section output is 0 dB. Without it, internal nodes of high-order elliptic filters
overflow in fixed point. The test showed several hundred saturations, and none with scaling.
**Auto Q** chooses the largest number of fractional bits for which all coefficients fit.

**Output gain** (dB, default 0) multiplies b0, b1 and b2 of the last section. No arithmetic
needs an extra operation per sample for it, and every node before the output keeps the
0 dB of section scaling.
- **Above 0 dB a signal clips.** The output saturates in fixed point, and the dsPIC33
  firmware clamps it to 0..4095. Clipping starts when the signal exceeds full scale divided
  by the gain. Nothing counts these clipped samples.
- **It adds no resolution.** The noise in the passband rises with the signal.
- **How the tool shows it:** The plots and the specification check are normalised to the
  gain. The summary names the gain. The fixed-point impulse test runs at ½ FS / gain.
- **How the tests drive it:** The C test and the test bench drive their signal at
  amplitude / gain, and the measured response is compared with the design times the gain.
- **What the firmware gets:** The gain is in the generated code (comment,
  `USER_FILTER_DESC`) and in `user_filter.json` (`gain_db`). The JSON's `sos` rows include
  the gain, so the dsPIC33 GUI's noise test compares against the right curve. Its
  thresholds are relative to the design's peak.

### Testing the C implementations

The **C test** tab compiles the generated code of the selected implementations (float, double,
fixed 32 bit, fixed 16 bit) with the host C compiler (`gcc`, or set `CC`). Each implementation
runs with a test signal: impulse, step, sine, chirp, white noise or two tones, with a chosen
amplitude and length. The tab then shows:

- a table per implementation with these columns:
  - build result
  - test bench verdict (PASS/FAIL)
  - bit-exact match with the fixed-point model
  - Q format
  - number of saturations
  - max. and RMS error against the double reference (fixed point also in LSB)
  - SNR
- two more table columns for the **measured frequency response**: the maximum deviation from the
  design in the passband, and the minimum stopband attenuation compared with the specification
  (✘ if it is missed)
- four plot views:
  - **output** against the reference
  - **error**
  - **measured magnitude**, computed from the impulse response of the compiled C code. It shows
    quantization effects such as limit cycles that the coefficient-based response cannot show.
  - **deviation from design**: measured minus design in dB, with the stopband shaded

  Accurate implementations lie exactly on top of each other in the magnitude view. Each
  implementation therefore has its own line pattern, the design is drawn as a wide translucent
  line underneath, and the deviation view separates the curves. Click a legend entry to hide or
  show a curve.
- the compiler commands and the test bench messages

Compiled programs are cached, so a new test signal does not trigger a recompile. The four
implementations are built in parallel.

**Test bench (.zip)** downloads, for the arithmetic selected in the Implementation panel:
- the filter (`.h`, `.c`)
- a test program `<name>_test.c`
- a `Makefile`
- `input.txt` with the test signal
- `expected.txt` with the reference output (fixed point: bit-exact model)

`make test` builds and runs it. The program prints PASS or FAIL and returns 0 or 1. This way the
same test also runs with another compiler, for example a cross compiler for the target.

### dsPIC33 tab

The way from the design to the board of this repository (`firmware.py`):

| Step | What it does |
|---|---|
| checks | the sample rate must be a whole number of kSPS between 1 and 40000 (the board's `stream on <ksps>`; a red check blocks the install), the CPU budget 200 MHz / fs per sample, the specification also after quantisation, no fixed-point overflow |
| 1 Install into firmware | `codegen.generate_firmware()` -> `src/core/user_filter.h` (the same code as the C code tab, `static inline`, plus id, description and design rate) and `src/core/user_filter.json` (spec, cascade, id - read by the dsPIC33 GUI) |
| 2 Build | `tools\build.bat` (EV74H48A) or `build.bat nano` (EV17P63A); OK only with exit code 0 and a .hex newer than the header |
| 3 Flash | EV74H48A: `ipecmd -TPPKOB4 -P33AK512MPS512 -M -F<hex> -OL` (newest MPLAB X, or `$IPECMD`; exit 9 = no programmer). EV17P63A: the .hex copied onto the Curiosity Nano's drive (the root holding `KIT-INFO.TXT`) - not yet tried on a board |
| 4 Open dsPIC33 GUI | `tools/adc_gui.py --sigproc user [--port COMx \| --fake] --http-port N`, in its own window; there the switch **filter on** and the **noise test** (the measured response against this design) |

Build and flash show their output line by line while they run, with the seconds counting. Do not
stop a flash half-way (closing the page, unplugging): an ipecmd killed while programming left the
PKOB4 answering nothing (`err = -10121`) until its USB cable was plugged again. A hung run is
stopped by itself after 240 s, its whole process tree (ipecmd.exe -> cmd -> java). A leftover
MPLAB X without a window (`mplab_ide64.exe` in the task list) can hold the PKOB4 too.

The line under the board shows which steps hold for the current design: installed (the header's
id is this design's), built (and the .hex is newer), flashed (from this session). `python
firmware.py --default` puts the repository's default filter back, `python firmware.py --fixtures
tests/host/user_filter` regenerates the fixtures of the firmware's host test.

The id is a CRC-32 of the generated code. The firmware reports it (`sigproc user` -> `user_id:`),
so the dsPIC33 GUI can tell whether the board runs the filter `user_filter.json` describes.

## Verification

- `fdesign/test/verify.py` designs 4 fixed and 120 random specifications with all three
  characteristics. Each design is checked independently with `scipy.signal.sosfreqz` for
  passband ripple, stopband attenuation, stability and 0 dB peak gain, and the order is
  compared with `buttord`, `cheb1ord` and `ellipord`. Result: 358 passed, 0 failed. 14 designs
  were rejected because their order exceeds the limit.
- `gui/test_codegen.py` generates code and test bench for 5 designs × 4 arithmetics × with and
  without scaling. It compiles them the same way as the C test tab, runs them with noise and
  compares the output. float and double are compared with `scipy.signal.sosfilt` (relative error
  below 1e-5 and exactly 0). Fixed point is compared bit-exactly with the Python model the GUI
  uses. In addition, the test bench must report PASS. Result: 40 of 40 passed. It also checks
  that the firmware host test's fixtures (`tests/host/user_filter`) match a fresh
  `firmware.py --fixtures` run.
- `gui/fw_ui_test.py` (playwright, Chrome) drives the dsPIC33 tab in a browser: install, build,
  the dsPIC33 GUI on its fake target with the filter `user`, its design rate, a grab through it.
  `--flash` adds the flash step - it programs a connected EV74H48A.
- The firmware side of the same path: `tests/host/test_user_filter_xcheck.py` (run by
  `tools\hosttest.bat`).

## Changes compared with the firmware library

`fdesign/lib/filter_design.c` is a copy of the FilterDesign project's `FilterDesign/filter_design.c`
(not in this repository) with these fixes:

1. Butterworth and Chebyshev bandstop computed the stopband edge with the bandpass formula, so
   the order was too low and the stopband attenuation was missed (36–38 dB instead of 40 dB).
2. The Cauer order was rounded up one step too far (`ceil(m + .5)` changed to `ceil(m)`).
3. The Cauer zero reordering read outside the array. The loop condition `i <= Sub_Filter || max >= 1`
   is now `max >= 1`.
4. Array overflows were reported as success (`return FALSE` = 0). There are now error codes, an
   order limit (`FLD_MAX_ORDER`), and errors from the BP/BS transformation are passed on.
5. All arithmetic uses the type `fld_real` (`double` on the PC), and duplicate prototypes were
   removed.

The front end (`src/fdesign.c`) adds:
- the mapping from passband and stopband edges to F1–F4
- for bandpass and bandstop, the stricter of the two stopband edges (the library itself only
  uses one edge and assumes geometric symmetry)
- removal of the pole/zero pair at z = −1 that the library uses to express first-order
  sections as biquads
- normalization of the peak gain to 0 dB

Known limitation: for bandstop filters, SciPy sometimes finds a lower order because it shifts
the passband edges by optimization. The designs here meet the specification, but are not always
minimal.
