#!/usr/bin/env python3
"""Publish a generated pin-only update as a PR, then explicitly dispatch checks."""
import json
import os
from pathlib import Path
import subprocess
from release import REPOSITORY, identity, run, validate_lock


def main():
    lock = validate_lock(json.loads(Path("release.json").read_text()))
    branch = "automation/upstream-v" + lock["version"]
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY or os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("discovery writes require canonical repository main")
    remote = run("git", "ls-remote", "--heads", "origin", "refs/heads/" + branch)
    if not remote:
        run("git", "checkout", "-b", branch)
        run("git", "add", "--", "release.json")
        run("git", "-c", "user.name=github-actions[bot]", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com", "commit", "-m", "Update upstream Voicebox to " + identity(lock))
        # A concurrent creator fails this push instead of overwriting its branch.
        run("git", "push", "origin", "HEAD:refs/heads/" + branch)
    else:
        # Idempotence must not overwrite any maintainer follow-up edits.
        run("git", "fetch", "origin", "refs/heads/" + branch)
        existing = validate_lock(json.loads(run("git", "show", "FETCH_HEAD:release.json")))
        if existing != lock:
            raise ValueError("existing update branch differs; maintainer reconciliation required")
    prs = json.loads(run("gh", "pr", "list", "--repo", REPOSITORY, "--state", "all", "--head", branch, "--json", "number,state,url"))
    if prs:
        if len(prs) != 1 or prs[0]["state"] != "OPEN":
            raise ValueError("update PR already closed; no automatic reopening")
        url = prs[0]["url"]
    else:
        body = ("Automated discovery of a newer stable upstream release. Only release.json changes.\n\n"
                "Review the source SHA, upstream release notes, Docker/dependency locks and packaging compatibility. "
                "This PR does not build, publish, promote or deploy an image.\n\n"
                "Because GITHUB_TOKEN-created PRs do not trigger pull_request workflows, this job explicitly dispatches "
                "the read-only checks workflow against the update branch. A maintainer must confirm that run is green "
                "for the current PR head before merging. Candidate build remains manual after merge.")
        url = run("gh", "pr", "create", "--repo", REPOSITORY, "--base", "main", "--head", branch, "--title", "Update Voicebox to " + lock["version"], "--body", body)
    # Verify external PR creation/read-back before reporting success.
    actual = json.loads(run("gh", "pr", "view", url, "--repo", REPOSITORY, "--json", "state,headRefName,baseRefName"))
    if actual != {"state": "OPEN", "headRefName": branch, "baseRefName": "main"}:
        raise ValueError("unexpected update PR state")
    subprocess.run(["gh", "workflow", "run", "checks.yml", "--repo", REPOSITORY, "--ref", branch], check=True)
    print(url)
    print("Checks requested; verify the dispatched run is green on the PR head before merging.")


if __name__ == "__main__":
    main()
