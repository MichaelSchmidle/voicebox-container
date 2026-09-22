"""No network or publishing: mocked orchestration plus real temporary files."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from test_release import r, LOCK, SHA, DIGEST


@contextlib.contextmanager
def workspace():
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
        os.chdir(directory)
        try:
            Path("release.json").write_text(json.dumps(LOCK))
            yield Path(directory)
        finally:
            os.chdir(previous)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.env = {"GITHUB_REPOSITORY":r.REPOSITORY, "GITHUB_REF":"refs/heads/main", "GITHUB_EVENT_NAME":"workflow_dispatch", "GITHUB_SHA":SHA, "PACKAGING_COMMIT":SHA, "GITHUB_ACTOR":"maintainer", "GITHUB_RUN_ID":"123", "GPU_VALIDATED":"true", "SECURITY_REVIEWED":"true", "SECURITY_EVIDENCE_URL":f"https://github.com/{r.REPOSITORY}/issues/2", "CANDIDATE_DIGEST":DIGEST, "GPU_EVIDENCE_URL":f"https://github.com/{r.REPOSITORY}/issues/1"}

    def test_discovery_updates_only_release_pin(self):
        item = {"tag_name":"v1.3.0", "draft":False, "prerelease":False}
        with workspace(), patch.object(r, "releases", return_value=[item]), patch.object(r, "get_json", return_value={"sha":"c"*40}) as api, patch.object(r, "output") as output:
            r.discover()
            self.assertEqual(json.loads(Path("release.json").read_text()), dict(LOCK, version="1.3.0", commit="c"*40, packaging_revision=1))
            self.assertTrue(api.call_args.args[0].endswith("/commits/v1.3.0"))
            output.assert_called_once_with(changed="true", version="1.3.0", branch="automation/upstream-v1.3.0")
            self.assertEqual([p.name for p in Path('.').iterdir()], ["release.json"])

    def test_no_new_release_no_mutation_or_commit_lookup(self):
        with workspace(), patch.object(r, "releases", return_value=[]), patch.object(r, "get_json") as api, patch.object(r, "output"):
            before = Path("release.json").read_bytes()
            r.discover()
            self.assertEqual(Path("release.json").read_bytes(), before)
            api.assert_not_called()

    def test_invalid_resolved_sha_does_not_write(self):
        with workspace(), patch.object(r, "releases", return_value=[{"tag_name":"v1.3.0", "draft":False, "prerelease":False}]), patch.object(r,"get_json", return_value={"sha":"main;id"}):
            before = Path("release.json").read_bytes()
            with self.assertRaises(ValueError): r.discover()
            self.assertEqual(Path("release.json").read_bytes(), before)

    def test_candidate_uses_dispatch_sha_and_rejects_overwrite(self):
        with workspace(), patch.dict(r.os.environ, self.env, clear=True), patch.object(r, "main_only"), patch.object(r, "run", return_value=SHA), patch.object(r, "Registry") as registry, patch.object(r,"output") as output:
            registry.return_value.request.return_value = None
            r.prepare()
            self.assertEqual(output.call_args.kwargs["tag"], "candidate-v1.2.3-r1-"+SHA)
            registry.return_value.request.return_value = (DIGEST,{},b'{}')
            with self.assertRaises(ValueError): r.prepare()
        with patch.dict(r.os.environ, dict(self.env, PACKAGING_COMMIT="c"*40), clear=True), patch.object(r,"main_only"), patch.object(r,"Registry") as registry:
            with self.assertRaises(ValueError): r.prepare()
            registry.assert_not_called()

    @contextlib.contextmanager
    def promotion(self):
        annotations = {r.ANNOTATION+k: str(v) for k,v in {"upstream":LOCK["repository"], "version":LOCK["version"], "source":SHA, "revision":1, "commit":SHA}.items()}
        candidate = (DIGEST, {"annotations":annotations}, b"manifest bytes")
        with workspace(), patch.dict(r.os.environ, self.env, clear=True), patch.object(r,"main_only"), patch.object(r,"require_environment"), patch.object(r,"verify_evidence") as evidence, patch.object(r,"run", side_effect=["",json.dumps(LOCK)]), patch.object(r,"Registry") as factory, patch.object(r,"verify_attestation", return_value='[{"verified":true}]') as verify, contextlib.redirect_stdout(io.StringIO()):
            reg = factory.return_value
            reg.request.side_effect = [candidate, None, None, None, None]
            reg.tags.return_value = []
            yield reg, verify, evidence, candidate

    def test_promotion_end_to_end_writes_exact_manifest_and_audit(self):
        with self.promotion() as (registry, verify, evidence, candidate):
            r.promote()
            self.assertEqual([call.args for call in registry.promote.call_args_list], [("v1.2.3-r1",candidate), ("latest",candidate)])
            verify.assert_called_once_with("ghcr.io/"+r.REPOSITORY.lower(), DIGEST, SHA)
            self.assertEqual(evidence.call_count, 2)
            evidence.assert_any_call(self.env["GPU_EVIDENCE_URL"], DIGEST, SHA)
            evidence.assert_any_call(self.env["SECURITY_EVIDENCE_URL"], DIGEST, SHA)
            record = json.loads(Path("promotion-record.json").read_text())
            self.assertEqual(record["digest"],DIGEST)
            self.assertEqual(record["evidence"], self.env["GPU_EVIDENCE_URL"])
            self.assertEqual(record["tags_changed"],["v1.2.3-r1","latest"])

    def test_failed_provenance_never_publishes(self):
        with self.promotion() as (registry, verify, _, __):
            verify.side_effect = subprocess.CalledProcessError(1,["gh","attestation","verify"])
            with self.assertRaises(subprocess.CalledProcessError): r.promote()
            registry.promote.assert_not_called()

    def test_digest_mismatch_never_verifies_or_publishes(self):
        with self.promotion() as (registry, verify, _, candidate):
            registry.request.side_effect = [("sha256:"+"c"*64,candidate[1],candidate[2])]
            with self.assertRaises(ValueError): r.promote()
            verify.assert_not_called()
            registry.promote.assert_not_called()

    def test_race_recheck_blocks_write(self):
        with self.promotion() as (registry, _, __, candidate):
            registry.request.side_effect = [candidate, None, None, candidate]
            with self.assertRaisesRegex(ValueError,"state changed"): r.promote()
            registry.promote.assert_not_called()

    def test_failed_gpu_attestation_never_publishes(self):
        with self.promotion() as (registry, verify, evidence, _), patch.dict(r.os.environ, GPU_VALIDATED="false"):
            with self.assertRaises(ValueError): r.promote()
            evidence.assert_not_called()
            verify.assert_not_called()
            registry.promote.assert_not_called()

    def test_security_review_required_before_publish(self):
        for value in ("false", "", "True"):
            with self.promotion() as (registry, verify, evidence, _), patch.dict(r.os.environ, SECURITY_REVIEWED=value):
                with self.assertRaisesRegex(ValueError, "security review"): r.promote()
                verify.assert_not_called()
                registry.promote.assert_not_called()

    def test_invalid_evidence_never_publishes(self):
        with self.promotion() as (registry, verify, evidence, _):
            evidence.side_effect = ValueError("evidence does not bind digest")
            with self.assertRaises(ValueError): r.promote()
            verify.assert_not_called()
            registry.promote.assert_not_called()

    def test_output_rejects_newline_injection(self):
        with self.assertRaises(ValueError): r.output(source=SHA+"\nimage=attacker")

    def test_registry_tags_paginates(self):
        registry = object.__new__(r.Registry)
        registry.name,registry.token = r.REPOSITORY.lower(),"token"
        with patch.object(r,"get_json",side_effect=[{"tags":[f"v1.0.{i}-r1" for i in range(100)]},{"tags":["v2.0.0-r1"]}]):
            self.assertEqual(len(registry.tags()),101)
        with patch.object(r,"get_json",return_value={"tags":None}): self.assertEqual(registry.tags(),[])
        with patch.object(r,"get_json",return_value={"tags":[None]}), self.assertRaises(ValueError): registry.tags()


if __name__ == "__main__": unittest.main()
