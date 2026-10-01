"""Run in FreeCAD's Python environment; no GUI, network or devices are used."""
import argparse
import json
from pathlib import Path
import FreeCAD as App
import Part


def verify(root):
    report = {'freecad_version': App.Version()[:3], 'step_roundtrip': {}}
    for path in sorted((root/'step').glob('*.step')):
        shape = Part.read(str(path))
        expected = 2 if 'ASSEMBLY_NOT_FOR_PRINT' in path.name else 1
        assert shape.isValid() and len(shape.Solids) == expected and shape.Volume > 0
        report['step_roundtrip'][path.name] = {
            'valid': shape.isValid(), 'solids': len(shape.Solids),
            'volume_mm3': shape.Volume,
            'surface_types': sorted({type(f.Surface).__name__ for f in shape.Faces}),
        }
    assert len(report['step_roundtrip']) == 11
    doc = App.openDocument(str(root/'freecad'/'nrf52840_sense.FCStd'))
    try:
        original = doc.PRINT_Base.Shape.Volume
        previous = doc.Parameters.XYClearance
        doc.Parameters.XYClearance = 0.65
        doc.recompute()
        modified = doc.PRINT_Base.Shape.Volume
        assert doc.PRINT_Base.Shape.isValid() and abs(modified-original) > 1e-4
        doc.Parameters.XYClearance = previous
        doc.recompute()
        assert abs(doc.PRINT_Base.Shape.Volume-original) < 1e-6
        imported = Part.read(str(root/'step'/'nrf52840_sense_base.step'))
        assert abs(imported.Volume-original) < 1e-6
        report['parametric_edit'] = {
            'parameter': 'XYClearance', 'original_mm': previous, 'test_mm': 0.65,
            'original_volume_mm3': original, 'modified_volume_mm3': modified,
            'restored_volume_mm3': doc.PRINT_Base.Shape.Volume,
            'step_volume_delta_mm3': abs(imported.Volume-original),
        }
    finally:
        App.closeDocument(doc.Name)
    report['physical_fit_verified'] = False
    report['powered_thermal_test'] = False
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root
    report = verify(root)
    (root/'reports'/'cad_verification.json').write_text(
        json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
