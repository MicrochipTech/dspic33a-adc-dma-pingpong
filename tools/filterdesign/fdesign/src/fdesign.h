/*
 * fdesign.h - specification based front end for the FilterDesign library
 *
 * The library (lib/filter_design.c) works with four corner frequencies F1..F4
 * whose meaning depends on the filter type. This layer accepts a plain
 * passband/stopband specification, maps it onto F1..F4, runs the design and
 * returns a cascade of second order sections (SOS) in the usual form
 *
 *     H(z) = prod_k (b0 + b1 z^-1 + b2 z^-2) / (1 + a1 z^-1 + a2 z^-2)
 *
 * Copyright (c) 2019 Martin Ruppert, MIT license (see lib/filter_design.c)
 */

#ifndef FDESIGN_H
#define FDESIGN_H

#include <stddef.h>

#define FD_MAX_SECTIONS 16

typedef enum { FD_LOWPASS, FD_HIGHPASS, FD_BANDPASS, FD_BANDSTOP } fd_type;
typedef enum { FD_BUTTERWORTH, FD_CHEBYSHEV, FD_ELLIPTIC } fd_char;

typedef struct {
    fd_type type;
    fd_char characteristic;
    double fs;          /* sampling rate in Hz */
    double fpass[2];    /* passband edge(s) in Hz: [0] for LP/HP, [0..1] for BP/BS */
    double fstop[2];    /* stopband edge(s) in Hz: [0] for LP/HP, [0..1] for BP/BS */
    double ap;          /* max. passband attenuation in dB (> 0) */
    double as;          /* min. stopband attenuation in dB (> ap) */
    int normalize;      /* 1: scale the overall peak gain to exactly 0 dB */
} fd_spec;

typedef struct {
    double b[3];        /* numerator   b0, b1, b2 */
    double a[3];        /* denominator 1, a1, a2  */
    int order;          /* 1: first order section (b2 = a2 = 0), 2: biquad */
} fd_section;

typedef struct {
    int order;                  /* filter order of the reference lowpass (BP/BS: digital order is 2x) */
    int n_sections;
    fd_section sec[FD_MAX_SECTIONS];
    double gain;                /* scale factor applied by normalization (1.0 if none) */
    double omega_s;             /* normalized stopband edge of the reference lowpass */
    double att_pass[2];         /* achieved attenuation at the passband edge(s) in dB */
    double att_stop[2];         /* achieved attenuation at the stopband edge(s) in dB */
    int n_edges;                /* 1 for LP/HP, 2 for BP/BS */
} fd_result;

/* Checks the specification. Returns 0 if valid, otherwise writes a reason to msg. */
int fd_validate(const fd_spec *spec, char *msg, size_t msg_len);

/* Designs the filter. Returns 0 on success, otherwise writes a reason to msg. */
int fd_design(const fd_spec *spec, fd_result *res, char *msg, size_t msg_len);

/* Magnitude of the cascade at frequency f (Hz). */
double fd_magnitude(const fd_result *res, double f, double fs);

const char *fd_type_name(fd_type t);
const char *fd_char_name(fd_char c);

#endif
