"""Checks on the probe workflow that encode the platform decisions.

Pull request runs must use ubuntu only. The windows-latest entry exists only in
the dispatch matrix, and every action stays pinned to a full commit SHA. PyYAML
is optional: the test is skipped when it is not installed.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - the CI image may not ship PyYAML
    yaml = None

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "probe-sandbox.yml"
PINNED = re.compile(r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")


@unittest.skipIf(yaml is None, "PyYAML is not installed")
class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    def _triggers(self):
        triggers = self.document.get("on")
        if triggers is None:
            triggers = self.document.get(True)  # PyYAML reads the bare `on` key as True
        return triggers

    def test_workflow_pins_every_action_to_a_commit(self):
        for job in self.document["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    self.assertRegex(step["uses"], PINNED)

    def test_workflow_keeps_read_only_default_permissions(self):
        self.assertEqual(self.document["permissions"], {"contents": "read"})

    def test_workflow_does_not_run_pr_code_with_secrets(self):
        self.assertNotIn("pull_request_target", self._triggers())

    def test_workflow_gates_windows_behind_dispatch_input(self):
        triggers = self._triggers()
        self.assertIn("pull_request", triggers)
        self.assertIs(
            triggers["workflow_dispatch"]["inputs"]["windows"]["default"], False
        )
        plan = self.document["jobs"]["plan"]
        self.assertEqual(plan["outputs"]["matrix"], "${{ steps.plan.outputs.matrix }}")
        build = plan["steps"][0]
        self.assertEqual(build["env"]["DISPATCH"], "${{ github.event_name == 'workflow_dispatch' }}")
        self.assertEqual(build["env"]["WINDOWS"], "${{ inputs.windows }}")
        self.assertIn("windows-latest", build["run"])
        self.assertIn('"os":"linux"', build["run"])
        probe = self.document["jobs"]["probe"]
        self.assertEqual(probe["strategy"]["matrix"], "${{ fromJSON(needs.plan.outputs.matrix) }}")

    def test_workflow_uploads_result_per_os(self):
        steps = self.document["jobs"]["probe"]["steps"]
        upload_steps = [step for step in steps if "upload-artifact@" in step.get("uses", "")]
        self.assertEqual(len(upload_steps), 1)
        with_block = upload_steps[0]["with"]
        self.assertIn("${{ matrix.os }}", with_block["name"])
        self.assertEqual(with_block["path"], "probes/sandbox/out/result.json")


if __name__ == "__main__":
    unittest.main()
