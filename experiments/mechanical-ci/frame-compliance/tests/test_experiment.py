"""Fast standard-library tests. These do not claim an external solver ran."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]/"run_experiment.py"
SPEC = importlib.util.spec_from_file_location("frame_experiment", SOURCE)
experiment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(experiment)


def tetra_fixture():
    # Right tetrahedron, with Gmsh's tetra10 midpoint order.
    points = [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (0., 0., 1.)]
    points += [experiment.scale(experiment.add(points[a], points[b]), .5)
               for a, b in experiment.GMSH_EDGES]
    return dict(enumerate(points, 1))


def end_faces():
    nodes, triangles = {}, []
    def node(p):
        for n, point in nodes.items():
            if point == p:
                return n
        n = len(nodes)+1
        nodes[n] = p
        return n
    for x0 in (-2., 1.):
        corners = [(x0, 0., 0.), (x0+1, 0., 0.), (x0+1, 0., 1.), (x0, 0., 1.)]
        for corners3 in ((0, 1, 2), (0, 2, 3)):
            pts = [corners[i] for i in corners3]
            mids = [experiment.scale(experiment.add(pts[a], pts[b]), .5)
                    for a, b in ((0, 1), (1, 2), (2, 0))]
            triangles.append(tuple(node(point) for point in pts+mids))
    return nodes, triangles


class GeometryAndMeshTests(unittest.TestCase):
    def test_fixture_is_independent_box_union_and_mm_mesh(self):
        text = experiment.geometry_text(2.1)
        self.assertIn('SetFactory("OpenCASCADE")', text)
        self.assertIn("BooleanUnion", text)
        self.assertIn("Mesh.ElementOrder = 2", text)
        self.assertNotIn("Import", text)

    def test_tetra_node_reordering_for_abaqus(self):
        nodes = tetra_fixture()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"test.inp"
            experiment.write_deck(path, nodes, [(11, tuple(range(1, 11)))], {(1, 1)},
                                  {2: (.005, 0., 0.)}, 1500., .3)
            self.assertIn("11,1,2,3,4,5,6,7,8,10,9\n", path.read_text())
        abaqus = [nodes[i+1] for i in experiment.ABAQUS_ORDER]
        for index, (a, b) in enumerate(((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))):
            self.assertEqual(abaqus[index+4], experiment.scale(experiment.add(abaqus[a], abaqus[b]), .5))

    def test_quality_volume_and_midside_checks(self):
        dims = {"width_mm": 1., "length_mm": 1., "rail_width_mm": .5, "thickness_mm": 1/6}
        with patch.object(experiment, "DIMENSIONS", dims):
            quality = experiment.mesh_quality(tetra_fixture(), [(1, tuple(range(1, 11)))])
        self.assertAlmostEqual(quality["volume_mm3"], 1/6)
        self.assertEqual(quality["max_midside_coordinate_error_mm"], 0)
        self.assertGreater(quality["minimum_mean_ratio_quality"], 0)

    def test_negative_jacobian_fails(self):
        with self.assertRaisesRegex(experiment.ExperimentError, "Nonpositive"):
            experiment.mesh_quality(tetra_fixture(), [(1, (1, 3, 2, 4, 5, 6, 7, 8, 9, 10))])

    def test_wrong_midside_order_fails(self):
        with self.assertRaisesRegex(experiment.ExperimentError, "node ordering"):
            experiment.mesh_quality(tetra_fixture(), [(1, (1, 2, 3, 4, 5, 6, 7, 8, 10, 9))])

    def test_ascii_mesh_parser(self):
        nodes = tetra_fixture()
        text = "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n$Nodes\n10\n"
        text += "".join(f"{n} {' '.join(map(str, p))}\n" for n, p in nodes.items())
        text += "$EndNodes\n$Elements\n2\n1 9 2 0 1 1 2 3 5 6 7\n"
        text += "2 11 2 0 1 1 2 3 4 5 6 7 8 9 10\n$EndElements\n"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"mesh.msh"
            path.write_text(text)
            actual_nodes, triangles, tets = experiment.read_mesh(path)
            self.assertEqual(actual_nodes, nodes)
            self.assertEqual(len(triangles), 1)
            self.assertEqual(tets[0][1], tuple(range(1, 11)))
            path.write_text(text.replace("2.2 0 8", "4.1 0 8"))
            with self.assertRaisesRegex(experiment.ExperimentError, "ASCII MSH 2.2"):
                experiment.read_mesh(path)


class LoadAndBoundaryTests(unittest.TestCase):
    def test_constant_traction_resultants_and_moments(self):
        nodes, triangles = end_faces()
        with patch.object(experiment, "DIMENSIONS", {"rail_width_mm": 1., "thickness_mm": 1.}):
            weights, areas = experiment.load_weights(nodes, triangles)
        self.assertEqual(areas, {"left": 1., "right": 1.})
        forces = experiment.make_forces(weights, .005)
        for side, expected_x in (("left", -1.5), ("right", 1.5)):
            self.assertAlmostEqual(sum(weights[side].values()), 1.)
            center = experiment.sum_vectors(experiment.scale(nodes[n], w) for n, w in weights[side].items())
            self.assertAlmostEqual(center[0], expected_x)
            self.assertAlmostEqual(center[2], .5)
        self.assertLess(experiment.norm(experiment.sum_vectors(forces.values())), 1e-14)
        self.assertLess(experiment.norm(experiment.sum_vectors(experiment.cross(nodes[n], f)
                                                             for n, f in forces.items())), 1e-14)

    def test_six_gauge_dofs_and_rear_clamp(self):
        nodes = {1: (-21., 58., 0.), 2: (21., 58., 0.), 3: (-17.8, 54.8, 0.), 4: (0., 0., 0.)}
        self.assertEqual(experiment.supports(nodes, "free_gauge"),
                         {(1, 1), (1, 2), (1, 3), (2, 2), (2, 3), (3, 3)})
        self.assertEqual(len(experiment.supports(nodes, "rear_clamp")), 9)

    def test_missing_gauge_is_error(self):
        with self.assertRaisesRegex(experiment.ExperimentError, "Gauge vertex"):
            experiment.supports({1: (0., 0., 0.)}, "free_gauge")

    def test_force_and_moment_and_gauge_residuals(self):
        nodes = {1: (-21., 58., 0.), 2: (21., 58., 0.), 3: (-17.8, 54.8, 0.),
                 4: (-10., 0., 2.), 5: (10., 0., 2.)}
        bc = experiment.supports(nodes, "free_gauge")
        weights = {"left": {4: 1.}, "right": {5: 1.}}
        forces = experiment.make_forces(weights, .005)
        u = {n: (0., 0., 0.) for n in nodes}
        u.update({4: (-.002, 0., 0.), 5: (.002, 0., 0.)})
        rf = {n: forces.get(n, (0., 0., 0.)) for n in nodes}
        out = experiment.summarize_case(nodes, bc, forces, weights, u, rf, .005, "free_gauge", 1500.)
        self.assertAlmostEqual(out["gap_increase_mm"], .004)
        self.assertAlmostEqual(out["gap_compliance_mm_per_N_each_side"], .8)
        self.assertEqual(out["maximum_individual_support_reaction_N"], 0.)
        rf[1] = (.001, 0., 0.)
        with self.assertRaisesRegex(experiment.ExperimentError, "equilibrium"):
            experiment.summarize_case(nodes, bc, forces, weights, u, rf, .005, "free_gauge", 1500.)


class CliAndResultsTests(unittest.TestCase):
    def test_output_root_must_be_new_and_not_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/"new"
            self.assertEqual(experiment.new_output_directory(target), target.absolute())
            marker = target/"preserve.txt"
            marker.write_text("keep")
            with self.assertRaisesRegex(experiment.ExperimentError, "must be new"):
                experiment.new_output_directory(target)
            self.assertEqual(marker.read_text(), "keep")
            symlink = Path(folder)/"dangling"
            symlink.symlink_to(Path(folder)/"missing")
            with self.assertRaisesRegex(experiment.ExperimentError, "symlink"):
                experiment.new_output_directory(symlink)

    def test_successful_solver_message_without_new_data_fails(self):
        nodes = tetra_fixture()
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(experiment, "supports", return_value={(1, 1)}), \
                 patch.object(experiment, "execute", return_value="Job finished"):
                with self.assertRaisesRegex(experiment.ExperimentError, "new result file"):
                    experiment.solve("ccx", Path(folder), nodes, [(1, tuple(range(1, 11)))],
                                     {"left": {2: 1.}, "right": {3: 1.}}, .005, 1500., .3,
                                     "free_gauge", "mock_case", 1.)

    def test_default_arguments_and_invalid_inputs(self):
        args = experiment.parser().parse_args(["--gmsh", "gmsh", "--ccx", "ccx", "--output", "output"])
        experiment.validate_args(args)
        self.assertEqual(args.load, .005)
        args.mesh_sizes = [1., 2.]
        with self.assertRaisesRegex(experiment.ExperimentError, "decreasing"):
            experiment.validate_args(args)
        args.mesh_sizes = [2., 1.]
        args.load = float("nan")
        with self.assertRaisesRegex(experiment.ExperimentError, "finite"):
            experiment.validate_args(args)

    def test_ccx_version_201_is_version_only(self):
        version_run = subprocess.CompletedProcess([], 201, "This is Version 2.23\n", "")
        with patch.object(experiment.subprocess, "run", return_value=version_run):
            self.assertEqual(experiment.detect_version("ccx", "-v", 5, "CalculiX"), "2.23")
            with self.assertRaisesRegex(experiment.ExperimentError, "status 201"):
                experiment.execute(["ccx", "-i", "job"], None, 5, "CalculiX")

    def test_unknown_version_fails(self):
        with patch.object(experiment.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "unknown", "")):
            with self.assertRaisesRegex(experiment.ExperimentError, "identify"):
                experiment.detect_version("gmsh", "--version", 5, "Gmsh")

    def test_timeout_has_no_command_path_in_error(self):
        with patch.object(experiment.subprocess, "run", side_effect=subprocess.TimeoutExpired(["private/tool"], 1)):
            with self.assertRaisesRegex(experiment.ExperimentError, "TimeoutExpired") as caught:
                experiment.execute(["private/tool"], None, 1, "Gmsh")
        self.assertNotIn("private", str(caught.exception))

    def test_compact_output_has_explicit_unknown_scope_and_excludes_paths(self):
        fields = ("schema_version", "fixture", "units", "dimensions", "tool_versions", "python_version",
                  "generator_sha256", "material", "load", "boundary_conditions", "convergence",
                  "E_halved_compliance_ratio", "free_to_clamped_compliance_ratio", "validation_scope",
                  "not_modeled", "checks_passed")
        summary = dict.fromkeys(fields)
        summary.update({"schema_version": 1, "meshes": [], "private_execution_path": "/private/example",
                        "validation_scope": {"physical_retention_or_failure_load": "unknown"}})
        compact = experiment.compact_summary(summary)
        self.assertNotIn("private_execution_path", compact)
        self.assertEqual(compact["validation_scope"]["physical_retention_or_failure_load"], "unknown")
        self.assertEqual(compact["hash_algorithm"], "sha256")

    def test_nonfinite_solver_result_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"bad.dat"
            path.write_text("displacements (vx,vy,vz)\n 1 nan 0 0\nforces (fx,fy,fz)\n 1 0 0 0\n")
            with self.assertRaises(experiment.ExperimentError):
                experiment.parse_results(path)

    def test_parse_displacement_and_force(self):
        text = "displacements (vx,vy,vz) for set ALLN\n\n 1 1.0E-3 0.0 0.0\n"
        text += "forces (fx,fy,fz) for set ALLN\n\n 1 0.005 0.0 0.0\n"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"case.dat"
            path.write_text(text)
            u, rf = experiment.parse_results(path)
            self.assertEqual(u[1], (.001, 0., 0.))
            self.assertEqual(rf[1], (.005, 0., 0.))


if __name__ == "__main__":
    unittest.main()
