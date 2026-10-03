# Module for Hyperspectral Single Molecule Localization Microscopy

Single Molecule Localization Microscopy (SMLM) is a super-resolution technique that relies on observing individual fluorphores and identifying its sub-pixel location. In order to observe two different components within a cell, fluorophores with different emission wavelengths are used. Under TIRF illumination, the penetration depth of the evanescent field is dependant on the excitation wavelength. Acquring SMLM images using two different excitation wavelengths will generate two different images since higher wavelengths will excite deeper into the sample. Using the same laser for both fluorophores will ensure that both are excited up to the same penetration depth. The Hyperspectral SMLM module will then separate the emission from the different fluorophores.


<p align="center">
	<img src="/HyperspectralSMLM/images/schematic.png" alt="Hyperspectral SMLM schematic" width="70%">
</p>


The module is place in the infinity space of the microscope body, Mod_Em1. A Verschrome tunable filter was used to filter out emission light. The tunable filter permits specific wavelengths of light based on its incoming angle. The filter was attached to a galvo motor for fine adjustments to the filter angle. 

## More details:
A. Vissa, M. Giuliani, PK. Kim, CM. Yip, **Hyperspectral super-resolution imaging with far-red emitting fluorophores using a thin-film tunable filter**, [https://doi.org/10.1101/756023](https://www.biorxiv.org/content/10.1101/756023v1)