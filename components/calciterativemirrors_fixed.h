/**
 * @file calciterativemirrors.h
 * @brief Functions for calculating nested mirror positions for NMO assemblies
 * 
 * Implements the iterative mirror construction algorithm described in:
 * O. Zimmer, "Multi-mirror imaging optics for low-loss transport of divergent 
 * neutron beams and tailored wavelength spectra", arXiv:1611.07353 (2016)
 * 
 * Also works reasonably well for parabolic mirrors.
 */

#ifndef CALCITERATIVEMIRRORS_H
#define CALCITERATIVEMIRRORS_H

#include <stdio.h>
#include <math.h>
#include <stdlib.h>

/**
 * @brief Calculate array of mirror distances for a nested mirror assembly
 * 
 * Uses the iterative construction where the back edge of mirror n connects
 * to the front edge of mirror n+1 when viewed from the focal point.
 * 
 * @param number    Number of mirrors to calculate
 * @param z_0       Z-coordinate of the initial point on the outermost mirror
 * @param r_0       R-coordinate (distance from axis) of the initial point
 * @param z_extract Z-coordinate at which to extract the mirror distances
 * @param LStart    Z-coordinate of the first (left) focal point
 * @param LEnd      Z-coordinate of the second (right) focal point  
 * @param lStart    Z-coordinate where the mirrors begin
 * @param lEnd      Z-coordinate where the mirrors end
 * 
 * @return Pointer to allocated array of 'number' distances (caller must free)
 *         Returns NULL on allocation failure
 * 
 * @note The returned array must be freed by the caller using free()
 * 
 * @example
 * double *b_values = get_r_at_z0(10, 0, 0.02, -0.05, -0.6, 0.6, -0.05, 0.05);
 * if (b_values) {
 *     for (int i = 0; i < 10; i++) {
 *         printf("Mirror %d: b = %f m\n", i, b_values[i]);
 *     }
 *     free(b_values);
 * }
 */
double* get_r_at_z0(int number, double z_0, double r_0, double z_extract, 
                    double LStart, double LEnd, double lStart, double lEnd) {
    
    int n = number;
    
    // Allocate array for results
    double *r_zExtracts = malloc(n * sizeof(double));  // Fixed: was double_t
    if (!r_zExtracts) {
        fprintf(stderr, "get_r_at_z0: Memory allocation failed for %d mirrors\n", n);
        return NULL;
    }
    
    // Initialize first mirror position
    r_zExtracts[0] = r_0;
    
    // Helper variables for ellipse parameters
    // Ellipse equation: r² = k1 + k2*z + k3*z²
    // See conic_finite_mirror.h for derivation
    double k1, k2, k3;
    double c;      // Half distance between focal points: c = (LEnd - LStart)/2
    double u;      // Shifted z-coordinate relative to ellipse center
    double a;      // Semi-major axis of ellipse
    double r_lEnd;
    double r_lStart;
    
    // Calculate initial ellipse from the point (z_0, r_0)
    c = (LEnd - LStart) / 2.0;
    u = (z_0 + c - LEnd);
    
    // Semi-major axis from the ellipse equation with foci at ±c
    // Using: r² + (z-c)² / a² = 1 and r²/b² + z²/a² = 1 where b² = a² - c²
    a = sqrt((u*u + c*c + r_0*r_0 + sqrt(pow(u*u + c*c + r_0*r_0, 2) - 4*c*c*u*u)) / 2.0);
    
    // Calculate k-coefficients for the conic equation r² = k1 + k2*z + k3*z²
    k3 = c*c / (a*a) - 1.0;
    k2 = 2.0 * k3 * (c - LEnd);
    k1 = k3 * (c - LEnd) * (c - LEnd) - c*c + a*a;
    
    #ifdef DEBUG_NMO
    printf("Initial ellipse: k1=%f, k2=%f, k3=%f, a=%f, c=%f\n", k1, k2, k3, a, c);
    #endif
    
    // Iteratively calculate each mirror position
    for (int k = 0; k < number; k++) {
        // Extract radius at the requested z-coordinate for this mirror
        r_zExtracts[k] = sqrt(k1 + k2*z_extract + k3*z_extract*z_extract);
        
        // Calculate radius at the end of this mirror
        r_lEnd = sqrt(k1 + k2*lEnd + k3*lEnd*lEnd);
        
        // The next mirror's starting point is determined by the line from F1
        // through the back edge of this mirror
        // This ensures neutrons from F1 reflecting off mirror k hit mirror k+1
        r_lStart = r_lEnd * (lStart - LStart) / (lEnd - LStart);
        
        // Calculate the new ellipse passing through (lStart, r_lStart)
        c = (LEnd - LStart) / 2.0;
        u = (lStart + c - LEnd);
        a = sqrt((u*u + c*c + r_lStart*r_lStart + 
                  sqrt(pow(u*u + c*c + r_lStart*r_lStart, 2) - 4*c*c*u*u)) / 2.0);
        
        k3 = c*c / (a*a) - 1.0;
        k2 = 2.0 * k3 * (c - LEnd);
        k1 = k3 * (c - LEnd) * (c - LEnd) - c*c + a*a;
        
        #ifdef DEBUG_NMO
        printf("Mirror[%d]: b=%f, k1=%f, k2=%f, k3=%f\n", k, r_zExtracts[k], k1, k2, k3);
        #endif
    }
    
    return r_zExtracts;
}

/**
 * @brief Calculate mirror positions and print summary
 * 
 * Convenience wrapper around get_r_at_z0 that prints the results.
 * Useful for debugging and verification.
 */
double* get_r_at_z0_verbose(int number, double z_0, double r_0, double z_extract,
                            double LStart, double LEnd, double lStart, double lEnd) {
    
    printf("Calculating %d nested mirror positions:\n", number);
    printf("  Focal points: F1 = %g m, F2 = %g m\n", LStart, LEnd);
    printf("  Mirror extent: z = [%g, %g] m\n", lStart, lEnd);
    printf("  Outermost mirror: r_0 = %g m at z_0 = %g m\n", r_0, z_0);
    printf("  Extraction plane: z = %g m\n", z_extract);
    
    double *results = get_r_at_z0(number, z_0, r_0, z_extract, LStart, LEnd, lStart, lEnd);
    
    if (results) {
        printf("  Results:\n");
        for (int i = 0; i < number; i++) {
            printf("    Mirror[%2d]: b = %10.6f m\n", i, results[i]);
        }
        printf("  Divergence coverage: %.3f deg to %.3f deg\n",
               atan(results[number-1] / LStart) * 180.0 / M_PI,
               atan(results[0] / LStart) * 180.0 / M_PI);
    }
    
    return results;
}

#endif /* CALCITERATIVEMIRRORS_H */
