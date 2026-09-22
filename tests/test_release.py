import importlib.util
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from pathlib import Path

spec = importlib.util.spec_from_file_location("release", Path(__file__).resolve().parents[1] / "scripts/release.py")
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64
LOCK = {"repository": "jamiepine/voicebox", "version": "1.2.3", "commit": SHA, "packaging_revision": 1}

class ReleaseTests(unittest.TestCase):
    def test_canonical_versions(self):
        self.assertEqual(r.version("10.2.3"), (10, 2, 3))
        for value in ["v1.2.3", "01.2.3", "1.2", "1.2.3-rc1", "1.2.3+foo", "1.2.3\n", "$(id)", "1.2.3;id", "", None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                r.version(value)

    def test_strict_pins(self):
        self.assertEqual(r.validate_lock(LOCK), LOCK)
        for key, value in [("repository", "attacker/repo"), ("commit", "a"*39), ("commit", "A"*40), ("commit", SHA+"\n"), ("packaging_revision", True), ("packaging_revision", 0), ("packaging_revision", "1")]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                r.validate_lock(dict(LOCK, **{key: value}))
        with self.assertRaises(ValueError):
            r.validate_lock({})

    def test_digest_and_evidence(self):
        self.assertEqual(r.digest(DIGEST), DIGEST)
        for value in [DIGEST+"\n", "sha256:"+"B"*64, "latest", "--help", "sha256:"+"b"*63, "sha512:"+"b"*64]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                r.digest(value)
        repo = "MichaelSchmidle/voicebox-container"
        url = f"https://github.com/{repo}/issues/3#issuecomment-123"
        self.assertEqual(r.evidence(url, repo), url)
        for value in ["http://github.com/"+repo+"/issues/1", "https://evil.example/test", "https://github.com.evil.example/"+repo+"/issues/1", "https://github.com/other/repo/issues/1", "https://github.com/"+repo+"/issues/1?x=y", url+"\n"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                r.evidence(value, repo)

    def test_discover_only_new_stable(self):
        releases = [{"tag_name": t, "draft": d, "prerelease": p} for t,d,p in [("v1.2.2", False, False), ("v1.2.4", False, False), ("v9.0.0", True, False), ("v8.0.0", False, True), ("v7.0.0-rc1", False, False), ("v01.9.0", False, False), ("6.0.0;id", False, False)]]
        self.assertEqual(r.select_release(releases, "1.2.3"), ("1.2.4", "v1.2.4"))
        self.assertIsNone(r.select_release(releases, "2.0.0"))
        self.assertIsNone(r.select_release([], "1.2.3"))

    def test_promotion_order_and_immutable_retry(self):
        self.assertEqual(r.promotion_plan(LOCK, DIGEST, None, None), ["v1.2.3-r1", "latest"])
        self.assertEqual(r.promotion_plan(LOCK, DIGEST, DIGEST, None), ["latest"])
        self.assertEqual(r.promotion_plan(LOCK, DIGEST, DIGEST, (LOCK, DIGEST)), [])
        with self.assertRaises(ValueError):
            r.promotion_plan(LOCK, DIGEST, "sha256:"+"c"*64, None)
        for old in [dict(LOCK, version="2.0.0"), dict(LOCK, packaging_revision=2)]:
            with self.assertRaises(ValueError):
                r.promotion_plan(LOCK, DIGEST, None, (old, "sha256:"+"c"*64))
        with self.assertRaises(ValueError):
            r.promotion_plan(LOCK, DIGEST, None, (LOCK, "sha256:"+"c"*64))

    def test_api_retries_transient_only(self):
        errors = [HTTPError("https://api.github.com/x", 503, "busy", {}, None), HTTPError("https://api.github.com/x", 429, "busy", {}, None)]
        with patch.object(r, "urlopen", side_effect=errors+[DummyResponse(b'{"ok":true}')]) as call, patch.object(r.time, "sleep"):
            self.assertEqual(r.get_json("https://api.github.com/x"), {"ok": True})
            self.assertEqual(call.call_count, 3)
        for code in [401, 403, 404]:
            with patch.object(r, "urlopen", side_effect=HTTPError("x", code, "no", {}, None)) as call:
                with self.assertRaises(HTTPError):
                    r.get_json("https://api.github.com/x")
                self.assertEqual(call.call_count, 1)

    def test_pagination(self):
        page = [{"tag_name": "v1.0.0"}] * 100
        with patch.object(r, "get_json", side_effect=[page, [{"tag_name": "v2.0.0"}]]) as call:
            self.assertEqual(len(r.releases()), 101)
            self.assertIn("page=2", call.call_args.args[0])

class GuardTests(unittest.TestCase):
    def test_highwater_blocks_partial_promotion_rollback(self):
        with self.assertRaises(ValueError):
            r.promotion_plan(LOCK, DIGEST, None, None, ["v1.2.4-r1"])
        with self.assertRaises(ValueError):
            r.promotion_plan(LOCK, DIGEST, None, None, ["v1.2.3-r2"])
        self.assertEqual(r.promotion_plan(LOCK, DIGEST, None, None, ["v1.0.0-r1", "candidate-v9.0.0-r1-"+SHA]), ["v1.2.3-r1", "latest"])

    def test_retries_exhausted(self):
        with patch.object(r, "urlopen", side_effect=HTTPError("x", 503, "no", {}, None)) as call, patch.object(r.time, "sleep") as sleep:
            with self.assertRaises(HTTPError): r.get_json("https://api.github.com/x")
            self.assertEqual(call.call_count, 4)
            self.assertEqual(sleep.call_count, 3)

    def test_annotation_schema_fail_closed(self):
        with self.assertRaises(ValueError): r.manifest_lock({})
        data = {r.ANNOTATION+k: str(v) for k,v in {"upstream": LOCK["repository"], "version": LOCK["version"], "source": SHA, "revision": 1}.items()}
        self.assertEqual(r.manifest_lock({"annotations": data}), LOCK)

    def test_require_independent_review(self):
        for response in [{}, {"protection_rules": [{"type": "required_reviewers", "prevent_self_review": False, "reviewers": [1]}]}, {"protection_rules": [{"type": "required_reviewers", "prevent_self_review": True, "reviewers": []}]}]:
            with patch.object(r, "get_json", return_value=response), self.assertRaises(ValueError): r.require_environment()
        configured = {"id": 7, "protection_rules": [{"type": "required_reviewers", "prevent_self_review": True, "reviewers": [{"type":"User"}]}]}
        approval = {"state": "approved", "environments": [{"id": 7}], "user": {"login": "reviewer"}}
        with patch.dict(r.os.environ, {"GITHUB_RUN_ID":"123", "GITHUB_ACTOR":"maintainer"}), patch.object(r, "get_json", side_effect=[configured, [approval], {"permission":"write"}]):
            r.require_environment()
        for history in [[], [dict(approval, state="rejected")], [dict(approval, user={"login":"maintainer"})], [dict(approval, environments=[{"id":8}])]]:
            with patch.dict(r.os.environ, {"GITHUB_RUN_ID":"123", "GITHUB_ACTOR":"maintainer"}), patch.object(r, "get_json", side_effect=[configured, history]), self.assertRaises(ValueError):
                r.require_environment()

    def test_permission_and_event_guards(self):
        env = {"GITHUB_ACTOR": "maintainer", "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REPOSITORY": r.REPOSITORY}
        with patch.dict(r.os.environ, env, clear=True), patch.object(r, "get_json", return_value={"permission":"write"}): r.main_only()
        for key,value in [("GITHUB_REF", "refs/heads/evil"), ("GITHUB_EVENT_NAME", "pull_request_target"), ("GITHUB_REPOSITORY", "evil/fork")]:
            with patch.dict(r.os.environ, dict(env, **{key:value}), clear=True), patch.object(r, "get_json") as api, self.assertRaises(ValueError): r.main_only()
            api.assert_not_called()
        for permission in ["read", "triage", "none"]:
            with patch.dict(r.os.environ, env, clear=True), patch.object(r, "get_json", return_value={"permission":permission}), self.assertRaises(ValueError): r.main_only()

    def test_evidence_must_exist_and_bind_digest_and_commit(self):
        url = f"https://github.com/{r.REPOSITORY}/issues/1#issuecomment-2"
        record = {"html_url":url, "body":f"Validated {DIGEST} built from {SHA}; CUDA and synthesis passed."}
        with patch.object(r, "get_json", return_value=record): r.verify_evidence(url, DIGEST, SHA)
        for invalid in [dict(record, body="looks good"), dict(record, html_url=url.replace("issues/1", "issues/9"))]:
            with patch.object(r, "get_json", return_value=invalid), self.assertRaises(ValueError): r.verify_evidence(url, DIGEST, SHA)

    def test_attestation_policy_uses_exact_identity(self):
        with patch.object(r, "run", return_value="[]") as run:
            r.verify_attestation("ghcr.io/"+r.REPOSITORY.lower(), DIGEST, SHA)
            args = run.call_args.args
            self.assertEqual(args[args.index("--source-digest")+1], SHA)
            self.assertEqual(args[args.index("--signer-digest")+1], SHA)
            self.assertEqual(args[args.index("--source-ref")+1], "refs/heads/main")
            self.assertIn("--deny-self-hosted-runners", args)
            self.assertEqual(args[args.index("--signer-workflow")+1], r.REPOSITORY+"/.github/workflows/candidate.yml")

    def test_manifest_404_only_means_absent(self):
        registry = object.__new__(r.Registry)
        registry.name, registry.token = r.REPOSITORY.lower(), "test-token"
        for code in [401, 403, 429, 500]:
            with patch.object(r, "urlopen", side_effect=HTTPError("x", code, "no", {}, None)), self.assertRaises(HTTPError): registry.request("latest")
        with patch.object(r, "urlopen", side_effect=HTTPError("x", 404, "no", {}, None)):
            self.assertIsNone(registry.request("latest"))
            with self.assertRaises(HTTPError): registry.request("latest", "PUT", b"{}", "application/json")

    def test_digest_bytes_and_readback(self):
        registry = object.__new__(r.Registry)
        registry.name, registry.token = r.REPOSITORY.lower(), "test-token"
        raw = b'{"mediaType":"application/vnd.oci.image.index.v1+json","manifests":[]}'
        computed = "sha256:" + r.hashlib.sha256(raw).hexdigest()
        with patch.object(r, "urlopen", return_value=DummyResponse(raw)):
            result = registry.request(computed)
            self.assertEqual(result, (computed,json.loads(raw),raw))
            with self.assertRaises(ValueError): registry.request(DIGEST)
        with patch.object(registry, "request", side_effect=[None, result]) as request:
            registry.promote("latest",result)
            self.assertEqual(request.call_args_list[0].args, ("latest", "PUT", raw, json.loads(raw)["mediaType"]))
        with patch.object(registry, "request", side_effect=[None, None]), self.assertRaises(ValueError): registry.promote("latest",result)


class DummyResponse:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return self.body

if __name__ == "__main__":
    unittest.main()
