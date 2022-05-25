from jira import JIRA

from c7n_mailer import utils

basic_auth = None


class JiraDelivery:
    def __init__(self, config, session, logger):
        self.config = config
        self.session = session
        self.logger = logger
        self.key = config.get("jira_project_key", "custodian_jira_project")
        self.init_jira()

    def init_jira(self):
        if not basic_auth:
            txt = utils.kms_decrypt(self.config, self.logger, self.session, "jira_basic_auth")
            basic_auth = tuple(txt.split(":"))
        self.client = JIRA(server=self.config.get("jira_address"), basic_auth=basic_auth)

    def jira_handler(self, sqs_message, jira_messages):
        issue_list = []
        for prd, resources in jira_messages.items():
            # TODO take tag:jira_project into count
            jira_project = resources[0].get(self.key)
            if not jira_project:
                self.logger.info(
                    f"Skip {len(resources)} resources due to "
                    f"jira_project value not found for product {prd}"
                )
                continue
            self.logger.info(
                "Sending account:%s policy:%s %s:%s jira:%s to %s"
                % (
                    sqs_message.get("account", ""),
                    sqs_message["policy"]["name"],
                    sqs_message["policy"]["resource"],
                    str(len(sqs_message["resources"])),
                    sqs_message["action"].get("jira_template", "slack_default"),
                    # TODO have the self.key support jmespath
                    jira_project,
                )
            )
            issue_list.append(
                # TODO dynamic jira fields, eg priority
                {
                    "project": jira_project,
                    "summary": utils.get_message_subject(sqs_message),
                    "description": utils.get_rendered_jinja(
                        jira_project,
                        sqs_message,
                        resources,
                        self.logger,
                        "jira_template",
                        "slack_template",
                        self.config["templates_folders"],
                    ),
                    "issuetype": {"name": "Task"},
                    "priority": {"name": "Medium"},
                    # Work Type field
                    "customfield_10106": {"value": "BAU"},
                }
            )
        if issue_list:
            self.create_issues(issue_list)

    def create_issues(self, issue_list):
        if not issue_list:
            return
        res = self.client.create_issues(field_list=issue_list)
        success = [i["issue"].key for i in res if i["status"] == "Success"]
        error = [i["error"] for i in res if i["error"]]
        if success:
            self.logger.info(f"Created issues {success}")
        if error:
            self.logger.error(f"Failed to create issues {error}")
