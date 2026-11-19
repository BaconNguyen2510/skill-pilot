"""Execute the workflow's failure handling and artifact filtering without CI/network."""

import ast
import io
import json
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import CodeType, FunctionType, SimpleNamespace


class WorkflowControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = (Path(__file__).parents[1] / "workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        cls.syntax_step = workflow.split("      - name: Syntax check\n", 1)[1].split(
            "\n      - name:", 1
        )[0]
        gate = workflow.split(
            "      - name: Candidate integrity and release gates\n", 1
        )[1]
        block = gate.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0]
        tree = ast.parse(textwrap.dedent(block))
        helper = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        )
        doctor_start = next(
            i
            for i, node in enumerate(tree.body)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "doctor"
                for target in node.targets
            )
        )
        helper_module = compile(
            ast.Module(body=[helper], type_ignores=[]), "workflow-run-helper", "exec"
        )
        cls.helper_code = next(
            value for value in helper_module.co_consts if isinstance(value, CodeType)
        )
        doctor_function = ast.FunctionDef(
            name="_check_doctor",
            args=ast.arguments(
                posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]
            ),
            body=tree.body[doctor_start:],
            decorator_list=[],
            returns=None,
            type_comment=None,
            type_params=[],
        )
        doctor_module = compile(
            ast.fix_missing_locations(
                ast.Module(body=[doctor_function], type_ignores=[])
            ),
            "workflow-doctor-block",
            "exec",
        )
        cls.doctor_code = next(
            value for value in doctor_module.co_consts if isinstance(value, CodeType)
        )

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="skill-pilot-ci-test-")
        self.addCleanup(temporary.cleanup)
        self.evidence = Path(temporary.name)

    def helper(self):
        namespace = {
            "subprocess": subprocess,
            "json": json,
            "evidence": self.evidence,
        }
        return FunctionType(self.helper_code, namespace)

    def doctor(self, payload, returncode=0):
        fake = SimpleNamespace(
            returncode=returncode, stdout=payload, stderr="private diagnostic"
        )
        namespace = {
            "subprocess": SimpleNamespace(
                PIPE=subprocess.PIPE, run=lambda *args, **kwargs: fake
            ),
            "sys": sys,
            "json": json,
            "evidence": self.evidence,
        }
        with redirect_stdout(io.StringIO()) as output:
            FunctionType(self.doctor_code, namespace)()
        return output.getvalue()

    def test_success_records_exit_and_output(self):
        with redirect_stdout(io.StringIO()):
            self.helper()(
                "success", [sys.executable, "-c", 'print("synthetic success")']
            )
        record = json.loads(
            (self.evidence / "success.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["returncode"], 0)
        self.assertIn("synthetic success", record["output"])

    def test_failure_is_recorded_before_exit_propagates(self):
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            self.helper()("failure", [sys.executable, "-c", "raise SystemExit(7)"])
        self.assertEqual(stopped.exception.code, 7)
        record = json.loads(
            (self.evidence / "failure.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["returncode"], 7)

    def test_doctor_artifact_and_console_exclude_private_fields(self):
        versions = {
            "cli_version": "3.0.0-rc.1",
            "manifest_versions": {"plugin.json": "2.1.1"},
            "manifest_versions_consistent": True,
            "cli_matches_manifests": False,
        }
        output = self.doctor(
            json.dumps({**versions, "warehouses_discovered": ["private-path"]})
        )
        artifact = (self.evidence / "doctor.json").read_text(encoding="utf-8")
        self.assertEqual(json.loads(artifact), versions)
        self.assertNotIn("private", artifact + output)

    def test_failed_doctor_records_only_returncode(self):
        with self.assertRaises(SystemExit) as stopped:
            self.doctor("private raw output", 9)
        self.assertEqual(stopped.exception.code, 9)
        self.assertEqual(
            json.loads((self.evidence / "doctor.json").read_text(encoding="utf-8")),
            {"returncode": 9},
        )

    def test_malformed_doctor_output_fails_closed(self):
        with self.assertRaises(json.JSONDecodeError):
            self.doctor("malformed synthetic output")

    def test_inconsistent_manifest_versions_fail(self):
        with self.assertRaises(AssertionError):
            self.doctor(
                json.dumps(
                    {
                        "cli_version": "rc",
                        "manifest_versions": {},
                        "manifest_versions_consistent": False,
                        "cli_matches_manifests": False,
                    }
                )
            )

    def test_multi_file_compilation_cannot_mask_first_file_failure(self):
        command = self.syntax_step.strip()
        self.assertTrue(command.startswith("run: python -m py_compile "))
        self.assertEqual(len(command.splitlines()), 1)
        arguments = shlex.split(command.removeprefix("run: "))
        self.assertEqual(arguments[:3], ["python", "-m", "py_compile"])
        bad = self.evidence / "bad.py"
        good = self.evidence / "good.py"
        bad.write_text("def broken(:\n", encoding="utf-8")
        good.write_text("value = 1\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, *arguments[1:3], str(bad), str(good)],
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
