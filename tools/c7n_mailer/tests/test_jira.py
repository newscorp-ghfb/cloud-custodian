# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

from collections import namedtuple
import unittest
from unittest.mock import MagicMock, patch

from c7n_mailer.jira_delivery import JiraDelivery


logger = MagicMock()
MockIssue = namedtuple("MockIssue", ["key"])


JIRA_CONFIG = {
    "jira_url": "https://jira.example.com/rest/api/2/",
    "jira_basic_auth": "user:token",
    "jira_project_key": "PROJ",
    "templates_folders": [],
}


class JiraDeliveryTest(unittest.TestCase):
    def test_init_sets_url(self):
        jira = JiraDelivery(JIRA_CONFIG, logger)
        self.assertEqual(jira.url, "https://jira.example.com/rest/api/2/")

    def test_init_sets_project_key(self):
        jira = JiraDelivery(JIRA_CONFIG, logger)
        self.assertEqual(jira.jp_key.expression, "PROJ")

    def test_init_default_project_key(self):
        config = JIRA_CONFIG.copy()
        del config["jira_project_key"]
        jira = JiraDelivery(config, logger)
        self.assertEqual(jira.jp_key.expression, "custodian_jira_project")

    def test_init_empty_auth_raises(self):
        config = JIRA_CONFIG.copy()
        config["jira_basic_auth"] = ""
        with self.assertRaises(ValueError) as ctx:
            JiraDelivery(config, logger)
        self.assertIn("does not have two values", str(ctx.exception))

    def test_init_jira_raises_on_missing_colon(self):
        config = JIRA_CONFIG.copy()
        config["jira_basic_auth"] = "invalid-no-colon"
        with self.assertRaises(ValueError) as ctx:
            JiraDelivery(config, logger)
        self.assertIn("does not have two values", str(ctx.exception))

    def test_init_jira_raises_on_too_many_parts(self):
        config = JIRA_CONFIG.copy()
        config["jira_basic_auth"] = "user:pass:extra"
        with self.assertRaises(ValueError) as ctx:
            JiraDelivery(config, logger)
        self.assertIn("does not have two values", str(ctx.exception))

    def test_process_skips_group_without_project(self):
        jira = JiraDelivery(JIRA_CONFIG, logger)
        message = {
            "account": "test-account",
            "policy": {"name": "test-policy", "resource": "ec2"},
            "action": {"jira": {}},
        }
        jira.process(message, {"default": [{"id": "res-1"}]})
        logger.info.assert_called()
        self.assertNotIn("delivered_jira", message["action"])

    def test_process_creates_issue_with_project(self):
        jira = JiraDelivery(JIRA_CONFIG, logger)
        message = {
            "account": "test-account",
            "policy": {"name": "test-policy", "resource": "ec2"},
            "action": {"jira": {"project": "MYPROJ"}},
        }
        with patch.object(
            jira, "create_issues", return_value=["PROJ-123"]
        ) as mock_create:
            jira.process(message, {"default": [{"id": "res-1"}]})
        mock_create.assert_called_once()
        self.assertEqual(message["action"]["delivered_jira"], ["PROJ-123"])
        self.assertEqual(message["action"]["delivered_jira_url"], jira.url)

    def test_process_skips_non_default_group_without_project(self):
        jira = JiraDelivery(JIRA_CONFIG, logger)
        message = {
            "account": "test-account",
            "policy": {"name": "test-policy", "resource": "ec2"},
            "action": {"jira": {}},
        }
        jira.process(message, {"other-group": [{"id": "res-1"}]})
        logger.info.assert_called()
        self.assertNotIn("delivered_jira", message["action"])

    def test_create_issues_returns_empty_on_empty_list(self):
        jira = JiraDelivery(JIRA_CONFIG, logger)
        result = jira.create_issues([])
        self.assertIsNone(result)

    def test_create_issues_logs_success_and_error(self):
        test_logger = MagicMock()
        jira = JiraDelivery(JIRA_CONFIG, test_logger)
        issue_results = [
            {"status": "Success", "issue": MockIssue(key="PROJ-1")},
            {"status": "Success", "issue": MockIssue(key="PROJ-2")},
            {"error": "Failed to create PROJ-3"},
        ]
        with patch.object(jira, "_create_issues", return_value=issue_results):
            result = jira.create_issues([{}, {}])
        self.assertEqual(result, ["PROJ-1", "PROJ-2"])
        test_logger.info.assert_called()
        test_logger.error.assert_called()


if __name__ == "__main__":
    unittest.main()
