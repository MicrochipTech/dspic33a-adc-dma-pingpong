/*********************************************************************

Copyright (c) 2019 Martin Ruppert

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

*********************************************************************/

#ifndef __FILTER_DESIGN
#define __FILTER_DESIGN

/*
 * PC build of the FilterDesign library.
 * Derived from ../../../FilterDesign/filter_design.h with these changes:
 *  - all arithmetic uses fld_real (double by default on the PC, float on the PIC32)
 *  - error codes instead of returning FALSE (= 0 = success) on overflow
 *  - order limit FLD_MAX_ORDER protects the internal arrays
 *  - duplicate prototypes and the bool macro removed
 */

#include <math.h>

#ifndef FLD_REAL_TYPE
#define FLD_REAL_TYPE double
#endif
typedef FLD_REAL_TYPE fld_real;

#define arsinh(x)           (log((x)+sqrt((x)*(x)+1)))
#define arcosh(x)           (log((x)+sqrt((x)*(x)-1)))  /* only valid for x >= 1 */
#define MAX                 16          /* max. number of biquads */
#define MAXDIGFILTKOEFF     5*MAX
#define DB                  (log(10.)/10.)
#define PI                  3.14159265358979323846
#define FALSE               0
#define TRUE                1

/* max. order of the reference lowpass (limited by the internal Cauer arrays);
   bandpass/bandstop are additionally limited to MAX biquads = order 16 */
#define FLD_MAX_ORDER       28

/* error codes (dsp->Error / return value of the design functions) */
#define FLD_OK              0
#define FLD_ERR_ORDER       2   /* order < 1 or too high for the internal arrays */

#define INTEGER_PRECISION   27

/* Codes for the selection of the filter characteristic */
#define BUTT        0x01
#define TSCHE       0x02
#define CAU         0x04

/* Codes for selecting the filter type */
#define TP          0x08
#define HP          0x10
#define BP          0x20
#define BS          0x40

#define N_EQUAL_ZERO	1

typedef struct {
    int Error;
    fld_real Samplerate;
    short Coefficient_Block_2[64];
    short Coefficient_Block_1[16];
    fld_real Az_Biquad[MAX + 1];
    fld_real Ay_Biquad[MAX + 1];
    fld_real Ax_Biquad[MAX + 1];
    fld_real Aw_Biquad[MAX + 1];
    fld_real Av_Biquad[MAX + 1];
    fld_real F_Coeff[MAX + 1];
    fld_real E_Coeff[MAX + 1];
    fld_real D_Coeff[MAX + 1];
    fld_real C_Coeff[MAX + 1];
    fld_real B_Coeff[MAX + 1];
    fld_real A_Coeff[MAX + 1];
    fld_real F4_Analog;
    fld_real F3_Analog;
    fld_real F2_Analog;
    fld_real F1_Analog;
    fld_real f4_Digital;
    fld_real f3_Digital;
    fld_real f2_Digital;
    fld_real f1_Digital;
    fld_real as_Blocking_Attenuation;
    fld_real ad_Passband_Attenuation;
    fld_real Epsilon;
    int Sub_Filter;
    int n_Order;
    fld_real constant_values[20];
    fld_real omega_d[20];
    fld_real s_imaginary_part_complex_zeros[20];
    fld_real r_real_part_complex_zeros[20];
    fld_real omega_s;
    fld_real cauer_const;
    fld_real b_reference_lp_coeff[MAX + 1];
    fld_real a_reference_lp_coeff[MAX + 1];
} DSP_DATA;

void FLD_Set_Instance(DSP_DATA *dsp_instance);
void FLD_Init_Filter(void);
void FLD_Frequency_Transformation(void);
void FLD_Coefficient_Assignment(void);
void FLD_InitCoeffsFloat(fld_real *num, fld_real *den, fld_real *taps, int N);
void FLD_InitCoeffsFixpoint(long *num, long *den, long *taps, int N);

int FLD_TP_Butterworth(void);
int FLD_HP_Butterworth(void);
int FLD_BP_Butterworth(void);
int FLD_BS_Butterworth(void);
int FLD_TP_Tschebycheff(void);
int FLD_HP_Tschebycheff(void);
int FLD_BP_Tschebycheff(void);
int FLD_BS_Tschebycheff(void);
int FLD_TP_Cauer(void);
int FLD_HP_Cauer(void);
int FLD_BP_Cauer(void);
int FLD_BS_Cauer(void);

/* internal helpers */
int FLD_Referenz_TP_Butterworth(void);
int FLD_Referenz_TP_Tschebycheff(void);
int FLD_Referenz_TP_Cauer(void);
int FLD_BP_Transformation(int filt_char);
int FLD_BS_Transformation(int filt_char);
void FLD_Get_Constants(void);
fld_real FLD_gammaM(fld_real a, fld_real b);
fld_real FLD_u_frq(fld_real omega_s, int nn);
fld_real FLD_u_db(fld_real as, fld_real ad);
fld_real FLD_Sn(fld_real u, fld_real z);
fld_real Frequency_Transformation(fld_real f, fld_real fa);

#endif
