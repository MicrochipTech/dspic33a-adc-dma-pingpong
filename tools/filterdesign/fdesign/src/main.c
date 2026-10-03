/*
 * main.c - command line front end of the FilterDesign library
 *
 * Copyright (c) 2019 Martin Ruppert, MIT license (see lib/filter_design.c)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "fdesign.h"

#define FDESIGN_VERSION "1.0.0"

/* exit codes */
#define EXIT_OK        0
#define EXIT_USAGE     1
#define EXIT_SPEC      2
#define EXIT_DESIGN    3

typedef enum { OUT_TEXT, OUT_JSON, OUT_SOS } out_format;

static void usage(FILE *f) {
    fprintf(f,
        "fdesign " FDESIGN_VERSION " - IIR filter design (Butterworth, Chebyshev I, elliptic)\n"
        "\n"
        "usage: fdesign -t TYPE -c CHAR -r FS -p FPASS -s FSTOP [options]\n"
        "\n"
        "  -t, --type TYPE      lowpass|lp, highpass|hp, bandpass|bp, bandstop|bs\n"
        "  -c, --char CHAR      butterworth|butter, chebyshev|cheby, elliptic|ellip|cauer\n"
        "  -r, --fs HZ          sampling rate in Hz\n"
        "  -p, --pass F[,F]     passband edge(s) in Hz (two values for bandpass/bandstop)\n"
        "  -s, --stop F[,F]     stopband edge(s) in Hz (two values for bandpass/bandstop)\n"
        "      --ap DB          max. passband attenuation in dB (default 1)\n"
        "      --as DB          min. stopband attenuation in dB (default 40)\n"
        "  -f, --format FMT     text (default), json, sos\n"
        "      --no-normalize   keep the gain of the library (peak gain not forced to 0 dB)\n"
        "  -h, --help           show this help\n"
        "  -v, --version        show the version\n"
        "\n"
        "Output: cascade of sections  H(z) = prod (b0 + b1 z^-1 + b2 z^-2) / (1 + a1 z^-1 + a2 z^-2)\n"
        "        'sos' prints one line per section: b0 b1 b2 a0 a1 a2 (scipy sos layout)\n"
        "\n"
        "example: fdesign -t bp -c elliptic -r 8000 -p 800,1200 -s 400,1800 --ap 3 --as 40\n"
        "\n"
        "exit codes: 0 ok, 1 usage error, 2 invalid specification, 3 design failed\n");
}

static int parse_type(const char *v, fd_type *t) {
    if (!strcmp(v, "lowpass") || !strcmp(v, "lp")) *t = FD_LOWPASS;
    else if (!strcmp(v, "highpass") || !strcmp(v, "hp")) *t = FD_HIGHPASS;
    else if (!strcmp(v, "bandpass") || !strcmp(v, "bp")) *t = FD_BANDPASS;
    else if (!strcmp(v, "bandstop") || !strcmp(v, "bs")) *t = FD_BANDSTOP;
    else return 1;
    return 0;
}

static int parse_char(const char *v, fd_char *c) {
    if (!strcmp(v, "butterworth") || !strcmp(v, "butter")) *c = FD_BUTTERWORTH;
    else if (!strcmp(v, "chebyshev") || !strcmp(v, "cheby") || !strcmp(v, "cheby1")) *c = FD_CHEBYSHEV;
    else if (!strcmp(v, "elliptic") || !strcmp(v, "ellip") || !strcmp(v, "cauer")) *c = FD_ELLIPTIC;
    else return 1;
    return 0;
}

static int parse_number(const char *v, double *x) {
    char *end;
    *x = strtod(v, &end);
    return (end == v || *end != '\0') ? 1 : 0;
}

/* parses "f" or "f1,f2"; returns the number of values or -1 on error */
static int parse_list(const char *v, double out[2]) {
    char buf[128], *comma;
    if (strlen(v) >= sizeof buf) return -1;
    strcpy(buf, v);
    comma = strchr(buf, ',');
    if (comma) {
        *comma = '\0';
        if (parse_number(buf, &out[0]) || parse_number(comma + 1, &out[1])) return -1;
        return 2;
    }
    return parse_number(buf, &out[0]) ? -1 : 1;
}

static void json_string(const char *s) {
    putchar('"');
    for (; *s; s++) {
        if (*s == '"' || *s == '\\') putchar('\\');
        putchar(*s);
    }
    putchar('"');
}

static void fail(out_format fmt, int code, const char *text) {
    if (fmt == OUT_JSON) {
        printf("{\"error\": ");
        json_string(text);
        printf(", \"exit_code\": %d}\n", code);
    } else {
        fprintf(stderr, "fdesign: %s\n", text);
    }
    exit(code);
}

static int spec_met(const fd_spec *s, const fd_result *r) {
    int i;
    for (i = 0; i < r->n_edges; i++) {
        if (r->att_pass[i] > s->ap + 1e-3 || r->att_stop[i] < s->as - 1e-3) return 0;
    }
    return 1;
}

static void print_json(const fd_spec *s, const fd_result *r) {
    int i, k;
    printf("{\n");
    printf("  \"version\": \"%s\",\n", FDESIGN_VERSION);
    printf("  \"type\": \"%s\",\n", fd_type_name(s->type));
    printf("  \"characteristic\": \"%s\",\n", fd_char_name(s->characteristic));
    printf("  \"fs\": %.17g,\n", s->fs);
    printf("  \"fpass\": [");
    for (i = 0; i < r->n_edges; i++) printf("%s%.17g", i ? ", " : "", s->fpass[i]);
    printf("],\n  \"fstop\": [");
    for (i = 0; i < r->n_edges; i++) printf("%s%.17g", i ? ", " : "", s->fstop[i]);
    printf("],\n");
    printf("  \"ap\": %.17g,\n  \"as\": %.17g,\n", s->ap, s->as);
    printf("  \"order\": %d,\n", r->order);
    printf("  \"digital_order\": %d,\n",
           (s->type == FD_BANDPASS || s->type == FD_BANDSTOP) ? 2 * r->order : r->order);
    printf("  \"omega_s\": %.17g,\n", r->omega_s);
    printf("  \"gain\": %.17g,\n", r->gain);
    printf("  \"att_pass\": [");
    for (i = 0; i < r->n_edges; i++) printf("%s%.17g", i ? ", " : "", r->att_pass[i]);
    printf("],\n  \"att_stop\": [");
    for (i = 0; i < r->n_edges; i++) printf("%s%.17g", i ? ", " : "", r->att_stop[i]);
    printf("],\n  \"spec_met\": %s,\n", spec_met(s, r) ? "true" : "false");
    printf("  \"sections\": [\n");
    for (k = 0; k < r->n_sections; k++) {
        const fd_section *q = &r->sec[k];
        printf("    {\"order\": %d, \"b\": [%.17g, %.17g, %.17g], \"a\": [%.17g, %.17g, %.17g]}%s\n",
               q->order, q->b[0], q->b[1], q->b[2], q->a[0], q->a[1], q->a[2],
               k + 1 < r->n_sections ? "," : "");
    }
    printf("  ]\n}\n");
}

static void print_text(const fd_spec *s, const fd_result *r) {
    int i, k;
    printf("Filter        : %s %s\n", fd_char_name(s->characteristic), fd_type_name(s->type));
    printf("Sampling rate : %g Hz\n", s->fs);
    printf("Passband edge :");
    for (i = 0; i < r->n_edges; i++) printf(" %g", s->fpass[i]);
    printf(" Hz (max. %g dB)\nStopband edge :", s->ap);
    for (i = 0; i < r->n_edges; i++) printf(" %g", s->fstop[i]);
    printf(" Hz (min. %g dB)\n", s->as);
    printf("Order         : %d (%d sections)\n",
           (s->type == FD_BANDPASS || s->type == FD_BANDSTOP) ? 2 * r->order : r->order, r->n_sections);
    printf("Achieved      : pass");
    for (i = 0; i < r->n_edges; i++) printf(" %.2f", r->att_pass[i]);
    printf(" dB, stop");
    for (i = 0; i < r->n_edges; i++) printf(" %.2f", r->att_stop[i]);
    printf(" dB -> %s\n\n", spec_met(s, r) ? "specification met" : "SPECIFICATION NOT MET");
    printf("  #  ord          b0               b1               b2               a1               a2\n");
    for (k = 0; k < r->n_sections; k++) {
        const fd_section *q = &r->sec[k];
        printf("%3d  %d  %16.9e %16.9e %16.9e %16.9e %16.9e\n",
               k + 1, q->order, q->b[0], q->b[1], q->b[2], q->a[1], q->a[2]);
    }
}

int main(int argc, char **argv) {
    fd_spec spec;
    fd_result res;
    out_format fmt = OUT_TEXT;
    char msg[256];
    int i, n_pass = 0, n_stop = 0, have_type = 0, have_char = 0, have_fs = 0, err;

    memset(&spec, 0, sizeof spec);
    spec.ap = 1.0;
    spec.as = 40.0;
    spec.normalize = 1;

    /* the output format is needed for error reporting, so look for it first */
    for (i = 1; i + 1 < argc; i++) {
        if (!strcmp(argv[i], "-f") || !strcmp(argv[i], "--format")) {
            if (!strcmp(argv[i + 1], "json")) fmt = OUT_JSON;
            else if (!strcmp(argv[i + 1], "sos")) fmt = OUT_SOS;
            else if (!strcmp(argv[i + 1], "text")) fmt = OUT_TEXT;
            else fail(OUT_TEXT, EXIT_USAGE, "unknown output format");
        }
    }

    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        const char *v = (i + 1 < argc) ? argv[i + 1] : NULL;

        if (!strcmp(a, "-h") || !strcmp(a, "--help")) {
            usage(stdout);
            return EXIT_OK;
        } else if (!strcmp(a, "-v") || !strcmp(a, "--version")) {
            printf("fdesign %s\n", FDESIGN_VERSION);
            return EXIT_OK;
        } else if (!strcmp(a, "--no-normalize")) {
            spec.normalize = 0;
            continue;
        }

        if (!v) {
            snprintf(msg, sizeof msg, "missing value for option %s (see --help)", a);
            fail(fmt, EXIT_USAGE, msg);
        }
        if (!strcmp(a, "-t") || !strcmp(a, "--type")) {
            if (parse_type(v, &spec.type)) fail(fmt, EXIT_USAGE, "unknown filter type");
            have_type = 1;
        } else if (!strcmp(a, "-c") || !strcmp(a, "--char")) {
            if (parse_char(v, &spec.characteristic)) fail(fmt, EXIT_USAGE, "unknown characteristic");
            have_char = 1;
        } else if (!strcmp(a, "-r") || !strcmp(a, "--fs")) {
            if (parse_number(v, &spec.fs)) fail(fmt, EXIT_USAGE, "invalid sampling rate");
            have_fs = 1;
        } else if (!strcmp(a, "-p") || !strcmp(a, "--pass")) {
            if ((n_pass = parse_list(v, spec.fpass)) < 0) fail(fmt, EXIT_USAGE, "invalid passband edge");
        } else if (!strcmp(a, "-s") || !strcmp(a, "--stop")) {
            if ((n_stop = parse_list(v, spec.fstop)) < 0) fail(fmt, EXIT_USAGE, "invalid stopband edge");
        } else if (!strcmp(a, "--ap")) {
            if (parse_number(v, &spec.ap)) fail(fmt, EXIT_USAGE, "invalid passband attenuation");
        } else if (!strcmp(a, "--as")) {
            if (parse_number(v, &spec.as)) fail(fmt, EXIT_USAGE, "invalid stopband attenuation");
        } else if (!strcmp(a, "-f") || !strcmp(a, "--format")) {
            /* already handled */
        } else {
            snprintf(msg, sizeof msg, "unknown option %s (see --help)", a);
            fail(fmt, EXIT_USAGE, msg);
        }
        i++;
    }

    if (argc == 1) {
        usage(stderr);
        return EXIT_USAGE;
    }
    if (!have_type || !have_char || !have_fs || !n_pass || !n_stop) {
        fail(fmt, EXIT_USAGE, "options -t, -c, -r, -p and -s are required (see --help)");
    }
    {
        int need = (spec.type == FD_BANDPASS || spec.type == FD_BANDSTOP) ? 2 : 1;
        if (n_pass != need || n_stop != need) {
            fail(fmt, EXIT_USAGE, need == 2 ? "bandpass/bandstop need two passband and two stopband edges"
                                            : "lowpass/highpass need one passband and one stopband edge");
        }
    }

    if (fd_validate(&spec, msg, sizeof msg) != 0) fail(fmt, EXIT_SPEC, msg);
    err = fd_design(&spec, &res, msg, sizeof msg);
    if (err != 0) fail(fmt, EXIT_DESIGN, msg);

    switch (fmt) {
        case OUT_JSON:
            print_json(&spec, &res);
            break;
        case OUT_SOS:
            for (i = 0; i < res.n_sections; i++) {
                const fd_section *q = &res.sec[i];
                printf("%.17g %.17g %.17g %.17g %.17g %.17g\n",
                       q->b[0], q->b[1], q->b[2], q->a[0], q->a[1], q->a[2]);
            }
            break;
        default:
            print_text(&spec, &res);
            break;
    }
    return EXIT_OK;
}
