"""Regression tests for the original passive XIAO first-fit fixture package."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]/'hardware'/'xiao-first-fit-v0.1'
SPEC = importlib.util.spec_from_file_location('xiao_meshes', ROOT/'sources'/'validate_meshes.py')
MESHES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MESHES)


class XiaoArtifactTests(unittest.TestCase):
    def test_manifest_covers_files_and_hashes(self):
        manifest = json.loads((ROOT/'MANIFEST.json').read_text())
        expected = set()
        for record in manifest['files']:
            path = Path(record['path'])
            self.assertFalse(path.is_absolute())
            self.assertNotIn('..', path.parts)
            expected.add(path.as_posix())
            data = (ROOT/path).read_bytes()
            self.assertEqual(record['size_bytes'], len(data), str(path))
            self.assertEqual(record['sha256'], hashlib.sha256(data).hexdigest(), str(path))
        actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts
                  and 'build' not in p.relative_to(ROOT).parts
                  and p.name != 'MANIFEST.json'}
        self.assertEqual(expected, actual)
        self.assertFalse(manifest['physical_fit_verified'])
        self.assertFalse(manifest['powered_thermal_test'])

    def test_eight_printable_meshes(self):
        report = MESHES.validate(ROOT)
        self.assertEqual(set(report), MESHES.EXPECTED)
        self.assertEqual(report['tray_four_xiao.stl']['bbox_mm'], [165.6, 52.8, 5.2])

    def test_rejects_empty_truncated_and_open_meshes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'bad.stl'
            for data in (b'', b'\0'*84, b'\0'*80+struct.pack('<I', 1),
                         b'\0'*80+struct.pack('<I', 1)+struct.pack('<12fH',
                         0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0)):
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    MESHES.inspect_stl(path)

    def test_rejects_missing_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                MESHES.validate(Path(tmp))

    def test_native_documents_exclude_imported_board_models(self):
        expected = {'00_REVIEW_assembly.FCStd', 'OPTIONAL_fit_coupon.FCStd',
                    'esp32s3_sense.FCStd', 'nrf52840_sense.FCStd',
                    'ra4m1.FCStd', 'tray_four_xiao.FCStd'}
        self.assertEqual({p.name for p in (ROOT/'freecad').glob('*')}, expected)
        for path in (ROOT/'freecad').glob('*.FCStd'):
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if name.endswith('.xml'):
                        content = archive.read(name).decode('utf-8')
                        self.assertNotIn('OFFICIAL_OLD_REFERENCE', content)
                        self.assertNotIn('/workspace/', content)
        self.assertFalse((ROOT/'reference').exists())
        self.assertFalse(list(ROOT.rglob('*.zip')))
        self.assertFalse(list(ROOT.rglob('*.FCBak')))


if __name__ == '__main__':
    unittest.main()
