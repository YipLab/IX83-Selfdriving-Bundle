# Calibration Protocol for FAIM on IX83

## G Factor calibration

1. Select isotropic solution(s) for measurement: (should match excitation wavelengths in experiments)  
* 405 nm | 10 nM AF405 (untested)
* 488 nm | 10 nM Fluorescein
* 561 nm | 10 nM AF568 (untested)
* 640 nm | 10 nM AF647 (untested)
2. Select the appropriate excitation method(s) (ie. Epi, TIRF).
3. Acquire images with Optosplit using low NA objective (< 0.7). Ensure no pixels are saturated
4. Use G factor calibration script to acquire 2D G factor.