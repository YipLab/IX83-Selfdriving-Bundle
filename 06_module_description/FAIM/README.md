# Module for Fluoresence Anisotropy Imaging Microscopy

This module observes the fluoresence emission polarization. An [Optosplit II](https://www.cairn-research.co.uk/product/optosplit-ii/) was used to separate parallel and perpendicular emissions onto the camera sensor. Post processing is then used to split the image and extract ratiometric information.

<p align="center">
	<img src="/FAIM/images/schematic.png" alt="FAIM Schematic" width="50%">
</p>


Inside the optosplit, the emission light is split into two paths. A broadband polarized beam splitter cube (PBS) is used to separate the polarization from the emission light. Linearly polarized filters are used to further clean up the polarizations.

## Component List

[Optosplit II](https://www.cairn-research.co.uk/product/optosplit-ii/)  
[Polarized Beam Splitter Cube](https://www.thorlabs.com/thorproduct.cfm?partnumber=PBS201)  
[Linear Polarized Filters](https://www.thorlabs.com/thorproduct.cfm?partnumber=LPVISE100-A)  

## Suggested Reads
DW. Piston, MA. Rizzo, **FRET by Fluorescence Polarization**, [https://doi.org/10.1016/S0091-679X(08)85018-2](https://www.sciencedirect.com/science/article/pii/S0091679X08850182)

F. Strohl, HHW. Wong, CE. Holt, CF Kaminski, **Total internal reflection anisotropy imaging microscopy: setup, calibration, and data processing for protein polymerization measurements in living cells**, [https://iopscience.iop.org/article/10.1088/2050-6120/aa872e](https://iopscience.iop.org/article/10.1088/2050-6120/aa872e)

## TODO:
* post processing scripts