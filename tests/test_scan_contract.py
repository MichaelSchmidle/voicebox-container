"""Regression for the live ARM64-only registry index scan failure."""
from pathlib import Path
import unittest


class ScanContractTests(unittest.TestCase):
    def test_registry_scan_has_explicit_platform_and_version(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/candidate.yml').read_text()
        scan = workflow.split('uses: aquasecurity/trivy-action@', 1)[1].split('      - name:', 1)[0]
        self.assertIn('version: v0.74.0', scan)
        self.assertIn('TRIVY_PLATFORM: linux/arm64', scan)
        self.assertIn('TRIVY_IMAGE_SRC: remote', scan)
        self.assertIn('ignore-unfixed: false', scan)
        self.assertIn('image-ref: ${{ steps.release.outputs.image }}@${{ steps.build.outputs.digest }}', scan)


if __name__ == '__main__':
    unittest.main()
