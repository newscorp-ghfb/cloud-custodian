from typing import List

import jmespath
import requests
import json

from c7n_mailer import utils


headers = {
  "Accept": "application/json",
  "Content-Type": "application/json"
}

class JiraDelivery:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.url = config.get("jira_url")
        self.jp_key = jmespath.compile(config.get("jira_project_key", "custodian_jira_project"))
        self.custom_fields = config.get("jira_custom_fields", {})
        self.init_jira()

    def init_jira(self):
        auth_txt = self.config.get("jira_basic_auth").split(":")
        if len(auth_txt) != 2:
            raise ValueError("basic auth is wrong, does not have two elements")
        self.basic_auth = HTTPBasicAuth(basic_auth[0], basic_auth[1])
 
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
                    "issuetype": {"name": jira_conf.get("issuetype", "Story")},
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
        res = self._create_issues(issue_list)
        success = [i["issue"].key for i in res if i["status"] == "Success"]
        error = [i["error"] for i in res if i["error"]]
        if success:
            self.logger.info(f"Created issues {success}")
        if error:
            self.logger.error(f"Failed to create issues {error}")
        return success

    def _create_issues(
        self, field_list: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Bulk create new issues and return an issue Resource for each successfully created issue.

        See `create_issue` documentation for field information.

        Args:
            field_list (List[Dict[str, Any]]): a list of dicts each containing field names and the values to use. Each dict is an individual issue to create and is subject to its minimum requirements.
            prefetch (bool): True reloads the created issue Resource so all of its data is present in the value returned (Default: ``True``)

        Returns:
            List[Dict[str, Any]]
        """
        data: dict[str, list] = {"issueUpdates": []}
        for field_dict in field_list:
            issue_data: dict[str, Any] = _field_worker(field_dict)
            p = issue_data["fields"]["project"]

            project_id = None
            if isinstance(p, str | int):
                project_id = self.project(str(p)).id
                issue_data["fields"]["project"] = {"id": project_id}

            p = issue_data["fields"]["issuetype"]
            if isinstance(p, int):
                issue_data["fields"]["issuetype"] = {"id": p}
            elif isinstance(p, str):
                issue_data["fields"]["issuetype"] = {
                    "id": self.issue_type_by_name(
                        str(p), project=str(project_id) if project_id else None
                    ).id
                }

            data["issueUpdates"].append(issue_data)

        url = self.url + "issue/bulk"
        response = requests.request(
           "POST",
           url,
           data=payload,
           headers=headers,
           auth=self.basic_auth
        )

        raw_issue_json = json.loads(response.text), sort_keys=True, indent=4, separators=(",", ": "))

        raw_issue_json = r.json()
        # Catching case where none of the issues has been created.
        # See https://github.com/pycontribs/jira/issues/350
        issue_list = []
        errors = {}
        for error in raw_issue_json["errors"]:
            errors[error["failedElementNumber"]] = error["elementErrors"]["errors"]
        for index, fields in enumerate(field_list):
            if index in errors:
                issue_list.append(
                    {
                        "status": "Error",
                        "error": errors[index],
                        "issue": None,
                        "input_fields": fields,
                    }
                )
            else:
                issue = raw_issue_json["issues"].pop(0)
                issue_list.append(
                    {
                        "status": "Success",
                        "issue": issue,
                        "error": None,
                        "input_fields": fields,
                    }
                )
        return issue_list
