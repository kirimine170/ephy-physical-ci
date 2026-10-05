; Original synthetic analysis-only G-code fixture. Do not execute on a printer.
G21
G90
M83
;WIDTH:0.4
;HEIGHT:0.2
;TYPE:Support material interface
G0 X-2 Y5 Z11.8
G1 X12 Y5 E1
;TYPE:Support material
G0 X1 Y5 Z11.7
G1 X9 Y5 Z11.9 E1
