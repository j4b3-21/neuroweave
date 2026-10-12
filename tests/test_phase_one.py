from pathlib import Path
import tempfile
import unittest
import os

from typer.testing import CliRunner

from src.cli.main import app
from src.cli.workspace import initialize_workspace


runner = CliRunner()


class PhaseOneInitializationTest(unittest.TestCase):
    def test_initialize_workspace_creates_phase_one_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            result = initialize_workspace(tmp_path)

            workspace_path = tmp_path.resolve() / ".neuroweave"

            self.assertEqual(result.workspace_path, workspace_path)
            self.assertTrue(workspace_path.is_dir())
            self.assertTrue((workspace_path / "project.json").is_file())
            self.assertTrue((workspace_path / "graph.json").is_file())

            for directory_name in ("snapshots", "runs", "artifacts"):
                self.assertTrue((workspace_path / directory_name).is_dir())

    def test_initialize_workspace_preserves_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            workspace_path = tmp_path / ".neuroweave"
            workspace_path.mkdir()

            project_file = workspace_path / "project.json"
            project_file.write_text("{\"custom\": true}\n", encoding="utf-8")

            graph_file = workspace_path / "graph.json"
            graph_file.write_text("{\"graph\": \"custom\"}\n", encoding="utf-8")

            result = initialize_workspace(tmp_path)

            self.assertEqual(
                project_file.read_text(encoding="utf-8"),
                "{\"custom\": true}\n",
            )
            self.assertEqual(
                graph_file.read_text(encoding="utf-8"),
                "{\"graph\": \"custom\"}\n",
            )
            self.assertIn(project_file.resolve(), result.existing_files)
            self.assertIn(graph_file.resolve(), result.existing_files)

    def test_nw_init_command_outputs_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            previous_cwd = Path.cwd()
            os.chdir(tmp_dir)
            try:
                workspace_root = Path.cwd().resolve()
                result = runner.invoke(app, ["init"])
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(result.exit_code, 0)
            self.assertIn("Initialized workspace at", result.output)
            self.assertTrue((workspace_root / ".neuroweave" / "project.json").is_file())


if __name__ == "__main__":
    unittest.main()
