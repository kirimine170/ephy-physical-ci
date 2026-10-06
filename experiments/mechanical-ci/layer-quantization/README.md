# Synthetic layer-height and coordinate-projection experiment

Ten original cuboids show how a 0.1 mm CAD change appears in a fixed BambuStudio slice. These are analysis-only data, not printer instructions or physical accuracy measurements.

| CAD dimension H (mm) | Flat model top deposition Z (mm) | Flat model layer count | Side model top Z / layers | Side outer-wall Y maximum at Z=0.4 (mm) |
| --- | --- | --- | --- | --- |
| 2.4 | 2.4 | 12 | 8 / 40 | 82.19 |
| 2.5 | 2.4 | 12 | 8 / 40 | 82.29 |
| 2.6 | 2.6 | 13 | 8 / 40 | 82.39 |
| 2.7 | 2.8 | 14 | 8 / 40 | 82.49 |
| 2.8 | 2.8 | 14 | 8 / 40 | 82.59 |

The flat cuboid is 10 × 8 × H at (80,80,0); the side cuboid is 10 × H × 8 at the same minimum corner. Thus the changed dimension projects to machine Z or machine Y respectively. At the selected Z=0.4 exterior layer, Y minimum is 80.21 and line width is 0.42. The nominal centerline-plus-half-width envelope therefore ends at Y=82.4 through 82.8 in the side series. This envelope is not the printed bead boundary.

A 0.1 mm change can leave top Z unchanged or cross a 0.2 mm layer boundary in these conditions. The XY contour can move by 0.1 mm under the same profile. Do not infer a universal ceiling/floor rule: STL floating-point coordinates and slicing thresholds can affect boundary cases. Same top Z and layer count do not imply the same internal paths. In particular, 2.7 and 2.8 have different internal paths; see [correction history](REVIEW_HISTORY.md).

## Frozen conditions and provenance

- Official [BambuStudio 02.08.02.61](https://github.com/bambulab/BambuStudio/releases/tag/v02.08.02.61), Ubuntu 24.04 AppImage
- AppImage SHA256: `d501b103fac5424513ec0e8d6bc145fb30719de2c7d94d7320d723740c81a7fd`
- Extracted `bin/bambu-studio` SHA256: `d267ad0b4589c46cb18f49e2414f87a529b446dc992cb6ab8a728fe43f549eb8`
- Official A1 mini 0.4 nozzle / 0.20mm Standard / Generic PLA profile inheritance, with fixed 3 walls, 20% infill and support-off process conditions
- All ten runs use identical machine, filament and process bytes; resolved settings report `precise_z_height=0`, first and normal layer height 0.2, regular slicing, nozzle 0.4
- Placement/rotation/orientation automation disabled. Exported 3MF instance rotations/scales are identity and transformed bounds match the input STL within 1e-5 mm
- CadQuery 2.7.0 generated original cuboids. No private case CAD or measurements are included

## Evidence and reproduction

`evidence.zip` preserves all ten original STL inputs, raw analysis-only G-code files, full resolved settings and exported 3MF files, plus fixed profiles and their official source hashes. `data-manifest.json` records every archived file's length and SHA256. Executables and runtime dependencies are excluded. Raw historical data are present; a fresh run need not produce identical bytes.

Read-only audit without a slicer or CadQuery:

```sh
python -m zipfile -e evidence.zip /tmp/quantization-audit
cp cases.json /tmp/quantization-audit/
python audit.py --root /tmp/quantization-audit
```

Fresh nonprinting reproduction using the already extracted, hash-matched official AppImage and installed CadQuery 2.7.0:

```sh
python reproduce.py --appdir /path/to/squashfs-root --output /path/to/fresh-run
python audit.py --root /path/to/fresh-run
```

If that official runtime needs additional existing shared libraries, supply `--library-path /path/to/libraries`. The script does not install software, download dependencies or send data to a printer. It uses only original cuboids and the frozen profile bytes. Generated G-code must remain analysis-only; do not send it to a printer.

## Audit coverage and limits

The audit handles the model FEATURE roles observed in these ten files, excluding Brim and Custom: Outer wall, Inner wall, Sparse infill, Internal solid infill, Top surface, Gap infill, Bridge, Bottom surface and Floating vertical shell. It tracks G0/G1/G2/G3 modal endpoints, absolute/relative E, retraction debt, layer Z/height and line width. It records arc I/J/R metadata. Selected exterior extrema are explicitly restricted to straight G1 paths at Z=0.4; it does not calculate general arc extrema.

This is a bounded parser for these files, not a complete G-code dialect interpreter or a firmware-conditional simulator. The geometric signature excludes extrusion quantity and speed. No print was performed: dimensional accuracy, shrinkage, anisotropy, fit, force, retention and material calibration remain unverified. No product-code fix, dependency installation in CI or license selection is part of this experiment.
