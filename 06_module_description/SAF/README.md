# Module for Supercritical Angle Fluorescence Measurements

Supercritical Angle Fluorescence (SAF) imaging is a multipurpose technique that can be used to detect fluoresence emissions close to the cover glass surface and make inferences with regards to sample adhesion to the coverglass, refractive index changes within a cell. These observations can be made by looking at the back focal plane of the sample.


![SAF Schematic](/SAF/images/schematic.png)


The SAF module is placed in the 2nd slot of the microscope body (Mod_Em1). It consists of a lens mounted on a servo motor. An arduino is used to control the servo to move the lens in and out of the optical axis. A button or serial command can be issued to manipulate the servo.


A excitation component can be incorporated  to reduce contribution from bulk excitation. An annulus with a lens pair combination can be added to generate TIRF illumination, eliminating epifluoresence excitation.  
  
  
The SAF images can be analyzed with the python class to acquire radial and circumferential profiles of the SAF images.  
  
  
## Component List:  
MG996R Servo motor  
AC254-200-A-ML


## Fabricated components:
Servo_holder
Circuit


## Suggested Reads:
M. Oheim, A. Salomon, M. Brunstein., **Supercritical Angle Fluorescence Microscopy and Spectroscopy**, [doi:10.1016/j.bpj.2020.03.029](https://www.sciencedirect.com/science/article/pii/S0006349520303003)


## TODO:
* Add arduino code
* Add python code
* Add new schematic
* Add stl for servo holder
* Add schematic for servo circuit.
