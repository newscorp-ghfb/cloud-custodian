import base64
from typing import List

from jira import JIRA

from c7n_mailer import utils


class JiraDelivery:
    def __init__(self, config, session, logger):
        self.config = config
        self.session = session
        self.logger = logger
        self.url = config.get("jira_url")
        self.key = config.get("jira_project_key", "custodian_jira_project")
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

    def jira_handler(self, sqs_message, jira_messages):
        issue_list = []
        for prd, resources in jira_messages.items():
            # TODO take tag:jira_project into count
            jira_project = resources[0].get(self.key)
            if not jira_project:
                self.logger.info(
                    f"Jira: Skip {len(resources)} resources due to "
                    f"jira_project value not found for product {prd}"
                )
                continue
            self.logger.info(
                "Sending account:%s policy:%s %s:%d jira:%s to %s"
                % (
                    sqs_message.get("account", ""),
                    sqs_message["policy"]["name"],
                    sqs_message["policy"]["resource"],
                    len(resources),
                    sqs_message["action"].get("jira_template", "slack_default"),
                    # TODO have the self.key support jmespath
                    jira_project,
                )
            )
            issue_list.append(
                {
                    "project": jira_project,
                    "summary": utils.get_message_subject(sqs_message),
                    "description": utils.get_rendered_jinja(
                        jira_project,
                        sqs_message,
                        resources,
                        self.logger,
                        "jira_template",
                        "slack_default",
                        self.config["templates_folders"],
                    ),
                    "issuetype": {"name": "Task"},
                    "priority": {"name": "Medium"},
                }
            )
            issue_list[-1].update(**self.custom_fields.get(jira_project, {}))

        if issue_list:
            issueIds = self.create_issues(issue_list)
            if issueIds:
                # NOTE borrow 'action' object to carry the delivery result
                sqs_message["action"]["delivered_jira"] = issueIds
                sqs_message["action"]["delivered_jira_url"] = self.url

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
