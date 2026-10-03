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

#include "filter_design.h"

static DSP_DATA *dsp;

void FLD_Set_Instance(DSP_DATA *dsp_instance){
    dsp = dsp_instance;
}


//////////////////////////////////////////////////////////////////////
// Konstruktion/Destruktion
//////////////////////////////////////////////////////////////////////

void FLD_Init_Filter(void) {
    int i;

    for (i = 1; i <= MAX; i++) {
        dsp->A_Coeff[i] = 1.0;
        dsp->B_Coeff[i] = 0.0;
        dsp->C_Coeff[i] = 0.0;
        dsp->D_Coeff[i] = 1.0;
        dsp->E_Coeff[i] = 0.0;
        dsp->F_Coeff[i] = 0.0;
        dsp->Av_Biquad[i] = 1;
        dsp->Aw_Biquad[i] = 0;
        dsp->Ax_Biquad[i] = 0;
        dsp->Ay_Biquad[i] = 0;
        dsp->Az_Biquad[i] = 0;
    }
    dsp->n_Order = 0;
    dsp->Sub_Filter = 16;
}



//////////////////////////////////////////////////////////////////////
// Berechnung der Butterworth-Referenztiefpass-Koeffizienten
// benutzte globale Variablen:
//	ad,as		Durchlaßdämpfung	
//  a[], b[]	Referenztiefpass-Koeffizienten
//////////////////////////////////////////////////////////////////////

int FLD_Referenz_TP_Butterworth() {
    int k;
    fld_real alpha, C;

    C = sqrt(pow(10., dsp->ad_Passband_Attenuation / 10.) - 1.);
    dsp->n_Order = (int) ceil(1. / (2. * log10(dsp->omega_s)) * log10((pow(10., dsp->as_Blocking_Attenuation / 10.) - 1) / ((pow(10., dsp->ad_Passband_Attenuation / 10.) - 1.))));

    if (dsp->n_Order < 1 || dsp->n_Order > FLD_MAX_ORDER)
        return (FLD_ERR_ORDER);

    alpha = pow(C, 1. / ((fld_real) dsp->n_Order));

    if (dsp->n_Order % 2 == 0)
        for (k = 1; k <= dsp->n_Order / 2; k++) {
            if (k > MAX) return (FLD_ERR_ORDER);
            dsp->a_reference_lp_coeff[k] = 2. * alpha * cos(((fld_real) (2. * k - 1)) / ((fld_real) (2. * dsp->n_Order)) * ((fld_real) PI));
            dsp->b_reference_lp_coeff[k] = alpha*alpha;
        } else {
        dsp->a_reference_lp_coeff[1] = alpha;
        dsp->b_reference_lp_coeff[1] = .0;
        for (k = 2; k <= (dsp->n_Order + 1) / 2; k++) {
            if (k > MAX)
                return (FLD_ERR_ORDER);
            dsp->a_reference_lp_coeff[k] = 2. * alpha * cos(((fld_real) k - 1.) / ((fld_real) dsp->n_Order) * ((fld_real) PI));
            dsp->b_reference_lp_coeff[k] = alpha*alpha;
        }
    }
    if (dsp->n_Order % 2 == 0) dsp->Sub_Filter = dsp->n_Order / 2;
    else dsp->Sub_Filter = (dsp->n_Order + 1) / 2;
    return (0);
}


///////////////////////////////////////////////////////////////////////////////////////////////////
//		Tiefpaß mit Butterworth Charakteristik
//
// Umsetzung der Referenztiefpass-Koeffizienten in die
// gewünschte Filterart.
// benutzte globale Parameter:
//		ad,as
//		a[] , b[]                       Koeffizienten des Referenztiefpasses
//		f1, f2, f3, f4                  Eckfrequenzen des Filters
//		A[], B[], C[], D[], E[], F[]    Koeffizienten der Üt-Fkt.
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_TP_Butterworth() {
    int k;
    fld_real kappa;

    dsp->omega_s = dsp->f2_Digital / dsp->f1_Digital;

    dsp->Error = FLD_Referenz_TP_Butterworth();
    if (dsp->Error != 0)
        return (dsp->Error);

    kappa = 1. / dsp->f1_Digital;
    for (k = 1; k <= dsp->Sub_Filter; k++) {
        if (k > MAX)
            return (FLD_ERR_ORDER);
        dsp->A_Coeff[k] = dsp->D_Coeff[k] = 1.;
        dsp->B_Coeff[k] = dsp->C_Coeff[k] = .0;
        dsp->E_Coeff[k] = dsp->a_reference_lp_coeff[k] * kappa;
        dsp->F_Coeff[k] = dsp->b_reference_lp_coeff[k] * kappa*kappa;
    }
    return (0);

}

///////////////////////////////////////////////////////////////////////////////////////////////////
//		Hochpaß mit Butterworth Charakteristik
//
// Umsetzung der Referenztiefpass-Koeffizienten in die
// gewünschte Filterart.
// benutzte globale Parameter:
//		ad,as
//		a[] , b[]                       Koeffizienten des Referenztiefpasses
//		f1, f2, f3, f4                  Eckfrequenzen des Filters
//		A[], B[], C[], D[], E[], F[]    Koeffizienten der Üt-Fkt.
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_HP_Butterworth() {
    int k, x;
    fld_real kappa;

    dsp->omega_s = dsp->f4_Digital / dsp->f3_Digital;

    dsp->Error = FLD_Referenz_TP_Butterworth();
    if (dsp->Error != 0)
        return (dsp->Error);

    kappa = 1. / dsp->f4_Digital;
    x = 1;
    if (dsp->n_Order % 2 != 0) {
        dsp->A_Coeff[1] = dsp->C_Coeff[1] = dsp->F_Coeff[1] = 0.0;
        dsp->D_Coeff[1] = 1.;
        dsp->E_Coeff[1] = 1. / dsp->a_reference_lp_coeff[1] * kappa;
        dsp->B_Coeff[1] = dsp->E_Coeff[1];
        x = 2;
    }
    for (k = x; k <= dsp->Sub_Filter; k++) {
        if (k > MAX)
            return (FLD_ERR_ORDER);
        dsp->A_Coeff[k] = dsp->B_Coeff[k] = .0;
        dsp->C_Coeff[k] = dsp->F_Coeff[k] = 1. / dsp->b_reference_lp_coeff[k] * kappa*kappa;
        dsp->D_Coeff[k] = 1.;
        dsp->E_Coeff[k] = dsp->a_reference_lp_coeff[k] / dsp->b_reference_lp_coeff[k] * kappa;
    }
    return (0);

}

///////////////////////////////////////////////////////////////////////////////////////////////////
//		Bandpaß mit Butterworth Charakteristik
//
// Umsetzung der Referenztiefpass-Koeffizienten in die
// gewünschte Filterart.
// benutzte globale Parameter:
//		ad,as
//		a[] , b[]                       Koeffizienten des Referenztiefpasses
//		f1, f2, f3, f4                  Eckfrequenzen des Filters
//		A[], B[], C[], D[], E[], F[]    Koeffizienten der Üt-Fkt.
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_BP_Butterworth() {
    dsp->omega_s = ((dsp->f4_Digital * dsp->f4_Digital) - (dsp->f3_Digital * dsp->f2_Digital)) / (dsp->f4_Digital * (dsp->f3_Digital - dsp->f2_Digital));

    dsp->Error = FLD_Referenz_TP_Butterworth();
    if (dsp->Error != 0)
        return (dsp->Error);

    dsp->Error = FLD_BP_Transformation(BUTT);
    if (dsp->Error != 0)
        return (dsp->Error);
    return (0);

}

///////////////////////////////////////////////////////////////////////////////////////////////////
//		Bandsperre mit Butterworth Charakteristik
//
// Umsetzung der Referenztiefpass-Koeffizienten in die
// gewünschte Filterart.
// benutzte globale Parameter:
//		ad,as
//		a[] , b[]                       Koeffizienten des Referenztiefpasses
//		f1, f2, f3, f4                  Eckfrequenzen des Filters
//		A[], B[], C[], D[], E[], F[]    Koeffizienten der Üt-Fkt.
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_BS_Butterworth() {
    dsp->omega_s = dsp->f3_Digital * (dsp->f4_Digital - dsp->f1_Digital) / (dsp->f3_Digital * dsp->f3_Digital - dsp->f4_Digital * dsp->f1_Digital);

    dsp->Error = FLD_Referenz_TP_Butterworth();
    if (dsp->Error != 0)
        return (dsp->Error);

    dsp->Error = FLD_BS_Transformation(BUTT);
    if (dsp->Error != 0)
        return (dsp->Error);
    return (0);

}

///////////////////////////////////////////////////////////////////////////////////////////////////
// Berechnung der Tschebyscheff-Referenztiefpass-Koeffizienten
// benutzte globale Variablen:
//     ad,as,dsp->omega_s
//     a[], b[]                    Referenztiefpass-Koeffizienten
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_Referenz_TP_Tschebycheff() {
    register int k;
    register fld_real alpha, gamma, delta, x, y, C;

    C = sqrt(pow(10., (fld_real) dsp->ad_Passband_Attenuation / 10.) - 1.);
    dsp->n_Order = (int) ceil(arcosh(sqrt((pow(10., dsp->as_Blocking_Attenuation / 10.) - 1.) / (pow(10., dsp->ad_Passband_Attenuation / 10.) - 1.))) / arcosh(dsp->omega_s));

    if (dsp->n_Order < 1 || dsp->n_Order > FLD_MAX_ORDER)
        return (FLD_ERR_ORDER);

    alpha = 1. / (fld_real) dsp->n_Order * arsinh(1. / sqrt(pow(10., (dsp->ad_Passband_Attenuation / 10.)) - 1.));
    gamma = sinh(alpha);
    delta = cosh(alpha);

    if (dsp->n_Order % 2 == 0)
        for (k = 1; k <= dsp->n_Order / 2; k++) {
            if (k > MAX)
                return (FLD_ERR_ORDER);
            x = cos((2. * (fld_real) k - 1.)*(fld_real) PI / 2. / (fld_real) dsp->n_Order);
            dsp->b_reference_lp_coeff[k] = 1. / (delta * delta - x * x);
            dsp->a_reference_lp_coeff[k] = 2. * dsp->b_reference_lp_coeff[k] * gamma*x;
        }
    if (dsp->n_Order % 2 != 0) {
        dsp->a_reference_lp_coeff[1] = 1. / gamma;
        dsp->b_reference_lp_coeff[1] = .0;
        for (k = 2; k <= (dsp->n_Order + 1) / 2; k++) {
            if (k > MAX)
                return (FLD_ERR_ORDER);
            y = cos(((fld_real) k - 1.) * PI / (fld_real) dsp->n_Order);
            dsp->b_reference_lp_coeff[k] = 1. / (delta * delta - y * y);
            dsp->a_reference_lp_coeff[k] = 2. * dsp->b_reference_lp_coeff[k] * gamma*y;
        }
    }
    if (dsp->n_Order % 2 == 0) dsp->Sub_Filter = dsp->n_Order / 2;
    else dsp->Sub_Filter = (dsp->n_Order + 1) / 2;
    return (0);

}

///////////////////////////////////////////////////////////////////////////////////////////////////
//		Tiefpaß mit Tschebyscheff Charakteristik
//
// Umsetzung der Referenztiefpass-Koeffizienten in die
// gewünschte Filterart.
// benutzte globale Parameter:
//		ad,as
//		a[] , b[]                       Koeffizienten des Referenztiefpasses
//		f1, f2, f3, f4                  Eckfrequenzen des Filters
//		A[], B[], C[], D[], E[], F[]    Koeffizienten der Üt-Fkt.
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_TP_Tschebycheff() {
    int k;
    fld_real kappa = 1. / dsp->f1_Digital, konst;
    dsp->omega_s = dsp->f2_Digital / dsp->f1_Digital;

    dsp->Error = FLD_Referenz_TP_Tschebycheff();
    if (dsp->Error != 0)
        return (dsp->Error);


    for (k = 1; k <= dsp->Sub_Filter; k++) {
        if (k > MAX)
            return (FLD_ERR_ORDER);
        dsp->A_Coeff[k] = dsp->D_Coeff[k] = 1.;
        dsp->B_Coeff[k] = dsp->C_Coeff[k] = .0;
        dsp->E_Coeff[k] = dsp->a_reference_lp_coeff[k] * kappa;
        dsp->F_Coeff[k] = dsp->b_reference_lp_coeff[k] * kappa*kappa;
    }
    if (dsp->n_Order % 2 == 0) {
        konst = pow(10., (-dsp->ad_Passband_Attenuation / 20.));
        dsp->A_Coeff[1] *= konst;
    }
    return (0);

}

///////////////////////////////////////////////////////////////////////////////////////////////////
//		Hochpaß mit Tschebyscheff Charakteristik
//
// Umsetzung der Referenztiefpass-Koeffizienten in die
// gewünschte Filterart.
// benutzte globale Parameter:
//		ad,as
//		a[] , b[]                       Koeffizienten des Referenztiefpasses
//		f1, f2, f3, f4                  Eckfrequenzen des Filters
//		A[], B[], C[], D[], E[], F[]    Koeffizienten der Üt-Fkt.
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_HP_Tschebycheff() {
    int k, x;
    fld_real kappa, konst;

    dsp->omega_s = dsp->f4_Digital / dsp->f3_Digital;

    dsp->Error = FLD_Referenz_TP_Tschebycheff();
    if (dsp->Error != 0)
        return (dsp->Error);

    kappa = 1. / dsp->f4_Digital;
    x = 1;
    if (dsp->n_Order % 2 != 0) {
        dsp->A_Coeff[1] = dsp->C_Coeff[1] = dsp->F_Coeff[1] = 0.0;
        dsp->D_Coeff[1] = 1.0;
        dsp->E_Coeff[1] = 1. / dsp->a_reference_lp_coeff[1] * kappa;
        dsp->B_Coeff[1] = dsp->E_Coeff[1];
        x = 2;
    }
    for (k = x; k <= dsp->Sub_Filter; k++) {
        if (k > MAX)
            return (FLD_ERR_ORDER);
        dsp->A_Coeff[k] = dsp->B_Coeff[k] = .0;
        dsp->C_Coeff[k] = dsp->F_Coeff[k] = 1. / dsp->b_reference_lp_coeff[k] * kappa*kappa;
        dsp->D_Coeff[k] = 1.0;
        dsp->E_Coeff[k] = dsp->a_reference_lp_coeff[k] / dsp->b_reference_lp_coeff[k] * kappa;
    }
    if (dsp->n_Order % 2 == 0) {
        konst = pow(10., (-dsp->ad_Passband_Attenuation / 20.));
        dsp->C_Coeff[1] *= konst;
    }
    return (0);

}

///////////////////////////////////////////////////////////////////////////////////////////////////
//		Bandpaß mit Tschebyscheff Charakteristik
//
// Umsetzung der Referenztiefpass-Koeffizienten in die
// gewünschte Filterart.
// benutzte globale Parameter:
//		ad,as
//		a[] , b[]                       Koeffizienten des Referenztiefpasses
//		f1, f2, f3, f4                  Eckfrequenzen des Filters
//		A[], B[], C[], D[], E[], F[]    Koeffizienten der Üt-Fkt.
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_BP_Tschebycheff() {
    fld_real konst;

    dsp->omega_s = ((dsp->f4_Digital * dsp->f4_Digital) - (dsp->f3_Digital * dsp->f2_Digital)) / (dsp->f4_Digital * (dsp->f3_Digital - dsp->f2_Digital));

    dsp->Error = FLD_Referenz_TP_Tschebycheff();
    if (dsp->Error != 0)
        return (dsp->Error);

    dsp->Error = FLD_BP_Transformation(TSCHE);
    if (dsp->Error != 0)
        return (dsp->Error);
    if (dsp->n_Order % 2 == 0) {
        konst = pow(10., (-dsp->ad_Passband_Attenuation / 20.));
        dsp->B_Coeff[1] *= konst;
    }
    return (0);

}

///////////////////////////////////////////////////////////////////////////////////////////////////
//		Bandsperre mit Tschebyscheff Charakteristik
//
// Umsetzung der Referenztiefpass-Koeffizienten in die
// gewünschte Filterart.
// benutzte globale Parameter:
//		ad,as
//		a[] , b[]                       Koeffizienten des Referenztiefpasses
//		f1, f2, f3, f4                  Eckfrequenzen des Filters
//		A[], B[], C[], D[], E[], F[]    Koeffizienten der Üt-Fkt.
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_BS_Tschebycheff() {
    fld_real konst;

    dsp->omega_s = dsp->f3_Digital * (dsp->f4_Digital - dsp->f1_Digital) / (dsp->f3_Digital * dsp->f3_Digital - dsp->f4_Digital * dsp->f1_Digital);

    dsp->Error = FLD_Referenz_TP_Tschebycheff();
    if (dsp->Error != 0)
        return (dsp->Error);

    dsp->Error = FLD_BS_Transformation(TSCHE);
    if (dsp->Error != 0)
        return (dsp->Error);
    if (dsp->n_Order % 2 == 0) {
        konst = pow(10., (-dsp->ad_Passband_Attenuation / 20.));
        dsp->A_Coeff[1] *= konst;
        dsp->C_Coeff[1] *= konst;
    }
    return (0);

}


///////////////////////////////////////////////////////////////////////////////////////////////////
// Berechnung der Cauer-Referenztiefpass-Koeffizienten
// benutzte globale Variablen:
//  ad                          Durchlaßdämpfung
//  as                          Sperrdämpfung
//  dsp->omega_s                     normierte Sperrfrequenz
//                              des Referenztiefpasses
//  dsp->omega_d[]                   normierte Dämpfungspole
//  r[], s[]                    Real-und Imaginärteil der komplexen
//                              Nullstellen des Referenztiefpasses
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_Referenz_TP_Cauer() {

    fld_real u, w, a0, m, sz, x, y, z, temp1, temp2;
    fld_real v, eas, eap;
    fld_real omega_un[20], d[20], e[30];
    fld_real b[20], c[20], omega[20], feld[20];
    fld_real dbn;
    int i, k, m_halb, index, j, max;

    dbn = log(10.) / 10.; // Umrechnungsfaktor dB in Neper
    for (i = 0; i <= 19; i++) // Felder initialisieren
        b[i] = c[i] = d[i] = e[i] = dsp->r_real_part_complex_zeros[i] = dsp->s_imaginary_part_complex_zeros[i] = omega[i] = omega_un[i] = dsp->omega_d[i] = 1.;

    u = FLD_u_db(dsp->as_Blocking_Attenuation, dsp->ad_Passband_Attenuation);
    temp1 = FLD_gammaM(dsp->omega_s, 1.);
    temp2 = FLD_gammaM(dsp->omega_s + 1., dsp->omega_s - 1.);
    m = PI / u * temp1 / temp2;
    dsp->n_Order = (int) ceil(m - 1e-9); /* was ceil(m + .5): one order too high */

    if (dsp->n_Order < 1 || dsp->n_Order > FLD_MAX_ORDER)
        return (FLD_ERR_ORDER);

    m = (fld_real) dsp->n_Order / 2.; // Halber Grad der Funktion
    if (dsp->n_Order % 2 != 0) { // Ungerade Funktion
        m_halb = dsp->n_Order / 2 + 1; // Laufindex int(n/2)+1
    } else { // Gerade Funktion
        m_halb = dsp->n_Order / 2; // Laufindex int(n/2)
    }

    // Berechnung von u über Omega_s und dem Filtergrad 
    u = FLD_u_frq(dsp->omega_s, dsp->n_Order);

    // Berechnung der charakteristischen Funktion. In e[i] sind alle nicht-
    // normierten Extremstellen im Durchlaßbereich enthalten.

    e[0] = FLD_Sn(2. * m*u, u / 2. * (2. * m)); // Ende des Durchlassbereiches
    for (i = 1; i <= dsp->n_Order; i++)
        e[i] = FLD_Sn((fld_real) dsp->n_Order * u, u / 2. * (fld_real) (dsp->n_Order - i)); // Weitere Extremstellen

    index = m_halb;
    for (i = 1; i <= dsp->n_Order; i++) // Nullstellen bei 1,3,5 usw
    { // normieren.
        if (i % 2 != 0) // In e[0] Ende des
        { // Durchlaábereiches
            omega[index] = e[i] / e[0];
            index--;
        }
    }
    k = 1;
    for (i = 1; i <= m_halb; i++) {
        if (omega[i] != 0) { // Polstellen berechnen
            omega_un[k] = 1 / omega[i] * dsp->omega_s;
            k++;
        }
    }

    // Dämpfungspole nach Saal umsortieren
    // sortierte Werte sind im Feld Omega_d[] enthalten

    k = dsp->n_Order / 2;
    j = 1;
    for (i = 1; i <= k; i += 2) {
        dsp->omega_d[j] = omega_un[i]; // Polstellen
        j++; // nach Saal umsotieren
    }
    if (i > k + 1)
        k--;
    for (i = k; i > 1; i -= 2) {
        dsp->omega_d[j] = omega_un[i]; // Polstellen
        j++; // nach Saal umsotieren
    }

    // Berechnung der Nullstellen von H nach Amstutz

    eas = exp(dbn * dsp->as_Blocking_Attenuation) - 1.; // Berechnung von a0 nach
    eap = exp(dbn * dsp->ad_Passband_Attenuation) - 1.; // Gl. 4.32, 4.33, und 4.34
    v = sqrt(eas / eap) + sqrt(eas / eap - 1);
    u = PI * PI / (2. * log(v + v));
    v = v / (sqrt(eas) + sqrt(eas + 1));
    w = u * log(v + sqrt(v * v + 1)) / PI;

    w = a0 = tan(w);
    w = w*w;
    y = exp(-2. * u);
    z = y;
    for (i = 1; i < 1000; i++) {
        if (i % dsp->n_Order != 0) {
            z = z*y;
        } else {
            x = pow(((1 - z) / (1 + z)), 2.); // tanh^2
            a0 = a0 * (w + x) / (1. + w * x);
            if (z < .1E-29)
                goto end; // Keine Änderung von z ?
            z = z*y;
        }
    }
end:
    // Komplexe Nullstellen von H berechnen Gl. 4.22

    sz = sqrt(a0 * a0 + 1. / a0 / a0 + e[0] * e[0] + 1. / e[0] / e[0]); // Zähler von sj
    for (i = 1; 2 * i - 1 < dsp->n_Order; i++) {
        y = a0 * e[2 * i - 1];
        y = y + 1. / y; // Nenner von sj und rj
        z = e[0] * e[2 * i - 1];
        dsp->r_real_part_complex_zeros[i] = e[dsp->n_Order + 1 - 2 * i]*(1. / z - z) / y / e[0]; // e[n+1-2*i] = Maxima bei
        dsp->s_imaginary_part_complex_zeros[i] = sz / y / e[0]; // ungeraden Fkt. !
    }
    if (dsp->n_Order % 2 != 0) {
        dsp->r_real_part_complex_zeros[i] = a0 / e[0]; // Reale Nullstelle der ungeraden
        dsp->s_imaginary_part_complex_zeros[i] = 0.; // Funktion
    }
    max = m_halb;
    for (i = 1; (max >= 1); i++, --max)
        feld[i] = dsp->r_real_part_complex_zeros[max];
    max = m_halb;
    for (i = 1; i <= max; ++i)
        dsp->r_real_part_complex_zeros[i] = feld[i];

    max = m_halb;
    for (i = 1; (max >= 1); i++, --max)
        feld[i] = dsp->s_imaginary_part_complex_zeros[max];
    max = m_halb;
    for (i = 1; i <= max; ++i)
        dsp->s_imaginary_part_complex_zeros[i] = feld[i];
    if (dsp->n_Order % 2 == 0) dsp->Sub_Filter = dsp->n_Order / 2;
    else dsp->Sub_Filter = (dsp->n_Order + 1) / 2;
    return (0);
}


///////////////////////////////////////////////////////////////////////////////////////////////////
//        Berechnung der Konstanten des Cauerfilters
///////////////////////////////////////////////////////////////////////////////////////////////////

void FLD_Get_Constants() {
    int k;
    fld_real h, Z, N;
    Z = N = 1.;
    if (dsp->n_Order % 2 != 0) {
        for (k = 1; k <= (dsp->n_Order - 1) / 2; k++)
            Z *= dsp->omega_d[k] * dsp->omega_d[k];
        for (k = 2; k <= (dsp->n_Order + 1) / 2; k++)
            N *= (dsp->r_real_part_complex_zeros[k] * dsp->r_real_part_complex_zeros[k] + dsp->s_imaginary_part_complex_zeros[k] * dsp->s_imaginary_part_complex_zeros[k]);
        dsp->cauer_const = Z / N / dsp->r_real_part_complex_zeros[1];
    } else {
        for (k = 1; k <= dsp->n_Order / 2; k++) {
            Z *= dsp->omega_d[k] * dsp->omega_d[k];
            N *= (dsp->r_real_part_complex_zeros[k] * dsp->r_real_part_complex_zeros[k] + dsp->s_imaginary_part_complex_zeros[k] * dsp->s_imaginary_part_complex_zeros[k]);
        }
        h = pow(10.0, dsp->ad_Passband_Attenuation / 20.);
        dsp->cauer_const = Z / N*h;
    }
}

///////////////////////////////////////////////////////////////////////////////////////////////////
//		Tiefpaß mit Cauer Charakteristik
//
// Umsetzung der Referenztiefpass-Koeffizienten in die
// gewünschte Filterart.
// benutzte globale Variablen:
//    r[], s[]                        Real-und Imaginärteil der
//                                    komplexen Nullstellen
//    f1, f2, f3 ,f4                  Eckfrequenzen
//    A[], B[], C[], D[], E[], F[]    Koeffizienten der Üt-Fkt.
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_TP_Cauer() {
    fld_real hilf;
    fld_real kappa, gamma;
    int i, m;

    dsp->omega_s = dsp->f2_Digital / dsp->f1_Digital;

    dsp->Error = FLD_Referenz_TP_Cauer();
    if (dsp->Error != 0)
        return (dsp->Error);

    FLD_Get_Constants();
    m = 1;
    hilf = 1.;
    kappa = 1. / dsp->f1_Digital;
    m = 1;
    if (dsp->n_Order % 2 != 0) { // ungerader Fall 
        dsp->A_Coeff[1] = 1.0;
        dsp->B_Coeff[1] = dsp->C_Coeff[1] = dsp->F_Coeff[1] = 0.0;
        dsp->D_Coeff[1] = 1.0;
        dsp->E_Coeff[1] = 1. / dsp->r_real_part_complex_zeros[1] * kappa;
        m = 2;
    }

    for (i = m; i <= (dsp->Sub_Filter - 1); i++)
        dsp->constant_values[i] = 1. / (2. * dsp->r_real_part_complex_zeros[i] * dsp->s_imaginary_part_complex_zeros[i]);
    dsp->constant_values[1] = 1. / dsp->r_real_part_complex_zeros[1];
    for (i = 1; i <= (dsp->Sub_Filter - 1); i++)
        hilf *= dsp->constant_values[i];

    dsp->constant_values[dsp->Sub_Filter] = dsp->cauer_const / hilf;
    for (i = m; i <= dsp->Sub_Filter; i++) {
        gamma = dsp->r_real_part_complex_zeros[i] * dsp->r_real_part_complex_zeros[i] + dsp->s_imaginary_part_complex_zeros[i] * dsp->s_imaginary_part_complex_zeros[i];
        if (dsp->n_Order % 2 != 0)
            dsp->A_Coeff[i] = dsp->omega_d[i - 1] * dsp->omega_d[i - 1] / dsp->constant_values[i] / gamma;
        else
            dsp->A_Coeff[i] = dsp->omega_d[i] * dsp->omega_d[i] / dsp->constant_values[i] / gamma;
        dsp->B_Coeff[i] = 0.0;
        dsp->C_Coeff[i] = 1. / (dsp->constant_values[i] * gamma) * kappa*kappa;
        dsp->D_Coeff[i] = 1.0;
        dsp->E_Coeff[i] = 2. * dsp->r_real_part_complex_zeros[i] / gamma*kappa;
        dsp->F_Coeff[i] = 1. / gamma * kappa*kappa;
    }
    return (0);
}

///////////////////////////////////////////////////////////////////////////////////////////////////
//		Hochpaß mit Cauer Charakteristik
//
// Umsetzung der Referenztiefpass-Koeffizienten in die
// gewünschte Filterart.
// benutzte globale Variablen:
//    r[], s[]                        Real-und Imaginärteil der
//                                    komplexen Nullstellen
//    f1, f2, f3 ,f4                  Eckfrequenzen
//    A[], B[], C[], D[], E[], F[]    Koeffizienten der Üt-Fkt.
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_HP_Cauer() {
    fld_real hilf, konst[20];
    fld_real kappa, gamma;
    int i, m;

    dsp->omega_s = dsp->f4_Digital / dsp->f3_Digital;

    dsp->Error = FLD_Referenz_TP_Cauer();
    if (dsp->Error != 0)
        return (dsp->Error);

    FLD_Get_Constants();
    m = 1;
    hilf = 1.;
    kappa = 1. / dsp->f4_Digital;
    m = 1;

    if (dsp->n_Order % 2 != 0) { // ungerader Fall
        dsp->A_Coeff[1] = dsp->C_Coeff[1] = dsp->F_Coeff[1] = 0.0;
        dsp->B_Coeff[1] = dsp->E_Coeff[1] = dsp->r_real_part_complex_zeros[1] * kappa;
        dsp->D_Coeff[1] = 1.0;
        m = 2;
    }
    for (i = m; i <= (dsp->Sub_Filter - 1); i++)
        konst[i] = 1. / (2. * dsp->r_real_part_complex_zeros[i] * dsp->s_imaginary_part_complex_zeros[i]);
    konst[1] = 1. / dsp->r_real_part_complex_zeros[1];
    for (i = 1; i <= (dsp->Sub_Filter - 1); i++)
        hilf *= konst[i];

    konst[dsp->Sub_Filter] = dsp->cauer_const / hilf;
    for (i = m; i <= dsp->Sub_Filter; i++) {
        gamma = dsp->r_real_part_complex_zeros[i] * dsp->r_real_part_complex_zeros[i] + dsp->s_imaginary_part_complex_zeros[i] * dsp->s_imaginary_part_complex_zeros[i];
        dsp->A_Coeff[i] = 1. / konst[i];
        dsp->B_Coeff[i] = 0.0;
        if (dsp->n_Order % 2 != 0)
            dsp->C_Coeff[i] = dsp->omega_d[i - 1] * dsp->omega_d[i - 1] / konst[i] * kappa * kappa;
        else
            dsp->C_Coeff[i] = dsp->omega_d[i] * dsp->omega_d[i] / konst[i] * kappa*kappa;
        dsp->D_Coeff[i] = 1.0;
        dsp->E_Coeff[i] = 2. * dsp->r_real_part_complex_zeros[i] * kappa;
        dsp->F_Coeff[i] = gamma * kappa*kappa;
    }
    return (0);
}

///////////////////////////////////////////////////////////////////////////////////////////////////
//		Bandpaß mit Cauer Charakteristik
//
// Umsetzung der Referenztiefpass-Koeffizienten in die
// gewünschte Filterart.
// benutzte globale Variablen:
//    r[], s[]                        Real-und Imaginärteil der
//                                    komplexen Nullstellen
//    f1, f2, f3 ,f4                  Eckfrequenzen
//    A[], B[], C[], D[], E[], F[]    Koeffizienten der Üt-Fkt.
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_BP_Cauer() {
    int i;
    fld_real hilf;

    dsp->omega_s = (dsp->f4_Digital * dsp->f4_Digital - dsp->f2_Digital * dsp->f3_Digital) / dsp->f4_Digital / (dsp->f3_Digital - dsp->f2_Digital);

    dsp->Error = FLD_Referenz_TP_Cauer();
    if (dsp->Error != 0)
        return (dsp->Error);

    FLD_Get_Constants();
    hilf = 1.;
    for (i = 1; i <= (dsp->Sub_Filter - 1); i++)
        //  konst[i]=1./(2.*r[i]*s[i])
        dsp->constant_values[i] = 1. / dsp->r_real_part_complex_zeros[i] / 2.;
    for (i = 1; i <= (dsp->Sub_Filter - 1); i++)
        hilf *= dsp->constant_values[i];
    dsp->constant_values[dsp->Sub_Filter] = dsp->cauer_const / hilf;
    dsp->Error = FLD_BP_Transformation(CAU);
    if (dsp->Error != 0)
        return (dsp->Error);
    return (0);

}

///////////////////////////////////////////////////////////////////////////////////////////////////
//		Bandsperre mit Cauer Charakteristik
//
// Umsetzung der Referenztiefpass-Koeffizienten in die
// gewünschte Filterart.
// benutzte globale Variablen:
//    r[], s[]                        Real-und Imaginärteil der
//                                    komplexen Nullstellen
//    f1, f2, f3 ,f4                  Eckfrequenzen
//    A[], B[], C[], D[], E[], F[]    Koeffizienten der Üt-Fkt.
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_BS_Cauer() {
    int i, m;
    fld_real hilf;

    dsp->omega_s = dsp->f3_Digital * (dsp->f4_Digital - dsp->f1_Digital) / (dsp->f3_Digital * dsp->f3_Digital - dsp->f4_Digital * dsp->f1_Digital);

    dsp->Error = FLD_Referenz_TP_Cauer();
    if (dsp->Error != 0)
        return (dsp->Error);

    FLD_Get_Constants();
    hilf = 1.;
    if (dsp->n_Order % 2 != 0) {
        m = 2;
        dsp->constant_values[1] = 1. / dsp->r_real_part_complex_zeros[1];
    } else {
        m = 1;
    }
    for (i = m; i <= (dsp->Sub_Filter - 1); i++)
        dsp->constant_values[i] = 1. / (2. * dsp->r_real_part_complex_zeros[i] * dsp->s_imaginary_part_complex_zeros[i]);
    for (i = 1; i <= (dsp->Sub_Filter - 1); i++)
        hilf *= dsp->constant_values[i];
    dsp->constant_values[dsp->Sub_Filter] = dsp->cauer_const / hilf;
    dsp->Error = FLD_BS_Transformation(CAU);
    if (dsp->Error != 0)
        return (dsp->Error);
    return (0);

}


///////////////////////////////////////////////////////////////////////////////////////////////////
//			Bandpaß Transformation 
//  für alle Butterworth, Tschebycheff und Cauer Charakteristika					
//
//	Übergeben wird ein Makro: BUTT, TSCHE oder CAU
//	Verändert werden hier die Arrays der Analog Koeffizienten:
//		A[],B[],C[],D[],E[],F[]
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_BP_Transformation(int filt_char) {
    int k, p, x, lauf;
    fld_real kappa, alpha, beta, delta, d, f;
    fld_real rep1, rep2, imp1, imp2, rea, imb;

    p = 1;
    x = 1;
    delta = sqrt(dsp->f2_Digital * dsp->f3_Digital);
    kappa = delta / (dsp->f3_Digital - dsp->f2_Digital);
    dsp->Sub_Filter = dsp->n_Order;
    if (dsp->Sub_Filter % 2 != 0)
        lauf = (dsp->Sub_Filter + 1) / 2;
    else
        lauf = dsp->Sub_Filter / 2;

    if (dsp->n_Order % 2 != 0) {
        if (filt_char == CAU) {
            dsp->A_Coeff[1] = dsp->C_Coeff[1] = 0.0;
            dsp->D_Coeff[1] = 1.0;
            dsp->B_Coeff[1] = 1. / kappa / dsp->constant_values[1] / delta;
            dsp->E_Coeff[1] = dsp->r_real_part_complex_zeros[1] / kappa / delta;
            dsp->F_Coeff[1] = 1. / delta / delta;
        } else {
            dsp->A_Coeff[1] = dsp->C_Coeff[1] = .0;
            dsp->D_Coeff[1] = 1.;
            dsp->F_Coeff[1] = 1. / delta / delta;
            dsp->B_Coeff[1] = 1. / dsp->a_reference_lp_coeff[1] / kappa / delta;
            dsp->E_Coeff[1] = dsp->B_Coeff[1];
        }
        p = 2;
        x = 2;
    } // End of if
    for (k = p; k <= lauf; k++) {
        if (x + 1 > MAX)
            return (FLD_ERR_ORDER);
        if (filt_char == CAU) {
            alpha = -dsp->r_real_part_complex_zeros[k] / 2. / kappa;
            beta = dsp->s_imaginary_part_complex_zeros[k] / 2. / kappa;
        } else {
            alpha = -dsp->a_reference_lp_coeff[k] / (4. * kappa * dsp->b_reference_lp_coeff[k]);
            beta = sqrt(1. / 4. / kappa / kappa / dsp->b_reference_lp_coeff[k] - alpha * alpha);
        }
        rea = alpha * alpha - beta * beta - 1.;
        imb = 2. * alpha*beta;
        rep1 = alpha + sqrt(rea / 2. + sqrt((rea * rea + imb * imb) / 4.));
        imp1 = beta + imb / 2. / (rep1 - alpha);
        rep2 = alpha - sqrt(rea / 2. + sqrt((rea * rea + imb * imb) / 4.));
        imp2 = beta - imb / 2. / (rep1 - alpha);
        dsp->F_Coeff[x + 1] = 1. / (rep2 * rep2 + imp2 * imp2) / (delta * delta);
        dsp->E_Coeff[x + 1] = -2. * rep2 * dsp->F_Coeff[x + 1] * delta;
        dsp->F_Coeff[x] = 1. / (rep1 * rep1 + imp1 * imp1) / (delta * delta);
        dsp->E_Coeff[x] = -2. * rep1 * dsp->F_Coeff[x] * delta;
        if (filt_char == CAU) {
            f = 1. / dsp->constant_values[k];

            if (dsp->n_Order % 2 != 0)
                d = (2. * kappa * kappa + dsp->omega_d[k - 1] * dsp->omega_d[k - 1])
                / kappa / kappa / 2.;
            else
                d = (2. * kappa * kappa + dsp->omega_d[k] * dsp->omega_d[k]) / kappa / kappa / 2.;
            dsp->A_Coeff[x] = (d - sqrt(d * d - 1.)) * sqrt(f);
            dsp->A_Coeff[x + 1] = (d + sqrt(d * d - 1.)) * sqrt(f);
            dsp->C_Coeff[x] = dsp->C_Coeff[x + 1] = 1. / delta / delta * sqrt(f);
            dsp->B_Coeff[x] = dsp->B_Coeff[x + 1] = 0.0;
            dsp->D_Coeff[x] = dsp->D_Coeff[x + 1] = 1.0;
        } else {
            dsp->A_Coeff[x] = dsp->C_Coeff[x] = dsp->A_Coeff[x + 1] = dsp->C_Coeff[x + 1] = 0.0;
            dsp->D_Coeff[x] = dsp->D_Coeff[x + 1] = 1.0;
            dsp->B_Coeff[x + 1] = 1.0 / delta / sqrt(dsp->b_reference_lp_coeff[k] * kappa * kappa);
            dsp->B_Coeff[x] = 1.0 / delta / sqrt(dsp->b_reference_lp_coeff[k] * kappa * kappa);
        }
        x += 2;
    } // for
    return (0);

}

///////////////////////////////////////////////////////////////////////////////////////////////////
//			Bandsperr Transformation 
//  für alle Butterworth, Tschebycheff und Cauer Charakteristika					
//
//	Übergeben wird ein Makro: BUTT, TSCHE oder CAU
//	Verändert werden hier die Arrays der Analog Koeffizienten:
//		A[],B[],C[],D[],E[],F[]
///////////////////////////////////////////////////////////////////////////////////////////////////

int FLD_BS_Transformation(int filt_char) {
    int k, p, x, lauf;
    fld_real alpha, beta, kappa, delta, gamma,
            rep1, rep2, imp1, imp2,
            rea, imb, d, f;

    kappa = (sqrt(dsp->f1_Digital * dsp->f4_Digital) / (dsp->f4_Digital - dsp->f1_Digital));
    delta = sqrt(dsp->f1_Digital * dsp->f4_Digital);
    dsp->Sub_Filter = dsp->n_Order;
    if (dsp->Sub_Filter % 2 != 0)
        lauf = (dsp->Sub_Filter + 1) / 2;
    else
        lauf = dsp->Sub_Filter / 2;
    x = 1;
    p = 1;
    if (dsp->n_Order % 2 != 0) {
        if (filt_char == CAU) {
            dsp->A_Coeff[1] = 1. / dsp->r_real_part_complex_zeros[1] / dsp->constant_values[1];
            dsp->C_Coeff[1] = 1. / dsp->r_real_part_complex_zeros[1] / dsp->constant_values[1] / delta / delta;
            dsp->D_Coeff[1] = 1.0;
            dsp->B_Coeff[1] = 0.0;
            dsp->E_Coeff[1] = 1. / dsp->r_real_part_complex_zeros[1] / kappa / delta;
            dsp->F_Coeff[1] = 1. / (delta * delta);
        } else {
            dsp->A_Coeff[1] = dsp->D_Coeff[1] = 1.0;
            dsp->B_Coeff[1] = .0;
            dsp->E_Coeff[1] = dsp->a_reference_lp_coeff[1] / kappa / delta;
            dsp->C_Coeff[1] = dsp->F_Coeff[1] = 1. / (delta * delta);
        }
        p = 2;
        x = 2;
    } // if

    for (k = p; k <= lauf; k++) {
        if (x + 1 > MAX)
            return (FLD_ERR_ORDER);
        if (filt_char == CAU) {
            gamma = dsp->r_real_part_complex_zeros[k] * dsp->r_real_part_complex_zeros[k] + dsp->s_imaginary_part_complex_zeros[k] * dsp->s_imaginary_part_complex_zeros[k];
            alpha = -dsp->r_real_part_complex_zeros[k] / 2. / gamma / kappa;
            beta = dsp->s_imaginary_part_complex_zeros[k] / 2. / gamma / kappa;
        } else {
            alpha = -dsp->a_reference_lp_coeff[k] / 4. / kappa;
            beta = sqrt(dsp->b_reference_lp_coeff[k] / 4. / kappa / kappa - alpha * alpha);
        }
        rea = alpha * alpha - beta * beta - 1.;
        imb = 2. * alpha*beta;
        rep1 = alpha + sqrt(rea / 2. + sqrt((rea * rea + imb * imb) / 4.));
        imp1 = beta + imb / 2. / sqrt(rea / 2. + sqrt(rea * rea / 4. + imb * imb / 4.));
        rep2 = alpha - sqrt(rea / 2. + sqrt((rea * rea + imb * imb) / 4.));
        imp2 = beta - imb / 2. / sqrt(rea / 2. + sqrt(rea * rea / 4. + imb * imb / 4.));

        dsp->E_Coeff[x] = -2. * rep1 / (rep1 * rep1 + imp1 * imp1) / delta;
        dsp->F_Coeff[x] = 1. / (rep1 * rep1 + imp1 * imp1) / (delta * delta);
        dsp->E_Coeff[x + 1] = -2. * rep2 / (rep2 * rep2 + imp2 * imp2) / delta;
        dsp->F_Coeff[x + 1] = 1. / (rep2 * rep2 + imp2 * imp2) / (delta * delta);
        if (filt_char == CAU) {
            if (dsp->n_Order % 2 != 0) {
                d = (1. + 2. * dsp->omega_d[k - 1] * dsp->omega_d[k - 1] * kappa * kappa) /
                        (2. * dsp->omega_d[k - 1] * dsp->omega_d[k - 1] * kappa * kappa);
                f = dsp->omega_d[k - 1] / sqrt(gamma * dsp->constant_values[k]);
            } else {
                d = 1. / (2. * dsp->omega_d[k] * dsp->omega_d[k] * kappa * kappa) + 1.;
                f = dsp->omega_d[k] / sqrt(gamma * dsp->constant_values[k]);
            }
            dsp->A_Coeff[x] = (d - sqrt(d * d - 1.)) * f;
            dsp->A_Coeff[x + 1] = (d + sqrt(d * d - 1.)) * f;
            dsp->B_Coeff[x] = dsp->B_Coeff[x + 1] = 0.0;
            dsp->C_Coeff[x] = f / (delta * delta);
            dsp->C_Coeff[x + 1] = f / (delta * delta);
            dsp->D_Coeff[x] = dsp->D_Coeff[x + 1] = 1.0;
        } else {
            dsp->A_Coeff[x] = dsp->A_Coeff[x + 1] = dsp->D_Coeff[x] = dsp->D_Coeff[x + 1] = 1.;
            dsp->C_Coeff[x] = dsp->C_Coeff[x + 1] = 1. / (delta * delta);
            dsp->B_Coeff[x] = dsp->B_Coeff[x + 1] = .0;
        }
        x += 2;
    }
    return (0);

}

///////////////////////////////////////////////////////////////////////////////////////////////////
//                                                                         
//   Sn-Fkt. Taylor-Reihenentwicklung der Jakobischen elliptischen         
//           Funktionen                                                    
//                                                                         
//   Eingabeparameter:                                                     
//   ----------------                                                      
//   u, z        Hilfsgröße, priodische Größe abhängig vom Grad der        
//               Funktion.                                                 
//                                                                         
//   Ausgabeparameter:                                                     
//   -----------------                                                     
//   Sn          Funktionswert der Taylor-Reihenentwicklung                
//                                                                         
///////////////////////////////////////////////////////////////////////////////////////////////////

fld_real FLD_Sn(fld_real u, fld_real z) {
    int i; // Zählvariable
    fld_real ax, rueckgabe; // Hilfsvariablen
    ax = rueckgabe = 1.; // Startwerte setzen
    for (i = 1; i <= 1000; i++) {
        ax = ax * tanh((fld_real) i * u - z) * tanh((fld_real) i * u + z);
        if (ax == rueckgabe) {
            rueckgabe = rueckgabe * tanh(z);
            return (rueckgabe);
        }
        rueckgabe = ax;
    }
    return (0); // Fehler aufgetreten
}

///////////////////////////////////////////////////////////////////////////////////////////////////
//   FUNKTION NICHT ANALYSIERT
///////////////////////////////////////////////////////////////////////////////////////////////////

fld_real FLD_u_db(fld_real as, fld_real ad) {
    fld_real u, dbn;

    dbn = DB;
    u = PI * PI / log(16. * (exp(dbn * as) - 1.) / (exp(dbn * ad) - 1.));
    return (u);

}


///////////////////////////////////////////////////////////////////////////////////////////////////
//                                                                         
//   u_frq bestimmt die  Hilfsgröße u aus den Frequenzen êp (1) und ês,    
//         nach Amstutz [4.29].                                            
//                                                                         
//   Eingabeparameter:                                                     
//   ----------------                                                      
//   ês, n       Beginn des Sperrbereiches, Filtergrad                     
//                                                                         
//                                                                         
//   Ausgabeparameter:                                                     
//   -----------------                                                     
//   u           Hilfsgröße                                                
//                                                                         
///////////////////////////////////////////////////////////////////////////////////////////////////

fld_real FLD_u_frq(fld_real omega_s, int nn) {
    fld_real u; // Gammafkt. berechnet das geom. -arithm. Mittel

    u = PI / 2. / ((fld_real) nn / 2.) * FLD_gammaM(omega_s, 1.) / FLD_gammaM(omega_s + 1, omega_s - 1);

    return (u);
}

///////////////////////////////////////////////////////////////////////////////////////////////////
//                                                                        
// gamma berechnet das geom. arithm. Mittel aus êp und ês nach           
//        Amstutz Abschnitt IV. G										   
//                                                                        
//  Eingabeparameter:                                                     
//  ----------------                                                      
//  ês, êp      Beginn des Sperrbereiches, Ende des Durchlaßbereiches     
//                                                                        
//                                                                        
//  Ausgabeparameter:                                                     
//  -----------------                                                     
//  a           geom. arithm. Mittel                                      
//                                                                        
///////////////////////////////////////////////////////////////////////////////////////////////////

fld_real FLD_gammaM(fld_real a, fld_real b) {
    int i; // Zählvariable
    fld_real ax; // Hilfsvariable

    for (i = 1; i <= 1000; i++) {
        ax = (a + b) / 2; // arithm. Mittel
        b = sqrt(a * b); // geom. Mittel
        if (fabs(ax - a) <= 1.0E-14)
            return (a);
        a = ax;
    }
    return (0); // Fehler aufgetreten
}


///////////////////////////////////////////////////////////////////////////////////////////////////
//     Koeffizientenzuordnung
// Um auf eine allgemeine Form des Biquads zu kommen, muss Av nach hinten transformiert werden
///////////////////////////////////////////////////////////////////////////////////////////////////

void FLD_InitCoeffsFloat(fld_real *num, fld_real *den, fld_real *taps, int N) {
    int i;

    for (i = 0; i < N; i++) {
        num[0] = dsp->Av_Biquad[i];
        num[1] = dsp->Aw_Biquad[i] * dsp->Av_Biquad[i];
        num[2] = dsp->Ax_Biquad[i] * dsp->Av_Biquad[i];
        den[0] = 1;
        den[1] = -dsp->Ay_Biquad[i];
        den[2] = -dsp->Az_Biquad[i];
        taps[0] = 0.0;
        taps[1] = 0.0;
        taps[2] = 0.0;
        num += 3;
        den += 3;
        taps += 3;
    }

}

///////////////////////////////////////////////////////////////////////////////////////////////////
//     Koeffizientenzuordnung für Integer (Fractional Q1.30)
// Um auf eine allgemeine Form des Biquads zu kommen, muss Av nach hinten transformiert werden
///////////////////////////////////////////////////////////////////////////////////////////////////

void FLD_InitCoeffsFixpoint(long *num, long *den, long *taps, int N) {
    int i;

    for (i = 0; i < N; i++) {
        num[0] = (long) (dsp->Av_Biquad[i] * (1 << INTEGER_PRECISION) + 0.5);
        num[1] = (long) (dsp->Aw_Biquad[i] * dsp->Av_Biquad[i] * (1 << INTEGER_PRECISION) + 0.5);
        num[2] = (long) (dsp->Ax_Biquad[i] * dsp->Av_Biquad[i] * (1 << INTEGER_PRECISION) + 0.5);
        den[0] = (long) (1.0 * (1 << INTEGER_PRECISION) + 0.5);
        den[1] = (long) (-dsp->Ay_Biquad[i] * (1 << INTEGER_PRECISION) + 0.5);
        den[2] = (long) (-dsp->Az_Biquad[i] * (1 << INTEGER_PRECISION) + 0.5);
        taps[0] = 0;
        taps[1] = 0;
        taps[2] = 0;
        num += 3;
        den += 3;
        taps += 3;
    }

}


///////////////////////////////////////////////////////////////////////////////////////////////////
//     Koeffizientenzuordnung
///////////////////////////////////////////////////////////////////////////////////////////////////

void FLD_Coefficient_Assignment() {
    int i;
    for (i = 1; i <= dsp->Sub_Filter; i++) {
        dsp->Epsilon = 1 / (dsp->D_Coeff[i] + dsp->E_Coeff[i] + dsp->F_Coeff[i]);
        dsp->Av_Biquad[i - 1] = dsp->Epsilon * (dsp->A_Coeff[i] + dsp->B_Coeff[i] + dsp->C_Coeff[i]);
        dsp->Aw_Biquad[i - 1] = 2 * ((dsp->A_Coeff[i] - dsp->C_Coeff[i]) / (dsp->A_Coeff[i] + dsp->B_Coeff[i] + dsp->C_Coeff[i]));
        dsp->Ax_Biquad[i - 1] = (dsp->A_Coeff[i] - dsp->B_Coeff[i] + dsp->C_Coeff[i]) / (dsp->A_Coeff[i] + dsp->B_Coeff[i] + dsp->C_Coeff[i]);
        dsp->Ay_Biquad[i - 1] = -(2 * dsp->Epsilon * (dsp->D_Coeff[i] - dsp->F_Coeff[i]));
        dsp->Az_Biquad[i - 1] = -(dsp->Epsilon * (dsp->D_Coeff[i] - dsp->E_Coeff[i] + dsp->F_Coeff[i]));
    }
}

/*
///////////////////////////////////////////////////////////////////////////////////////////////////
//     Koeffizienten ermitteln
///////////////////////////////////////////////////////////////////////////////////////////////////
void Digitale_Koeffizienten_ermitteln()
{

    Koeffizientenzuordnung();
    
    // Koeffizientenblöcke so initialisieren,
    // daß alle Teilfilter durchgeschaltet sind. Avs = 1 Aw-Az = 0;
    for(i=0; i <= 15 ;i++)
    {
        Koeffizienten_Block1[i]   = 0x7fff;
    }

   for(i=0; i <= 63 ;i++)
    {
        Koeffizienten_Block2[i]   = 0;
    }

    // Koeffizienten in die zu übertragenden Arrays kopieren
    for(i=1; i <= Teilfilter; i++)
    {
        Koeffizienten_Block1[i-1]   = FloatToQ15(Av[i]);

        Koeffizienten_Block2[4*(i-1)]   = FloatToQ15(Ay[i]/2);
        Koeffizienten_Block2[4*(i-1)+1] = FloatToQ15(Aw[i]/2);
        Koeffizienten_Block2[4*(i-1)+2] = FloatToQ15(Az[i]/2);
        Koeffizienten_Block2[4*(i-1)+3] = FloatToQ15(Ax[i]/2);
    }
}
 */

/*
///////////////////////////////////////////////////////////////////////////////////////////////////
//    Koeffizienten von Floating-Point in Fixed-Point Q16 umrechnen
///////////////////////////////////////////////////////////////////////////////////////////////////
short FloatToQ15(fld_real Float)
{
    bool	Negativ;
    short	Fix;
    int		Zahl;
    fld_real	Temp,Fehler;

    Temp = 0;
    Fix = 0;

    if (Float < 0 )
    {
        Negativ = TRUE;
        Float   = -Float;
    }
    else
    {
        Negativ = FALSE;
    }
    for (Zahl=1 ; Zahl<=15 ; Zahl++)
    {
        Fix = Fix << 1;
        Temp = Temp + pow(2,-Zahl);
        if (Float >= Temp )
        {
            Fix++;
        }
        else
            Temp = Temp - pow(2,-Zahl);
    }
    Fehler = (Float - Temp);
    if ((Fehler >= pow(2,-16)) && (Float>-1) && (Float<1))
        Fix = Fix++;
    if (Negativ)
        Fix = ~Fix +1;
    return (Fix);
}
 */

///////////////////////////////////////////////////////////////////////////////////////////////////
//	die übergebene Frequenz f wird auf die Abtastfrequenz bezogen 
//	und durch die Tangensfunktion so "verzerrt" verschoben, dass 
//	die am Ende des Filterentwurfs folgenden Digitalfilter Koeffizienten
//	korrekte Filtereckfrequenzen erzeugen.
//	Die Notwendigkeit entsteht durch den Fehler der Bilineartransformation. 
///////////////////////////////////////////////////////////////////////////////////////////////////

fld_real Frequency_Transformation(fld_real f, fld_real fa) {
    return ( tan((fld_real) (PI * (f / fa))));
}

/*
///////////////////////////////////////////////////////////////////////////////////////////////////
//	Konvertierungsfunktion um Q15 (short) Werte wieder nach fld_real zu wandeln
///////////////////////////////////////////////////////////////////////////////////////////////////
fld_real Q15Tofloat(short a)
{
    int		i;
    fld_real	x=0;
    short	b=1;
    bool	Negativ=false;

    if(a&0x8000){
        a=~(a+1);
        Negativ=true;
    }

    for(i=-15;i<=-1;i++){
        if(a&b)
            x+=pow(2,i);
        b<<=1;
    }
    if(Negativ)
        x*=-1;
    return(x);
}
 */

///////////////////////////////////////////////////////////////////////////////////////////////////
//	Frequenzen in F1,F2,F3,F4 auf die Abtastrate bezogen transformiert
//	in f1,f2,f3,f4 zu verfügung stellen
///////////////////////////////////////////////////////////////////////////////////////////////////

void FLD_Frequency_Transformation(void) {    
    dsp->f1_Digital = Frequency_Transformation(dsp->F1_Analog, dsp->Samplerate);
    dsp->f2_Digital = Frequency_Transformation(dsp->F2_Analog, dsp->Samplerate);
    dsp->f3_Digital = Frequency_Transformation(dsp->F3_Analog, dsp->Samplerate);
    dsp->f4_Digital = Frequency_Transformation(dsp->F4_Analog, dsp->Samplerate);
}

