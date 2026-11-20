"""Guard the explicit, host-independent stable-release workflow."""

import pathlib
import unittest

WORKFLOW = (
    pathlib.Path(__file__).resolve().parents[1] / "workflows" / "stable-release.yml"
)


class StableReleaseWorkflowTests(unittest.TestCase):
    def test_release_is_manual_main_only_and_explicitly_confirmed(self) -> None:
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", content)
        self.assertIn("github.ref == 'refs/heads/main'", content)
        self.assertIn("inputs.confirm == 'publish-v4.0.0'", content)
        self.assertIn("contents: write", content)
        self.assertIn("persist-credentials: false", content)
        self.assertIn("eval/v4_release_qualification.py", content)
        self.assertIn('tag="v4.0.0"', content)
        self.assertIn('gh release create "$tag"', content)
        self.assertNotIn("--force", content)
        self.assertNotIn("git push", content)

    def test_release_refuses_existing_tag_or_release(self) -> None:
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('gh release view "$tag"', content)
        self.assertIn('git rev-parse --verify -q "refs/tags/$tag"', content)
        self.assertIn("Refusing to overwrite", content)
        self.assertIn("Refusing to reuse", content)


if __name__ == "__main__":
    unittest.main()
