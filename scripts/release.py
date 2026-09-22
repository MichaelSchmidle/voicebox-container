#!/usr/bin/env python3
"""Small fail-closed release policy and CLI; Python standard library only."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

UPSTREAM = "jamiepine/voicebox"
REPOSITORY = "MichaelSchmidle/voicebox-container"
VERSION = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
SHA = r"[0-9a-f]{40}"
DIGEST = r"sha256:[0-9a-f]{64}"
ANNOTATION = "io.voicebox.packaging."


def match(pattern, value, name):
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError(f"invalid {name}")
    return value


def version(value):
    return tuple(map(int, match(VERSION, value, "stable version").split(".")))


def digest(value):
    return match(DIGEST, value, "sha256 digest")


def sha(value):
    return match(SHA, value, "commit SHA")


def validate_lock(lock):
    if not isinstance(lock, dict) or set(lock) != {"repository", "version", "commit", "packaging_revision"} or lock.get("repository") != UPSTREAM:
        raise ValueError("release.json requires exactly repository, version, commit, packaging_revision and must pin jamiepine/voicebox")
    version(lock.get("version"))
    sha(lock.get("commit"))
    rev = lock.get("packaging_revision")
    if type(rev) is not int or not 1 <= rev <= 999999:
        raise ValueError("packaging_revision must be an integer in 1..999999")
    return lock


def evidence(url, repo=REPOSITORY):
    return match(r"https://github\.com/" + re.escape(repo) + r"/(?:issues|pull)/[1-9][0-9]*(?:#issuecomment-[1-9][0-9]*)?", url, "evidence URL (repository issue/PR or comment)")


def verify_evidence(url, image_digest, packaging_sha):
    evidence(url)
    digest(image_digest)
    sha(packaging_sha)
    suffix = url.split(REPOSITORY + "/", 1)[1]
    if "#issuecomment-" in suffix:
        comment = suffix.split("#issuecomment-", 1)[1]
        endpoint = "issues/comments/" + comment
    else:
        endpoint = "issues/" + suffix.split("/")[1]
    record = get_json(f"https://api.github.com/repos/{REPOSITORY}/{endpoint}")
    body = record.get("body") or ""
    if record.get("html_url") != url or image_digest not in body or packaging_sha not in body:
        raise ValueError("Evidence must exist and explicitly identify candidate digest and packaging commit")


def select_release(items, current):
    eligible = []
    for item in items:
        # Missing flags are not assumed safe.
        if item.get("draft") is not False or item.get("prerelease") is not False:
            continue
        tag = item.get("tag_name", "")
        if not isinstance(tag, str):
            continue
        text = tag[1:] if tag.startswith("v") else tag
        try:
            parsed = version(text)
        except ValueError:
            continue
        if parsed > version(current):
            eligible.append((parsed, text, tag))
    if not eligible:
        return None
    _, text, tag = max(eligible)
    return text, tag


def get_json(url, headers=None):
    """Only retry idempotent reads, bounded backoff, never hide auth failures."""
    headers = dict(headers or {})
    headers.setdefault("User-Agent", "voicebox-container-release")
    if url.startswith("https://api.github.com/"):
        headers.setdefault("Accept", "application/vnd.github+json")
        headers.setdefault("X-GitHub-Api-Version", "2022-11-28")
        if os.environ.get("GH_TOKEN"):
            headers.setdefault("Authorization", "Bearer " + os.environ["GH_TOKEN"])
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
        except (URLError, TimeoutError):
            if attempt == 3:
                raise
        time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def releases():
    result = []
    for page in range(1, 101):
        items = get_json(f"https://api.github.com/repos/{UPSTREAM}/releases?per_page=100&page={page}")
        if not isinstance(items, list):
            raise ValueError("unexpected releases API response")
        result.extend(items)
        if len(items) < 100:
            return result
    raise ValueError("release pagination exceeds safety limit; refusing partial discovery")


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def output(**values):
    lines = []
    for key, value in values.items():
        if "\n" in str(value) or "\r" in str(value):
            raise ValueError("multiline output not allowed")
        lines.append(f"{key}={value}\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.writelines(lines)
    print("".join(lines), end="")


def discover():
    path = Path("release.json")
    lock = validate_lock(json.loads(path.read_text()))
    selected = select_release(releases(), lock["version"])
    if selected is None:
        output(changed="false")
        return
    new_version, tag = selected
    # Commits endpoint dereferences lightweight and annotated tags to a commit.
    commit = get_json(f"https://api.github.com/repos/{UPSTREAM}/commits/{quote(tag, safe='')}")
    lock.update(version=new_version, commit=sha(commit["sha"]), packaging_revision=1)
    path.write_text(json.dumps(lock, indent=2) + "\n")
    output(changed="true", version=new_version, branch=f"automation/upstream-v{new_version}")


def identity(lock):
    validate_lock(lock)
    return f"v{lock['version']}-r{lock['packaging_revision']}"


def candidate_tag(lock, packaging_sha):
    return "candidate-" + identity(lock) + "-" + sha(packaging_sha)


def promotion_plan(lock, candidate_digest, version_digest, latest, stable_tags=()):
    validate_lock(lock)
    digest(candidate_digest)
    current = (version(lock["version"]), lock["packaging_revision"])
    for tag in stable_tags:
        parsed = re.fullmatch(r"v(" + VERSION + r")-r([1-9][0-9]*)", tag)
        if parsed and (version(parsed[1]), int(parsed[5])) > current:
            raise ValueError("a newer immutable stable tag already exists; rollback denied")
    if version_digest is not None and digest(version_digest) != candidate_digest:
        raise ValueError("immutable version tag already points at another digest")
    if latest:
        old_lock, old_digest = latest
        validate_lock(old_lock)
        digest(old_digest)
        current = (version(lock["version"]), lock["packaging_revision"])
        old = (version(old_lock["version"]), old_lock["packaging_revision"])
        if current < old or (current == old and candidate_digest != old_digest):
            raise ValueError("rollback or same-version replacement denied")
    return ([identity(lock)] if version_digest is None else []) + (["latest"] if latest is None or latest[1] != candidate_digest else [])


class Registry:
    """GHCR manifest API. Only a real manifest 404 means a tag is absent."""
    def __init__(self, repo=REPOSITORY, write=False):
        if repo != REPOSITORY:
            raise ValueError("unexpected registry repository")
        self.name = repo.lower()
        auth = base64.b64encode((os.environ["GITHUB_ACTOR"] + ":" + os.environ["GH_TOKEN"]).encode()).decode()
        query = urlencode({"service": "ghcr.io", "scope": f"repository:{self.name}:" + ("pull,push" if write else "pull")})
        self.token = get_json("https://ghcr.io/token?" + query, {"Authorization": "Basic " + auth})["token"]

    def request(self, ref, method="GET", body=None, media=None):
        match(r"(?:sha256:[0-9a-f]{64}|[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127})", ref, "manifest reference")
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"}
        if media:
            headers["Content-Type"] = media
        try:
            with urlopen(Request(f"https://ghcr.io/v2/{self.name}/manifests/{ref}", data=body, headers=headers, method=method), timeout=60) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code == 404 and method == "GET":
                return None
            raise
        if method != "GET":
            return None
        computed = "sha256:" + hashlib.sha256(raw).hexdigest()
        if ref.startswith("sha256:") and computed != ref:
            raise ValueError("registry returned incorrect digest")
        return computed, json.loads(raw), raw

    def tags(self):
        tags = []
        last = ""
        for _ in range(1000):
            page = get_json(f"https://ghcr.io/v2/{self.name}/tags/list?" + urlencode({"n": 100, "last": last}), {"Authorization": "Bearer " + self.token})
            items = page.get("tags") or []
            if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
                raise ValueError("invalid registry tag list")
            tags.extend(items)
            if len(items) < 100:
                return tags
            if items[-1] == last:
                raise ValueError("registry tag pagination did not advance")
            last = items[-1]
        raise ValueError("registry tag pagination exceeded limit")

    def promote(self, ref, manifest):
        # Reuse exact bytes. No rebuild or index rewrite that changes the digest.
        expected, document, raw = manifest
        self.request(ref, "PUT", raw, document["mediaType"])
        actual = self.request(ref)
        if actual is None or actual[0] != expected:
            raise ValueError("tag write failed read-back verification")


def manifest_lock(document):
    a = document.get("annotations", {})
    return validate_lock({"repository": a.get(ANNOTATION + "upstream"), "version": a.get(ANNOTATION + "version"), "commit": a.get(ANNOTATION + "source"), "packaging_revision": int(a.get(ANNOTATION + "revision", "0"))})


def verify_attestation(image, image_digest, packaging_sha):
    return run("gh", "attestation", "verify", "oci://" + image + "@" + digest(image_digest),
               "--repo", REPOSITORY,
               "--signer-workflow", REPOSITORY + "/.github/workflows/candidate.yml",
               "--signer-digest", sha(packaging_sha), "--source-digest", sha(packaging_sha),
               "--source-ref", "refs/heads/main", "--deny-self-hosted-runners",
               "--cert-oidc-issuer", "https://token.actions.githubusercontent.com",
               "--predicate-type", "https://slsa.dev/provenance/v1", "--format", "json")


def trusted_actor():
    actor = match(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", os.environ["GITHUB_ACTOR"], "actor")
    data = get_json(f"https://api.github.com/repos/{REPOSITORY}/collaborators/{actor}/permission")
    if data.get("permission") not in ("admin", "maintain", "write"):
        raise ValueError("release dispatch requires a trusted maintainer")


def require_environment():
    env = get_json(f"https://api.github.com/repos/{REPOSITORY}/environments/release")
    rules = env.get("protection_rules", [])
    if not any(rule.get("type") == "required_reviewers" and rule.get("prevent_self_review") is True and rule.get("reviewers") for rule in rules):
        raise ValueError("release environment must require independent review and prevent self-review")
    run_id = match(r"[1-9][0-9]*", os.environ["GITHUB_RUN_ID"], "run ID")
    reviews = get_json(f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run_id}/approvals")
    if not isinstance(reviews, list):
        raise ValueError("unexpected workflow approval history")
    for review in reviews:
        reviewer = review.get("user", {}).get("login", "")
        if (review.get("state") == "approved" and reviewer != os.environ["GITHUB_ACTOR"]
                and any(item.get("id") == env.get("id") for item in review.get("environments", []))):
            match(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", reviewer, "reviewer")
            permission = get_json(f"https://api.github.com/repos/{REPOSITORY}/collaborators/{reviewer}/permission")
            if permission.get("permission") in ("admin", "maintain", "write"):
                return
    raise ValueError("this run must have an independent trusted maintainer's release-environment approval")


def main_only():
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY or os.environ.get("GITHUB_REF") != "refs/heads/main" or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise ValueError("publishing requires workflow_dispatch on canonical repository main")
    trusted_actor()


def prepare():
    main_only()
    packaging_sha = sha(os.environ["PACKAGING_COMMIT"])
    if packaging_sha != os.environ.get("GITHUB_SHA") or packaging_sha != run("git", "rev-parse", "HEAD"):
        raise ValueError("candidate must use the exact reviewed dispatch main commit")
    lock = validate_lock(json.loads(Path("release.json").read_text()))
    # Request creation-capable scope even for the absence check on a new package.
    reg = Registry(write=True)
    tag = candidate_tag(lock, packaging_sha)
    if reg.request(tag) is not None:
        raise ValueError("candidate tag already exists: never overwrite; inspect existing run or bump packaging revision")
    output(image="ghcr.io/" + REPOSITORY.lower(), tag=tag, version=lock["version"], source=lock["commit"], revision=lock["packaging_revision"])


def promote():
    main_only()
    require_environment()
    image_digest = digest(os.environ["CANDIDATE_DIGEST"])
    packaging_sha = sha(os.environ["PACKAGING_COMMIT"])
    evidence_url = evidence(os.environ["GPU_EVIDENCE_URL"])
    if os.environ.get("GPU_VALIDATED") != "true":
        raise ValueError("explicit GPU validation attestation is required")
    if os.environ.get("SECURITY_REVIEWED") != "true":
        raise ValueError("explicit security review attestation is required")
    security_url = evidence(os.environ["SECURITY_EVIDENCE_URL"])
    verify_evidence(evidence_url, image_digest, packaging_sha)
    verify_evidence(security_url, image_digest, packaging_sha)
    # Require reviewed ancestry. Do not execute old repository code.
    run("git", "merge-base", "--is-ancestor", packaging_sha, "HEAD")
    lock = validate_lock(json.loads(run("git", "show", packaging_sha + ":release.json")))
    reg = Registry(write=True)
    image = "ghcr.io/" + REPOSITORY.lower()
    candidate = reg.request(candidate_tag(lock, packaging_sha))
    if candidate is None or candidate[0] != image_digest:
        raise ValueError("candidate tag does not match supplied digest")
    annotations = candidate[1].get("annotations", {})
    if manifest_lock(candidate[1]) != lock or annotations.get(ANNOTATION + "commit") != packaging_sha:
        raise ValueError("candidate metadata does not match reviewed pins")
    verification = verify_attestation(image, image_digest, packaging_sha)
    Path("promotion-verification.json").write_text(verification + "\n")
    immutable = reg.request(identity(lock))
    latest = reg.request("latest")
    latest_state = (manifest_lock(latest[1]), latest[0]) if latest else None
    plan = promotion_plan(lock, image_digest, immutable[0] if immutable else None, latest_state, reg.tags())
    # Both workflows share one non-cancelling concurrency group. Recheck before writing.
    if reg.request(identity(lock)) != immutable or reg.request("latest") != latest:
        raise ValueError("registry state changed during promotion; rerun after investigation")
    for tag in plan:
        reg.promote(tag, candidate)
    record = {"image": image, "digest": image_digest, "release": lock, "packaging_commit": packaging_sha, "evidence": evidence_url, "security_evidence": security_url, "security_reviewed": True, "attested_by": os.environ["GITHUB_ACTOR"], "run_url": f"https://github.com/{REPOSITORY}/actions/runs/{os.environ['GITHUB_RUN_ID']}", "tags_changed": plan}
    Path("promotion-record.json").write_text(json.dumps(record, indent=2) + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(f"Promoted `{image}@{image_digest}` as `{identity(lock)}` / `latest`.\n\nGPU evidence: {evidence_url}\n")
    print(json.dumps(record, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["discover", "prepare", "promote", "validate"])
    command = parser.parse_args().command
    if command == "validate":
        validate_lock(json.loads(Path("release.json").read_text()))
    else:
        {"discover": discover, "prepare": prepare, "promote": promote}[command]()


if __name__ == "__main__":
    main()
