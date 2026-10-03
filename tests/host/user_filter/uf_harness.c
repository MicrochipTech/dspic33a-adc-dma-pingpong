/*******************************************************************************
 * Copyright (C) 2026 Microchip Technology Inc. and its subsidiaries.
 *
 * Subject to your compliance with these terms, you may use Microchip software
 * and any derivatives exclusively with Microchip products. It is your
 * responsibility to comply with third party license terms applicable to your
 * use of third party software (including open source software) that may
 * accompany Microchip software.
 *
 * THIS SOFTWARE IS SUPPLIED BY MICROCHIP "AS IS". NO WARRANTIES, WHETHER
 * EXPRESS, IMPLIED OR STATUTORY, APPLY TO THIS SOFTWARE, INCLUDING ANY IMPLIED
 * WARRANTIES OF NON-INFRINGEMENT, MERCHANTABILITY, AND FITNESS FOR A
 * PARTICULAR PURPOSE.
 *
 * IN NO EVENT WILL MICROCHIP BE LIABLE FOR ANY INDIRECT, SPECIAL, PUNITIVE,
 * INCIDENTAL OR CONSEQUENTIAL LOSS, DAMAGE, COST OR EXPENSE OF ANY KIND
 * WHATSOEVER RELATED TO THE SOFTWARE, HOWEVER CAUSED, EVEN IF MICROCHIP HAS
 * BEEN ADVISED OF THE POSSIBILITY OR THE DAMAGES ARE FORESEEABLE. TO THE
 * FULLEST EXTENT ALLOWED BY LAW, MICROCHIP'S TOTAL LIABILITY ON ALL CLAIMS IN
 * ANY WAY RELATED TO THIS SOFTWARE WILL NOT EXCEED THE AMOUNT OF FEES, IF ANY,
 * THAT YOU HAVE PAID DIRECTLY TO MICROCHIP FOR THIS SOFTWARE.
 ******************************************************************************/

/*
 * uf_harness.c - src/core/sigproc.c's "sigproc user" path on a host gcc, for
 * tests/host/test_user_filter_xcheck.py (03.10.2026). That script compiles
 * this file with a copy of sigproc.c once per fixture folder (float, double,
 * fixed32, fixed16), the copy beside the fixture's header, so its
 * user_filter.h is the one sigproc.c includes.
 *
 *   uf_harness <input.txt> <block length> <gap block>
 *
 * input.txt holds 12-bit samples, one per line. They go through
 * sigproc_block() in blocks of the given length - the first block and the
 * "gap block" with info->gap = 1 - and come out one per line, after a first
 * line "id <USER_FILTER_ID> fs <USER_FILTER_FS_HZ> desc <USER_FILTER_DESC>".
 */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "sigproc.h"

#define N_MAX 65536u

static uint16_t buf[N_MAX];

int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "usage: uf_harness <input.txt> <block length> <gap block>\n");
        return 2;
    }
    FILE *in = fopen(argv[1], "r");
    if (in == NULL) { perror(argv[1]); return 2; }
    const uint32_t blk = (uint32_t)strtoul(argv[2], NULL, 10);
    const uint32_t gap_at = (uint32_t)strtoul(argv[3], NULL, 10);
    uint32_t n = 0u;
    unsigned v;
    while (n < N_MAX && fscanf(in, "%u", &v) == 1) { buf[n++] = (uint16_t)v; }
    fclose(in);
    if (blk == 0u || n % blk != 0u) { fprintf(stderr, "n %u is no multiple of %u\n", (unsigned)n, (unsigned)blk); return 2; }

    sigproc_set_filter(SIGPROC_USER);
    for (uint32_t b = 0u; b < n / blk; b++) {
        const sigproc_info_t info = { b & 1u, b, 0u, (b == 0u || b == gap_at) ? 1u : 0u };
        sigproc_block(&buf[b * blk], blk, &info);
    }
    printf("id %08X fs %u desc %s\n", (unsigned)sigproc_user_id(), (unsigned)sigproc_user_fs_hz(),
           sigproc_user_desc());
    for (uint32_t i = 0u; i < n; i++) { printf("%u\n", (unsigned)buf[i]); }
    return 0;
}
