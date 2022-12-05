from typing import List

import jmespath
from jira import JIRA

from c7n_mailer import utils


class JiraDelivery:
    def __init__(self, config, session, logger):
        self.config = config
        self.session = session
        self.logger = logger
        self.url = config.get("jira_url")
        self.jp_key = jmespath.compile(config.get("jira_project_key", "custodian_jira_project"))
        self.custom_fields = config.get("jira_custom_fields", {})
        self.init_jira()

    def init_jira(self):
        auth_txt = self.config.get("jira_basic_auth")
        # NOTE check length to skip calls to KMS while testing with plain text
        if len(auth_txt) > 100:
            self.logger.info("Calling KMS to decrypt the jira_basic_auth")
            auth_txt = utils.kms_decrypt(self.config, self.logger, self.session, "jira_basic_auth")
            self.config["jira_basic_auth"] = auth_txt
        basic_auth = tuple(auth_txt.split(":"))
        self.client = JIRA(server=self.url, basic_auth=basic_auth)

    def process(self, message, jira_messages):
        issue_list = []
        for group_name, resources in jira_messages.items():
            jira_conf = message["action"].get("jira", {})
            # FIXME should search all resources in the group until found
            jira_project = self.jp_key.search(resources[0]) or jira_conf.get("project")
            # NOTE override jira_project for 'default' group, which should be more desirable
            if group_name == "default":
                jira_project = jira_conf.get("project")
            if not jira_project:
                self.logger.info(
                    f"Jira: Skip {len(resources)} resources due to "
                    f"jira_project value not found for this group {group_name}"
                )
                continue
            self.logger.info(
                "Sending account:%s policy:%s %s:%d jira:%s to %s"
                % (
                    message.get("account", ""),
                    message["policy"]["name"],
                    message["policy"]["resource"],
                    len(resources),
                    message["action"].get("jira_template", "slack_default"),
                    jira_project,
                )
            )
            issue_list.append(
                {
                    "project": jira_project,
                    "summary": utils.get_message_subject(message),
                    "description": utils.get_rendered_jinja(
                        jira_project,
                        message,
                        resources,
                        self.logger,
                        "jira_template",
                        "slack_default",
                        self.config["templates_folders"],
                    ),
                    "issuetype": {"name": jira_conf.get("issuetype", "Task")},
                    "priority": {"name": jira_conf.get("priority", "Medium")},
                }
            )
            custom_fields = self.custom_fields.get(jira_project, {})
            issue_list[-1].update(**custom_fields)
            # NOTE remove all `cannot-be-set` attributes
            for k in [k for k, v in custom_fields.items() if v == "cannot-be-set"]:
                issue_list[-1].pop(k)

        if issue_list:
            issueIds = self.create_issues(issue_list)
            if issueIds:
                # NOTE borrow 'action' object to carry the delivery result
                message["action"]["delivered_jira"] = issueIds
                message["action"]["delivered_jira_url"] = self.url

    def create_issues(self, issue_list) -> List:
        if not issue_list:
            return
        res = self.client.create_issues(field_list=issue_list)
        success = [i["issue"].key for i in res if i["status"] == "Success"]
        error = [i["error"] for i in res if i["error"]]
        if success:
            self.logger.info(f"Created issues {success}")
        if error:
            self.logger.error(f"Failed to create issues {error}")
        return success
