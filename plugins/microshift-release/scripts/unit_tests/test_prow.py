"""Unit tests for lib.prow module."""

import argparse
import io
import json
import os
import subprocess
import unittest
from unittest import mock

import prow_testing
from lib import prow


class TestParseVersion(unittest.TestCase):

    def test_valid_xyz(self):
        result = prow.parse_version("4.21.3")
        self.assertEqual(result["version"], "4.21.3")
        self.assertEqual(result["minor"], "4.21")
        self.assertEqual(result["branch"], "release-4.21")
        self.assertEqual(result["pr_title"], "[release-4.21] Release Testing 4.21.3")

    def test_valid_rc(self):
        result = prow.parse_version("4.22.0-rc.1")
        self.assertEqual(result["version"], "4.22.0-rc.1")
        self.assertEqual(result["minor"], "4.22")
        self.assertEqual(result["branch"], "release-4.22")

    def test_valid_ec(self):
        result = prow.parse_version("4.22.0-ec.5")
        self.assertEqual(result["version"], "4.22.0-ec.5")

    def test_tilde_normalization(self):
        result = prow.parse_version("4.22.0~ec.5")
        self.assertEqual(result["version"], "4.22.0-ec.5")

    def test_rejects_old_version(self):
        with self.assertRaises(ValueError) as ctx:
            prow.parse_version("4.18.3")
        self.assertIn("Jenkins", str(ctx.exception))

    def test_rejects_nightly(self):
        with self.assertRaises(ValueError) as ctx:
            prow.parse_version("4.21.0-nightly-2025-01-01")
        self.assertIn("nightly", str(ctx.exception))

    def test_rejects_invalid_format(self):
        with self.assertRaises(ValueError) as ctx:
            prow.parse_version("4.21")
        self.assertIn("Invalid version format", str(ctx.exception))

    def test_rejects_bare_minor(self):
        with self.assertRaises(ValueError):
            prow.parse_version("4.21")

    def test_rejects_major_below_4(self):
        with self.assertRaises(ValueError):
            prow.parse_version("3.22.0")

    def test_valid_5x_xyz(self):
        result = prow.parse_version("5.0.0")
        self.assertEqual(result["version"], "5.0.0")
        self.assertEqual(result["minor"], "5.0")
        self.assertEqual(result["branch"], "release-5.0")
        self.assertEqual(result["pr_title"], "[release-5.0] Release Testing 5.0.0")

    def test_valid_5x_rc(self):
        result = prow.parse_version("5.0.0-rc.0")
        self.assertEqual(result["version"], "5.0.0-rc.0")
        self.assertEqual(result["minor"], "5.0")
        self.assertEqual(result["release_type"], "RC")

    def test_valid_5x_ec(self):
        result = prow.parse_version("5.1.0-ec.3")
        self.assertEqual(result["version"], "5.1.0-ec.3")
        self.assertEqual(result["minor"], "5.1")
        self.assertEqual(result["release_type"], "EC")


class TestCiJobs(unittest.TestCase):

    def test_421_jobs(self):
        jobs = prow.ci_jobs("4.21")
        self.assertEqual(len(jobs), 4)
        self.assertIn("e2e-aws-tests-bootc-release", jobs)
        self.assertIn("e2e-aws-tests-bootc-release-arm", jobs)
        self.assertIn("e2e-aws-tests-release", jobs)
        self.assertIn("e2e-aws-tests-release-arm", jobs)

    def test_422_jobs(self):
        jobs = prow.ci_jobs("4.22")
        self.assertEqual(len(jobs), 6)
        self.assertIn("e2e-aws-tests-bootc-release-el9", jobs)
        self.assertIn("e2e-aws-tests-bootc-release-el10", jobs)
        self.assertIn("e2e-aws-tests-bootc-release-arm-el9", jobs)
        self.assertIn("e2e-aws-tests-bootc-release-arm-el10", jobs)

    def test_future_version_uses_422_jobs(self):
        jobs = prow.ci_jobs("4.25")
        self.assertEqual(len(jobs), 6)

    def test_5x_uses_422_jobs(self):
        jobs = prow.ci_jobs("5.0")
        self.assertEqual(len(jobs), 6)
        self.assertIn("e2e-aws-tests-bootc-release-el9", jobs)


class TestMatchCiJobs(unittest.TestCase):

    def test_all_matched_422(self):
        gcs_jobs = [
            "pull-ci-openshift-microshift-release-4.22-e2e-aws-tests-release",
            "pull-ci-openshift-microshift-release-4.22-e2e-aws-tests-release-arm",
            "pull-ci-openshift-microshift-release-4.22-e2e-aws-tests-bootc-release-el9",
            "pull-ci-openshift-microshift-release-4.22-e2e-aws-tests-bootc-release-el10",
            "pull-ci-openshift-microshift-release-4.22-e2e-aws-tests-bootc-release-arm-el9",
            "pull-ci-openshift-microshift-release-4.22-e2e-aws-tests-bootc-release-arm-el10",
        ]
        matched = prow.match_ci_jobs(gcs_jobs, "4.22")
        for short in prow.ci_jobs("4.22"):
            self.assertIsNotNone(matched[short], f"{short} should be matched")

    def test_all_matched_421(self):
        gcs_jobs = [
            "pull-ci-openshift-microshift-release-4.21-e2e-aws-tests-bootc-release",
            "pull-ci-openshift-microshift-release-4.21-e2e-aws-tests-bootc-release-arm",
            "pull-ci-openshift-microshift-release-4.21-e2e-aws-tests-release",
            "pull-ci-openshift-microshift-release-4.21-e2e-aws-tests-release-arm",
        ]
        matched = prow.match_ci_jobs(gcs_jobs, "4.21")
        for short in prow.ci_jobs("4.21"):
            self.assertIsNotNone(matched[short], f"{short} should be matched")

    def test_partial_match(self):
        gcs_jobs = [
            "pull-ci-openshift-microshift-release-4.22-e2e-aws-tests-release",
        ]
        matched = prow.match_ci_jobs(gcs_jobs, "4.22")
        self.assertIsNotNone(matched["e2e-aws-tests-release"])
        self.assertIsNone(matched["e2e-aws-tests-release-arm"])

    def test_empty_list(self):
        matched = prow.match_ci_jobs([], "4.22")
        for short in prow.ci_jobs("4.22"):
            self.assertIsNone(matched[short])

    def test_no_false_positives(self):
        gcs_jobs = [
            "pull-ci-openshift-microshift-release-4.22-e2e-aws-tests-release-arm",
        ]
        matched = prow.match_ci_jobs(gcs_jobs, "4.22")
        self.assertIsNone(matched["e2e-aws-tests-release"])
        self.assertIsNotNone(matched["e2e-aws-tests-release-arm"])


class TestGetPrCheckStatuses(unittest.TestCase):

    @mock.patch("lib.prow.subprocess.run")
    def test_maps_check_names_to_short_names(self, mock_run):
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout='[{"name":"pull-ci-openshift-microshift-release-4.22-e2e-aws-tests-release","state":"IN_PROGRESS"},'
                   '{"name":"pull-ci-openshift-microshift-release-4.22-e2e-aws-tests-release-arm","state":"COMPLETED"}]',
        )
        result = prow.get_pr_check_statuses(1234, "4.22")
        self.assertEqual(result["e2e-aws-tests-release"], "IN_PROGRESS")
        self.assertEqual(result["e2e-aws-tests-release-arm"], "COMPLETED")

    @mock.patch("lib.prow.subprocess.run")
    def test_returns_empty_on_failure(self, mock_run):
        mock_run.return_value = mock.Mock(returncode=1, stderr="error")
        result = prow.get_pr_check_statuses(1234, "4.22")
        self.assertEqual(result, {})

    @mock.patch("lib.prow.subprocess.run")
    def test_ignores_unrelated_checks(self, mock_run):
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout='[{"name":"tide","state":"COMPLETED"},{"name":"some-other-check","state":"IN_PROGRESS"}]',
        )
        result = prow.get_pr_check_statuses(1234, "4.22")
        self.assertEqual(result, {})


class TestFetchAllJobStatusesOverride(unittest.TestCase):
    """Verify that GitHub check statuses override stale GCS results."""

    @mock.patch("lib.prow.get_pr_check_statuses")
    @mock.patch("lib.prow.get_latest_build")
    def test_in_progress_overrides_stale_success(self, mock_build, mock_checks):
        mock_build.return_value = {
            "job": "pull-ci-openshift-microshift-release-4.22-e2e-aws-tests-release",
            "status": "SUCCESS",
            "url": "https://old-url",
            "build_id": "100",
        }
        mock_checks.return_value = {
            "e2e-aws-tests-release": "IN_PROGRESS",
        }

        matched = {"e2e-aws-tests-release": "full-job-name"}
        for short in prow.ci_jobs("4.22"):
            if short not in matched:
                matched[short] = None

        statuses = prow.fetch_all_job_statuses(1234, matched, "4.22")
        release_status = next(s for s in statuses if s["short_name"] == "e2e-aws-tests-release")
        self.assertEqual(release_status["status"], "PENDING")

    @mock.patch("lib.prow.get_pr_check_statuses")
    @mock.patch("lib.prow.get_latest_build")
    def test_completed_does_not_override(self, mock_build, mock_checks):
        mock_build.return_value = {
            "job": "pull-ci-openshift-microshift-release-4.22-e2e-aws-tests-release",
            "status": "SUCCESS",
            "url": "https://url",
            "build_id": "100",
        }
        mock_checks.return_value = {
            "e2e-aws-tests-release": "COMPLETED",
        }

        matched = {"e2e-aws-tests-release": "full-job-name"}
        for short in prow.ci_jobs("4.22"):
            if short not in matched:
                matched[short] = None

        statuses = prow.fetch_all_job_statuses(1234, matched, "4.22")
        release_status = next(s for s in statuses if s["short_name"] == "e2e-aws-tests-release")
        self.assertEqual(release_status["status"], "SUCCESS")


class TestCheckAwsAuth(unittest.TestCase):

    def _run(self, env, sts_rc=0, binary="/mock/bin/aws", timeout=False):
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(prow_testing.shutil, "which",
                               return_value=binary) as mock_which, \
             mock.patch.object(prow_testing.subprocess, "run",
                               return_value=mock.Mock(returncode=sts_rc,
                                                      stderr="")) as mock_run:
            if timeout:
                mock_run.side_effect = subprocess.TimeoutExpired(
                    "aws", 30, output="mock-timeout-stdout",
                    stderr="mock-timeout-stderr",
                )
            result = prow_testing._check_aws_auth()
        return result, mock_which, mock_run

    def _assert_sts_called(self, mock_which, mock_run):
        mock_which.assert_called_once_with("aws")
        mock_run.assert_called_once_with(
            ["aws", "sts", "get-caller-identity"],
            capture_output=True, text=True, timeout=30,
        )

    def test_no_credentials_fails(self):
        result, mock_which, mock_run = self._run({}, binary=None)
        self.assertEqual(result["check"], "aws_auth")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("No AWS credentials", result["reason"])
        mock_which.assert_not_called()
        mock_run.assert_not_called()

    def test_incomplete_key_pairs_fail(self):
        for env in ({"AWS_ACCESS_KEY_ID": "mock-access-key"},
                    {"AWS_SECRET_ACCESS_KEY": "mock-secret-key"}):
            with self.subTest(env_keys=list(env)):
                result, mock_which, mock_run = self._run(env)
                self.assertEqual(result["status"], "FAIL")
                self.assertIn("No AWS credentials", result["reason"])
                mock_which.assert_not_called()
                mock_run.assert_not_called()

    def test_profile_passes(self):
        result, mock_which, mock_run = self._run({"AWS_PROFILE": "mock-profile"})
        self.assertEqual(result["check"], "aws_auth")
        self.assertEqual(result["status"], "PASS")
        self._assert_sts_called(mock_which, mock_run)

    def test_complete_key_pair_passes(self):
        result, mock_which, mock_run = self._run({
            "AWS_ACCESS_KEY_ID": "mock-access-key",
            "AWS_SECRET_ACCESS_KEY": "mock-secret-key",
        })
        self.assertEqual(result["status"], "PASS")
        self._assert_sts_called(mock_which, mock_run)

    def test_profile_with_access_key_without_secret_fails(self):
        result, mock_which, mock_run = self._run({
            "AWS_PROFILE": "mock-profile",
            "AWS_ACCESS_KEY_ID": "mock-access-key",
        }, sts_rc=255)
        self.assertEqual(result["check"], "aws_auth")
        self.assertEqual(result["status"], "FAIL")
        self._assert_sts_called(mock_which, mock_run)

    def test_profile_with_secret_without_access_key_passes(self):
        result, mock_which, mock_run = self._run({
            "AWS_PROFILE": "mock-profile",
            "AWS_SECRET_ACCESS_KEY": "mock-secret-key",
        })
        self.assertEqual(result["check"], "aws_auth")
        self.assertEqual(result["status"], "PASS")
        self._assert_sts_called(mock_which, mock_run)

    def test_missing_cli_fails(self):
        result, mock_which, mock_run = self._run(
            {"AWS_PROFILE": "mock-profile"}, binary=None,
        )
        self.assertEqual(result["check"], "aws_auth")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("aws CLI not found", result["reason"])
        mock_which.assert_called_once_with("aws")
        mock_run.assert_not_called()

    def test_expired_credentials_fail(self):
        result, mock_which, mock_run = self._run(
            {"AWS_PROFILE": "mock-profile"}, sts_rc=255,
        )
        self.assertEqual(result["status"], "FAIL")
        self._assert_sts_called(mock_which, mock_run)

    def test_timeout_fails_without_diagnostics(self):
        result, mock_which, mock_run = self._run(
            {"AWS_PROFILE": "mock-profile"}, timeout=True,
        )
        self.assertEqual(result, {
            "check": "aws_auth",
            "status": "FAIL",
            "reason": "AWS authentication check timed out after 30 seconds.",
        })
        self._assert_sts_called(mock_which, mock_run)


class TestCheckCliAuth(unittest.TestCase):

    checks = (
        ("gh", "gh_auth", "FAIL", ["gh", "auth", "status"]),
        ("gsutil", "gsutil_auth", "WARN",
         ["gsutil", "ls", "gs://test-platform-results-public/"]),
    )

    def _run(self, binary, command, missing=False, returncode=0, timeout=False):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(prow_testing.shutil, "which",
                               return_value=None if missing else "/mock/bin/tool") as mock_which, \
             mock.patch.object(prow_testing.subprocess, "run",
                               return_value=mock.Mock(returncode=returncode,
                                                      stderr="mock failure")) as mock_run:
            if timeout:
                mock_run.side_effect = subprocess.TimeoutExpired(
                    command, 30, output="mock-timeout-stdout",
                    stderr="mock-timeout-stderr",
                )
            result = getattr(prow_testing, f"_check_{binary}_auth")()
        mock_which.assert_called_once_with(binary)
        if missing:
            mock_run.assert_not_called()
        else:
            mock_run.assert_called_once_with(
                command, capture_output=True, text=True, timeout=30,
            )
        return result

    def test_success_passes(self):
        for binary, check, _, command in self.checks:
            with self.subTest(binary=binary):
                result = self._run(binary, command)
                self.assertEqual(result["check"], check)
                self.assertEqual(result["status"], "PASS")

    def test_missing_cli(self):
        for binary, check, failure_status, command in self.checks:
            with self.subTest(binary=binary):
                result = self._run(binary, command, missing=True)
                self.assertEqual(result["check"], check)
                self.assertEqual(result["status"], failure_status)
                self.assertIn("not found", result["reason"])

    def test_nonzero_result(self):
        for binary, check, failure_status, command in self.checks:
            with self.subTest(binary=binary):
                result = self._run(binary, command, returncode=1)
                self.assertEqual(result["check"], check)
                self.assertEqual(result["status"], failure_status)

    def test_timeout_without_diagnostics(self):
        for binary, check, failure_status, command in self.checks:
            with self.subTest(binary=binary):
                result = self._run(binary, command, timeout=True)
                self.assertEqual(result["check"], check)
                self.assertEqual(result["status"], failure_status)
                self.assertIn("timed out after 30 seconds", result["reason"])
                self.assertEqual(set(result), {"check", "status", "reason"})
                self.assertNotIn("mock-timeout", json.dumps(result))


class TestPreflightAuthTimeouts(unittest.TestCase):

    def _run_timeout(self, binary, check_status, overall_status, exit_code=None):
        def run(command, **kwargs):
            if command[0] == binary:
                raise subprocess.TimeoutExpired(
                    command, 30, output="mock-timeout-stdout",
                    stderr="mock-timeout-stderr",
                )
            return mock.Mock(returncode=0, stderr="")

        output = io.StringIO()
        with mock.patch.dict(os.environ, {"AWS_PROFILE": "mock-profile"}, clear=True), \
             mock.patch.object(prow_testing.shutil, "which",
                               return_value="/mock/bin/tool") as mock_which, \
             mock.patch.object(prow_testing.subprocess, "run", side_effect=run) as mock_run, \
             mock.patch.object(prow_testing, "_check_s3_rpms", return_value={
                 "check": "s3_rpms", "status": "PASS", "reason": "mock RPMs present",
             }), \
             mock.patch("sys.stdout", output):
            args = argparse.Namespace(version="4.22.1")
            if exit_code is None:
                prow_testing.cmd_preflight(args)
            else:
                with self.assertRaises(SystemExit) as raised:
                    prow_testing.cmd_preflight(args)
                self.assertEqual(raised.exception.code, exit_code)

        result = json.loads(output.getvalue())
        self.assertEqual(result["action"], "preflight")
        self.assertEqual(result["version"], "4.22.1")
        self.assertEqual(result["status"], overall_status)
        expected_checks = {
            "gh_auth": "PASS", "aws_auth": "PASS",
            "s3_rpms": "PASS", "gsutil_auth": "PASS",
        }
        expected_checks[f"{binary}_auth"] = check_status
        self.assertEqual(
            {check["check"]: check["status"] for check in result["checks"]},
            expected_checks,
        )
        timeout_check = next(check for check in result["checks"]
                             if check["check"] == f"{binary}_auth")
        self.assertIn("timed out after 30 seconds", timeout_check["reason"])
        self.assertEqual(set(timeout_check), {"check", "status", "reason"})
        self.assertNotIn("mock-timeout", output.getvalue())
        self.assertEqual(mock_which.call_args_list,
                         [mock.call("gh"), mock.call("aws"), mock.call("gsutil")])
        self.assertEqual(mock_run.call_args_list, [
            mock.call(["gh", "auth", "status"],
                      capture_output=True, text=True, timeout=30),
            mock.call(["aws", "sts", "get-caller-identity"],
                      capture_output=True, text=True, timeout=30),
            mock.call(["gsutil", "ls", "gs://test-platform-results-public/"],
                      capture_output=True, text=True, timeout=30),
        ])

    def test_gh_timeout_emits_json_and_exits_one(self):
        self._run_timeout("gh", "FAIL", "fail", exit_code=1)

    def test_aws_timeout_emits_json_and_exits_one(self):
        self._run_timeout("aws", "FAIL", "fail", exit_code=1)

    def test_gsutil_timeout_emits_json_without_exit(self):
        self._run_timeout("gsutil", "WARN", "warn")


if __name__ == "__main__":
    unittest.main()
