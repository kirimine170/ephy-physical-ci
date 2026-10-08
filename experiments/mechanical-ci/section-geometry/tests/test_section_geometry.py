import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import trimesh
from section_geometry import mesh_audit, section_relation, fit_circle_2d, section_material

class GeometryTests(unittest.TestCase):
    def box(self,dx=0):
        m=trimesh.creation.box(extents=[2,2,2]);m.apply_translation([dx,0,0]);return m
    def test_closed_mesh(self):
        a=mesh_audit(self.box());self.assertTrue(a['edge_watertight']);self.assertEqual(a['boundary_edges'],0)
    def test_open_mesh(self):
        a=self.box();a.update_faces(np.arange(len(a.faces))!=0);self.assertFalse(mesh_audit(a)['edge_watertight'])
    def test_separated(self):
        r=section_relation(self.box(),self.box(3),0);self.assertAlmostEqual(r['separation'],1);self.assertEqual(r['overlap_area'],0)
    def test_overlap(self):
        r=section_relation(self.box(),self.box(1),0);self.assertEqual(r['status'],'overlap');self.assertAlmostEqual(r['overlap_area'],2)
    def test_touch_is_not_gap(self):
        r=section_relation(self.box(),self.box(2),0);self.assertEqual(r['overlap_area'],0);self.assertEqual(r['separation'],0)
    def test_missing_not_pass(self):
        r=section_relation(self.box(),self.box(),3);self.assertEqual(r['status'],'no_shared_section');self.assertIsNone(r['separation'])
    def test_invalid_parameters(self):
        for z,t in [(float('nan'),0),(0,-1),(0,float('inf'))]:
            with self.assertRaises(ValueError):section_relation(self.box(),self.box(),z,t)
    def test_fit_circle(self):
        a=np.linspace(0,2*np.pi,64,endpoint=False);p=np.c_[2*np.cos(a)+7,2*np.sin(a)-4]
        r=fit_circle_2d(p);self.assertTrue(np.allclose(r['center'],[7,-4]));self.assertAlmostEqual(r['mean_vertex_radius'],2)
    def test_reject_collinear(self):
        with self.assertRaises(ValueError):fit_circle_2d([[0,0],[1,0],[2,0]])
    def test_fit_translation(self):
        a=np.linspace(0,2*np.pi,64,endpoint=False);p=np.c_[2*np.cos(a),2*np.sin(a)]+1e6
        self.assertAlmostEqual(fit_circle_2d(p)['mean_vertex_radius'],2,places=8)
    def test_hole_not_filled(self):
        m=trimesh.creation.annulus(r_min=1,r_max=2,height=2,sections=128)
        a=section_material(m,0);from shapely.geometry import Point
        self.assertFalse(a.contains(Point(0,0)));self.assertTrue(a.contains(Point(1.5,0)))


    def test_reject_partial_open_components(self):
        closed=self.box(); opened=self.box(10)
        opened.update_faces(np.arange(len(opened.faces))!=0)
        combined=trimesh.util.concatenate([closed,opened])
        with self.assertRaises(ValueError):section_material(combined,0)
    def test_reject_crossing_rings(self):
        a=self.box(); b=self.box(); b.apply_translation([.5,.5,0])
        with self.assertRaises(ValueError):section_material(trimesh.util.concatenate([a,b]),0)
    def test_output_hardlink_protected(self):
        import tempfile,pathlib,subprocess,sys,os
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);src=root/'a.stl';dst=root/'b.json'
            src.write_bytes(self.box().export(file_type='stl'));before=src.read_bytes();os.link(src,dst)
            script=pathlib.Path(__file__).resolve().parents[1]/'section_geometry.py'
            r=subprocess.run([sys.executable,str(script),str(src),'--output',str(dst)],capture_output=True)
            self.assertNotEqual(r.returncode,0);self.assertEqual(src.read_bytes(),before)


    def test_reject_nested_separate_solids(self):
        outer=trimesh.creation.box(extents=[4,4,4]); inner=self.box()
        with self.assertRaises(ValueError):section_material(trimesh.util.concatenate([outer,inner]),0)

if __name__=='__main__':unittest.main()
