/*
 * fdesign.c - specification based front end for the FilterDesign library
 *
 * Copyright (c) 2019 Martin Ruppert, MIT license (see lib/filter_design.c)
 */

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "fdesign.h"
#include "filter_design.h"

#define NORM_GRID 16384

static void set_msg(char *msg, size_t len, const char *text) {
    if (msg && len) {
        snprintf(msg, len, "%s", text);
    }
}

const char *fd_type_name(fd_type t) {
    switch (t) {
        case FD_LOWPASS: return "lowpass";
        case FD_HIGHPASS: return "highpass";
        case FD_BANDPASS: return "bandpass";
        case FD_BANDSTOP: return "bandstop";
    }
    return "?";
}

const char *fd_char_name(fd_char c) {
    switch (c) {
        case FD_BUTTERWORTH: return "butterworth";
        case FD_CHEBYSHEV: return "chebyshev";
        case FD_ELLIPTIC: return "elliptic";
    }
    return "?";
}

int fd_validate(const fd_spec *s, char *msg, size_t len) {
    int i, n = (s->type == FD_BANDPASS || s->type == FD_BANDSTOP) ? 2 : 1;
    double nyq = s->fs / 2.0;

    if (!(s->fs > 0.0)) {
        set_msg(msg, len, "sampling rate must be > 0");
        return 1;
    }
    for (i = 0; i < n; i++) {
        if (!(s->fpass[i] > 0.0 && s->fpass[i] < nyq) || !(s->fstop[i] > 0.0 && s->fstop[i] < nyq)) {
            set_msg(msg, len, "all band edges must lie between 0 and fs/2");
            return 1;
        }
    }
    if (!(s->ap > 0.0)) {
        set_msg(msg, len, "passband attenuation must be > 0 dB");
        return 1;
    }
    if (!(s->as > s->ap)) {
        set_msg(msg, len, "stopband attenuation must be greater than passband attenuation");
        return 1;
    }
    switch (s->type) {
        case FD_LOWPASS:
            if (!(s->fpass[0] < s->fstop[0])) {
                set_msg(msg, len, "lowpass requires fpass < fstop");
                return 1;
            }
            break;
        case FD_HIGHPASS:
            if (!(s->fstop[0] < s->fpass[0])) {
                set_msg(msg, len, "highpass requires fstop < fpass");
                return 1;
            }
            break;
        case FD_BANDPASS:
            if (!(s->fstop[0] < s->fpass[0] && s->fpass[0] < s->fpass[1] && s->fpass[1] < s->fstop[1])) {
                set_msg(msg, len, "bandpass requires fstop1 < fpass1 < fpass2 < fstop2");
                return 1;
            }
            break;
        case FD_BANDSTOP:
            if (!(s->fpass[0] < s->fstop[0] && s->fstop[0] < s->fstop[1] && s->fstop[1] < s->fpass[1])) {
                set_msg(msg, len, "bandstop requires fpass1 < fstop1 < fstop2 < fpass2");
                return 1;
            }
            break;
        default:
            set_msg(msg, len, "unknown filter type");
            return 1;
    }
    return 0;
}

double fd_magnitude(const fd_result *res, double f, double fs) {
    int k;
    double w = 2.0 * PI * f / fs;
    double c1 = cos(w), s1 = sin(w), c2 = cos(2.0 * w), s2 = sin(2.0 * w);
    double mag = 1.0;

    for (k = 0; k < res->n_sections; k++) {
        const fd_section *q = &res->sec[k];
        double nr = q->b[0] + q->b[1] * c1 + q->b[2] * c2;
        double ni = -q->b[1] * s1 - q->b[2] * s2;
        double dr = q->a[0] + q->a[1] * c1 + q->a[2] * c2;
        double di = -q->a[1] * s1 - q->a[2] * s2;
        mag *= sqrt((nr * nr + ni * ni) / (dr * dr + di * di));
    }
    return mag;
}

/*
 * The library derives the stopband edge of the reference lowpass from only one
 * stopband edge (BP: F4, BS: F3) and implicitly assumes geometric symmetry.
 * Pick the stricter of both edges and, if needed, mirror it geometrically
 * around the center frequency so that both stopband edges are met.
 */
static void select_strict_edges(fd_type type, DSP_DATA *d) {
    if (type == FD_BANDPASS) {
        double f0sq = d->f2_Digital * d->f3_Digital;
        double bw = d->f3_Digital - d->f2_Digital;
        double om_lo = fabs(d->f1_Digital * d->f1_Digital - f0sq) / (d->f1_Digital * bw);
        double om_hi = fabs(d->f4_Digital * d->f4_Digital - f0sq) / (d->f4_Digital * bw);
        if (om_lo < om_hi) {
            d->f4_Digital = f0sq / d->f1_Digital;   /* mirror of the lower edge */
        }
    } else if (type == FD_BANDSTOP) {
        double f0sq = d->f1_Digital * d->f4_Digital;
        double bw = d->f4_Digital - d->f1_Digital;
        double om_lo = d->f2_Digital * bw / fabs(d->f2_Digital * d->f2_Digital - f0sq);
        double om_hi = d->f3_Digital * bw / fabs(d->f3_Digital * d->f3_Digital - f0sq);
        double edge = (om_lo < om_hi) ? d->f2_Digital : d->f3_Digital;
        d->f3_Digital = (edge * edge > f0sq) ? edge : f0sq / edge;
    }
}

/* Removes the pole/zero pair at z = -1 that the library uses to express a
   first order section as a biquad (F = 0). */
static void reduce_first_order(fd_section *q) {
    double den_m1 = q->a[0] - q->a[1] + q->a[2];
    double num_m1 = q->b[0] - q->b[1] + q->b[2];
    double scale = fabs(q->b[0]) + fabs(q->b[1]) + fabs(q->b[2]);

    if (fabs(den_m1) < 1e-9 && fabs(num_m1) < 1e-9 * (scale > 0 ? scale : 1.0)) {
        /* divide by (1 + z^-1) */
        q->a[1] = q->a[1] - q->a[0];
        q->a[2] = 0.0;
        q->b[1] = q->b[1] - q->b[0];
        q->b[2] = 0.0;
        q->order = 1;
    }
}

int fd_design(const fd_spec *s, fd_result *res, char *msg, size_t len) {
    static DSP_DATA d;
    int err, k, i;
    char buf[160];

    if (fd_validate(s, msg, len) != 0) {
        return 1;
    }
    memset(&d, 0, sizeof d);
    memset(res, 0, sizeof *res);
    FLD_Set_Instance(&d);

    d.Samplerate = s->fs;
    d.ad_Passband_Attenuation = s->ap;
    d.as_Blocking_Attenuation = s->as;
    switch (s->type) {
        case FD_LOWPASS:
            d.F1_Analog = s->fpass[0];
            d.F2_Analog = s->fstop[0];
            d.F3_Analog = s->fpass[0];
            d.F4_Analog = s->fstop[0];
            break;
        case FD_HIGHPASS:
            d.F1_Analog = s->fstop[0];
            d.F2_Analog = s->fpass[0];
            d.F3_Analog = s->fstop[0];
            d.F4_Analog = s->fpass[0];
            break;
        case FD_BANDPASS:
            d.F1_Analog = s->fstop[0];
            d.F2_Analog = s->fpass[0];
            d.F3_Analog = s->fpass[1];
            d.F4_Analog = s->fstop[1];
            break;
        case FD_BANDSTOP:
            d.F1_Analog = s->fpass[0];
            d.F2_Analog = s->fstop[0];
            d.F3_Analog = s->fstop[1];
            d.F4_Analog = s->fpass[1];
            break;
    }

    FLD_Frequency_Transformation();
    select_strict_edges(s->type, &d);
    FLD_Init_Filter();

    switch (s->characteristic * 4 + s->type) {
        case FD_BUTTERWORTH * 4 + FD_LOWPASS:  err = FLD_TP_Butterworth(); break;
        case FD_BUTTERWORTH * 4 + FD_HIGHPASS: err = FLD_HP_Butterworth(); break;
        case FD_BUTTERWORTH * 4 + FD_BANDPASS: err = FLD_BP_Butterworth(); break;
        case FD_BUTTERWORTH * 4 + FD_BANDSTOP: err = FLD_BS_Butterworth(); break;
        case FD_CHEBYSHEV * 4 + FD_LOWPASS:    err = FLD_TP_Tschebycheff(); break;
        case FD_CHEBYSHEV * 4 + FD_HIGHPASS:   err = FLD_HP_Tschebycheff(); break;
        case FD_CHEBYSHEV * 4 + FD_BANDPASS:   err = FLD_BP_Tschebycheff(); break;
        case FD_CHEBYSHEV * 4 + FD_BANDSTOP:   err = FLD_BS_Tschebycheff(); break;
        case FD_ELLIPTIC * 4 + FD_LOWPASS:     err = FLD_TP_Cauer(); break;
        case FD_ELLIPTIC * 4 + FD_HIGHPASS:    err = FLD_HP_Cauer(); break;
        case FD_ELLIPTIC * 4 + FD_BANDPASS:    err = FLD_BP_Cauer(); break;
        case FD_ELLIPTIC * 4 + FD_BANDSTOP:    err = FLD_BS_Cauer(); break;
        default:
            set_msg(msg, len, "unknown filter characteristic");
            return 1;
    }
    if (err != 0) {
        snprintf(buf, sizeof buf, "design failed: required order %d exceeds the limit "
                 "(%d sections, order 16 for bandpass/bandstop)", d.n_Order, MAX);
        set_msg(msg, len, err == FLD_ERR_ORDER ? buf : "design failed");
        return 2;
    }
    if (d.Sub_Filter < 1 || d.Sub_Filter > FD_MAX_SECTIONS) {
        set_msg(msg, len, "design failed: invalid number of sections");
        return 2;
    }

    FLD_Coefficient_Assignment();
    res->order = d.n_Order;
    res->omega_s = d.omega_s;
    res->n_sections = d.Sub_Filter;
    for (k = 0; k < d.Sub_Filter; k++) {
        fd_section *q = &res->sec[k];
        q->b[0] = d.Av_Biquad[k];
        q->b[1] = d.Aw_Biquad[k] * d.Av_Biquad[k];
        q->b[2] = d.Ax_Biquad[k] * d.Av_Biquad[k];
        q->a[0] = 1.0;
        q->a[1] = -d.Ay_Biquad[k];
        q->a[2] = -d.Az_Biquad[k];
        q->order = 2;
        for (i = 0; i < 3; i++) {
            if (!isfinite(q->b[i]) || !isfinite(q->a[i])) {
                set_msg(msg, len, "design failed: non-finite coefficient");
                return 2;
            }
        }
        reduce_first_order(q);
    }

    res->gain = 1.0;
    if (s->normalize) {
        double peak = 0.0;
        for (i = 0; i <= NORM_GRID; i++) {
            double m = fd_magnitude(res, 0.5 * s->fs * i / NORM_GRID, s->fs);
            if (m > peak) peak = m;
        }
        if (peak > 0.0) {
            res->gain = 1.0 / peak;
            for (i = 0; i < 3; i++) {
                res->sec[0].b[i] *= res->gain;
            }
        }
    }

    res->n_edges = (s->type == FD_BANDPASS || s->type == FD_BANDSTOP) ? 2 : 1;
    for (i = 0; i < res->n_edges; i++) {
        res->att_pass[i] = -20.0 * log10(fd_magnitude(res, s->fpass[i], s->fs));
        res->att_stop[i] = -20.0 * log10(fd_magnitude(res, s->fstop[i], s->fs));
    }
    return 0;
}
