"""PR orchestration tests: all git/GitHub calls mocked, never remote writes."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from test_release import r, LOCK
from test_release_integration import workspace

sys.modules["release"] = r
spec = importlib.util.spec_from_file_location("release_pr", Path(__file__).resolve().parents[1]/"scripts/release_pr.py")
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)
BRANCH = "automation/upstream-v1.2.3"
URL = "https://github.com/"+r.REPOSITORY+"/pull/1"
VALID = json.dumps({"state":"OPEN","headRefName":BRANCH,"baseRefName":"main"})


class PRTests(unittest.TestCase):
    def setUp(self):
        self.env = {"GITHUB_REPOSITORY":r.REPOSITORY,"GITHUB_REF":"refs/heads/main"}

    def test_new_pr_dispatches_checks_and_only_stages_pin(self):
        responses = ["", "", "", "", "", "[]", URL, VALID]
        with workspace(), patch.dict(pr.os.environ,self.env,clear=True), patch.object(pr,"run",side_effect=responses) as run, patch.object(pr.subprocess,"run") as dispatch, patch("builtins.print"):
            pr.main()
            calls = [x.args for x in run.call_args_list]
            self.assertIn(("git","add","--","release.json"),calls)
            self.assertFalse(any("--force" in c for c in calls))
            dispatch.assert_called_once_with(["gh","workflow","run","checks.yml","--repo",r.REPOSITORY,"--ref",BRANCH],check=True)

    def test_existing_open_pr_retry_does_not_push_or_recreate(self):
        responses = ["remote-sha refs/heads/"+BRANCH,"",json.dumps(LOCK),json.dumps([{"state":"OPEN","url":URL}]),VALID]
        with workspace(), patch.dict(pr.os.environ,self.env,clear=True), patch.object(pr,"run",side_effect=responses) as run, patch.object(pr.subprocess,"run") as dispatch, patch("builtins.print"):
            pr.main()
            for call in run.call_args_list:
                self.assertNotIn("push",call.args)
                self.assertNotIn("create",call.args)
            dispatch.assert_called_once()

    def test_existing_branch_mismatch_no_push(self):
        responses = ["remote", "", json.dumps(dict(LOCK,commit="c"*40))]
        with workspace(), patch.dict(pr.os.environ,self.env,clear=True), patch.object(pr,"run",side_effect=responses) as run, patch.object(pr.subprocess,"run") as dispatch:
            with self.assertRaises(ValueError): pr.main()
            self.assertFalse(any("push" in c.args for c in run.call_args_list))
            dispatch.assert_not_called()

    def test_closed_pr_no_reopen(self):
        responses = ["remote","",json.dumps(LOCK),json.dumps([{"state":"CLOSED","url":URL}])]
        with workspace(), patch.dict(pr.os.environ,self.env,clear=True), patch.object(pr,"run",side_effect=responses), patch.object(pr.subprocess,"run") as dispatch:
            with self.assertRaises(ValueError): pr.main()
            dispatch.assert_not_called()

    def test_readback_discrepancy_no_checks_dispatch(self):
        responses = ["remote","",json.dumps(LOCK),json.dumps([{"state":"OPEN","url":URL}]),json.dumps({"state":"CLOSED","headRefName":BRANCH,"baseRefName":"main"})]
        with workspace(), patch.dict(pr.os.environ,self.env,clear=True), patch.object(pr,"run",side_effect=responses), patch.object(pr.subprocess,"run") as dispatch:
            with self.assertRaises(ValueError): pr.main()
            dispatch.assert_not_called()

    def test_noncanonical_repo_no_git_or_api_calls(self):
        with workspace(), patch.dict(pr.os.environ,dict(self.env,GITHUB_REPOSITORY="evil/fork"),clear=True), patch.object(pr,"run") as run:
            with self.assertRaises(ValueError): pr.main()
            run.assert_not_called()


if __name__ == "__main__": unittest.main()
