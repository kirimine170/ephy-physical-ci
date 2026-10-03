"""Behavioral regressions for the research experiment, using original toy inputs."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cadquery as cq
import numpy as np
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCP.IFSelect import IFSelect_RetDone

CHILD_ENV = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import experiment


class EscapeExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.tmp.name)
        cls.fixture = cls.directory / "fixtures"
        subprocess.run([sys.executable, str(ROOT / "build_fixtures.py"), str(cls.fixture)],
                       check=True, capture_output=True, env=CHILD_ENV)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_open_and_closed_examples_distinguish_claims(self):
        opened = experiment.run(self.fixture / "open.step", self.fixture / "moving.step", proposals=100)
        closed = experiment.run(self.fixture / "closed.step", self.fixture / "moving.step", proposals=100)
        self.assertEqual(opened["result"], "sampled_escape_candidate")
        self.assertTrue(opened["selected_path_BRep_replay"]["sampled_clear"])
        self.assertEqual(opened["selected_tree_path"][0], [0.] * 6)
        self.assertEqual(closed["result"], "not_found_in_bounded_search")
        self.assertFalse(closed["retention_proven"])
        self.assertFalse(closed["whole_graph_BRep_verified"])
        self.assertEqual(closed["selected_path_kind"], "reachable_play_only")
        self.assertGreater(closed["connected_nodes"], 1)

    def test_BRep_replay_rejects_clear_endpoints_with_obstructed_middle(self):
        # Both endpoints outside a solid wall; intermediate samples cross it.
        wall, body = self.directory / "wall.step", self.directory / "body.step"
        cq.exporters.export(cq.Solid.makeBox(1, 4, 4, cq.Vector(0, -2, -2)), str(wall))
        cq.exporters.export(cq.Solid.makeBox(.5, .5, .5, cq.Vector(-2, -.25, -.25)), str(body))
        path = [np.zeros(6), np.array([5., 0., 0., 0., 0., 0.])]
        result = experiment.replay(wall, body, path, np.array([-1.75, 0., 0.]), .1)
        self.assertFalse(result["sampled_clear"])
        self.assertGreater(result["first_collision"]["overlap_mm3"], experiment.VOLUME_TOLERANCE)

    def test_mesh_and_BRep_rotation_conventions_agree(self):
        shape = experiment.read_solid(self.fixture / "moving.step")
        q = np.array([1., -.2, .3, 13., -17., 29.])
        pivot = np.array([0., 0., 3.])
        rotation, translation = experiment.pose_matrix(q, pivot)
        expected = np.array([v.toTuple() for v in shape.Vertices()]) @ rotation.T + translation
        actual = np.array([v.toTuple() for v in experiment.transform_brep(shape, q, pivot).Vertices()])
        for point in expected:
            self.assertLess(np.linalg.norm(actual - point, axis=1).min(), 1e-9)

    def test_point_motion_bound_and_connected_parent_chain(self):
        a, b = np.zeros(6), np.array([.3, -.4, .2, 10, -20, 30.])
        radius, maximum = 3., .1
        points = np.eye(3) * radius
        previous = points
        for q in experiment.sample_edge(a, b, radius, maximum):
            rotation, translation = experiment.pose_matrix(q, np.zeros(3))
            current = points @ rotation.T + translation
            self.assertLessEqual(np.linalg.norm(current - previous, axis=1).max(), maximum + 1e-10)
            previous = current
        states = [a, b, b + 1]
        self.assertEqual(len(experiment.backtrack(states, [-1, 0, 1], 2)), 3)
        for bad in ([-1, 1, 1], [-1, -1, 1]):
            with self.assertRaises(ValueError):
                experiment.backtrack(states, bad, 2)

    def test_goal_beyond_domain_is_rejected(self):
        tall = self.directory / "tall.step"
        # Moving body is outside this wall; the above-wall goal exceeds dz bounds.
        cq.exporters.export(cq.Solid.makeBox(1, 1, 50, cq.Vector(10, 10, 0)), str(tall))
        with self.assertRaisesRegex(ValueError, "goal is unreachable"):
            experiment.run(tall, self.fixture / "moving.step", proposals=1)

    def test_multiple_STEP_roots_are_rejected_without_dropping_obstacles(self):
        destination = self.directory / "multiple_roots.step"
        writer = STEPControl_Writer()
        remote = cq.Solid.makeBox(1, 1, 1, cq.Vector(10, 10, 0))
        overlapping = experiment.read_solid(self.fixture / "moving.step")
        for shape in (remote, overlapping):
            self.assertEqual(writer.Transfer(shape.wrapped, STEPControl_AsIs), IFSelect_RetDone)
        self.assertEqual(writer.Write(str(destination)), IFSelect_RetDone)
        self.assertEqual(len(cq.importers.importStep(str(destination)).vals()), 2)
        with self.assertRaisesRegex(ValueError, "no extra STEP roots"):
            experiment.run(destination, self.fixture / "moving.step", proposals=10)

    def test_overlapping_origin_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "origin overlaps"):
            experiment.run(self.fixture / "moving.step", self.fixture / "moving.step", proposals=1)

    def test_cli_refuses_existing_output_without_modifying_it(self):
        output = self.directory / "preserve.json"
        output.write_text("keep")
        result = subprocess.run([sys.executable, str(ROOT / "experiment.py"),
                                 "--fixed", str(self.fixture / "open.step"),
                                 "--moving", str(self.fixture / "moving.step"),
                                 "--output", str(output)], capture_output=True, text=True, env=CHILD_ENV)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("output already exists", result.stderr)
        self.assertEqual(output.read_text(), "keep")

    def test_invalid_budgets_and_sample_spacing(self):
        for proposals in (0, -1, 200001):
            with self.assertRaises(ValueError):
                experiment.run(self.fixture / "open.step", self.fixture / "moving.step", proposals=proposals)
        with self.assertRaises(ValueError):
            experiment.run(self.fixture / "open.step", self.fixture / "moving.step", point_step=0)
        with self.assertRaises(ValueError):
            experiment.step_count(np.zeros(6), np.ones(6), 10, float("nan"))


if __name__ == "__main__":
    unittest.main()
