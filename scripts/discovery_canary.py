#!/usr/bin/env python3
"""Disposable hosted-token integration probe; never merge or use for releases.

The production publisher requires main and a genuine newer release. This probe
exercises its Git/PR/check-dispatch transport with a test-only text change and
isolated base/head refs instead. It does not execute release_pr.main or alter pins.
"""
import json
import os
from pathlib import Path
import subprocess

from release import REPOSITORY, run

BASE = "test/discovery-canary-20261029"
HEAD = BASE + "-update"
SOURCE = "14233c12d8d23205c78886a5daf17f074eb7bc87"
MARKER = "docs/DISCOVERY_CANARY.txt"


def main():
    if (os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
            or os.environ.get("GITHUB_REF") != "refs/heads/" + BASE
            or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"):
        raise ValueError("canary requires its exact disposable repository/ref/event")
    pin_before = Path("release.json").read_bytes()
    if run("git", "ls-remote", "--heads", "origin", "refs/heads/" + HEAD):
        raise ValueError("canary head already exists; do not overwrite or retry blindly")
    baseline = json.loads(run("gh", "api", "repos/" + REPOSITORY + "/branches/main"))
    if baseline["commit"]["sha"] != SOURCE or baseline["protected"] is not True:
        raise ValueError("main moved or protection absent; reconcile before testing")
    run("git", "checkout", "-b", HEAD)
    Path(MARKER).write_text(
        "Disposable Actions-token integration fixture. DO NOT MERGE.\n"
        "No upstream version, source commit or packaging revision changed.\n"
        "The PR targets a disposable branch, not main.\n"
    )
    run("git", "add", "--", MARKER)
    run("git", "-c", "user.name=github-actions[bot]", "-c",
        "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit", "-m", "test: disposable discovery transport canary")
    head_sha = run("git", "rev-parse", "HEAD")
    changed = run("git", "diff", "--name-only", "HEAD^", "HEAD").splitlines()
    if changed != [MARKER] or Path("release.json").read_bytes() != pin_before:
        raise ValueError("canary changed more than its marker")
    run("git", "push", "origin", "HEAD:refs/heads/" + HEAD)
    body = (
        "Disposable integration canary for #4. **DO NOT MERGE.**\n\n"
        "This PR exercises real GITHUB_TOKEN branch publication, PR creation, "
        "readback and explicit checks.yml dispatch. It targets a disposable base "
        "branch and changes only a text fixture. Production release pins and "
        "publisher source are unchanged; release_pr.main and discovery's "
        "new-release path are not executed by this canary.\n\n"
        "No image build, publication, promotion, schedule activation or "
        "deployment is performed. Close this PR and remove both canary refs "
        "after retaining the scoped evidence."
    )
    url = run("gh", "pr", "create", "--repo", REPOSITORY, "--base", BASE,
              "--head", HEAD, "--draft", "--title",
              "[CANARY - DO NOT MERGE] Discovery token and checks transport",
              "--body", body)
    actual = json.loads(run("gh", "pr", "view", url, "--repo", REPOSITORY,
                            "--json", "state,headRefName,baseRefName,headRefOid,isDraft,author"))
    if (actual["state"] != "OPEN" or actual["headRefName"] != HEAD
            or actual["baseRefName"] != BASE or actual["headRefOid"] != head_sha
            or actual["isDraft"] is not True
            or actual["author"]["login"] not in ("github-actions[bot]", "app/github-actions")):
        raise ValueError("unexpected canary PR readback: " + json.dumps(actual))
    subprocess.run(["gh", "workflow", "run", "checks.yml", "--repo", REPOSITORY,
                    "--ref", HEAD], check=True)
    record = {"source_main": SOURCE, "canary_base": BASE, "canary_head": HEAD,
              "head_sha": head_sha, "pr_url": url, "pr_readback": actual,
              "checks_dispatch_requested": True,
              "checks_passed": "not established here; verify the matching run separately",
              "scope": "transport canary, not a real release update"}
    rendered = json.dumps(record, indent=2) + "\n"
    Path("canary-record.json").write_text(rendered)
    print(rendered)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
        summary.write("## Disposable discovery transport canary\n\n```json\n" + rendered + "```\n")


if __name__ == "__main__":
    main()
