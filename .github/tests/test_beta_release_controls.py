"""Guard the beta publisher against accidental stable or untested releases."""

from __future__ import annotations

import pathlib
import unittest

WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / "workflows" / "ci.yml"


class BetaReleaseWorkflowTests(unittest.TestCase):
    def test_release_needs_green_matrix_and_explicit_branch_marker(self) -> None:
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read\n", content)
        self.assertIn("\n  beta_release:\n", content)
        release_job = content.split("\n  beta_release:\n", 1)[1]
        self.assertIn("needs: test", release_job)
        self.assertIn("github.event_name == 'push'", release_job)
        self.assertIn("github.ref == 'refs/heads/feat/v4-development'", release_job)
        self.assertIn(
            "contains(github.event.head_commit.message, '[beta-release]')",
            release_job,
        )
        self.assertIn("contents: write", release_job)
        self.assertIn("persist-credentials: false", release_job)
        self.assertIn("--prerelease", release_job)
        self.assertIn('--target "$GITHUB_SHA"', release_job)
        self.assertIn('tag="v4.0.0-beta.1"', release_job)
        self.assertNotIn("--force", release_job)
        self.assertNotIn("git push", release_job)

    def test_no_unreviewed_external_release_action(self) -> None:
        job = WORKFLOW.read_text(encoding="utf-8").split("\n  beta_release:\n", 1)[1]
        self.assertNotIn("softprops/action-gh-release", job)
        self.assertIn("gh release create", job)
        self.assertIn("docs/v4/BETA_RELEASE_NOTES.md", job)


if __name__ == "__main__":
    unittest.main()
