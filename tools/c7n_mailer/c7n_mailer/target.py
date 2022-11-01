# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

import traceback

from .email_delivery import EmailDelivery
from .sns_delivery import SnsDelivery
from .utils import decrypt, get_provider, Providers


class MessageTargetMixin(object):
    def on_aws(self):
        return get_provider(self.config) == Providers.AWS

    def on_gcp(self):
        return get_provider(self.config) == Providers.GCP

    def handle_targets(self, message, sent_timestamp):
        email_delivery = EmailDelivery(self.config, self.session, self.logger)

        # this section calls Jira api to create tickets
        if any(e == "jira" for e in message.get("action", ()).get("to")):
            from .jira_delivery import JiraDelivery

            if "jira_url" not in self.config:
                self.logger.warning("jira_url not found in mailer config")
            else:
                try:
                    jira_delivery = JiraDelivery(self.config, self.session, self.logger)
                    groupedResources = email_delivery.get_grouped_resources(message, "jira")
                    jira_delivery.process(message, jira_messages=groupedResources)
                except Exception as e:
                    self.logger.error(f"Failed to create Jira issue: {str(e)}")
                    message["action"]["delivered_jira_error"] = "Failed to create Jira issue"

        # this section sends email to ServiceNow to create tickets
        if any(e == "servicenow" for e in message.get("action", ()).get("to")):
            servicenow_address = self.config.get("servicenow_address")
            if not servicenow_address:
                self.logger.warning("servicenow_address not found in mailer config")
            else:
                groupedPrdMsg = email_delivery.get_group_email_messages_map(message)
                for mimetext_msg in groupedPrdMsg.values():
                    email_delivery.send_c7n_email(message, [servicenow_address], mimetext_msg)

        # get the map of email_to_addresses to mimetext messages (with resources baked in)
        # and send any emails (to SES or SMTP) if there are email addresses found
        # NOTE Azure process has its own implementation atm
        if self.on_aws() or self.on_gcp():
            groupedAddrMsg = email_delivery.get_to_addrs_email_messages_map(message)
            for email_to_addrs, mimetext_msg in groupedAddrMsg.items():
                email_delivery.send_c7n_email(message, list(email_to_addrs), mimetext_msg)

        # this sections gets the map of sns_to_addresses to rendered_jinja messages
        # (with resources baked in) and delivers the message to each sns topic
        if self.on_aws():
            sns_delivery = SnsDelivery(self.config, self.session, self.logger)
            sns_message_packages = sns_delivery.get_sns_message_packages(message)
            sns_delivery.deliver_sns_messages(sns_message_packages, message)

        # this section sends a notification to the resource owner via Slack
        if any(
            e.startswith("slack") or e.startswith("https://hooks.slack.com/")
            for e in message.get("action", {}).get("to", [])
            + message.get("action", {}).get("owner_absent_contact", [])
        ):
            from .slack_delivery import SlackDelivery

            slack_token: str = self.config.get("slack_token")
            if slack_token and not slack_token.startswith("xoxb-"):
                slack_token = decrypt(self.config, self.logger, self.session, "slack_token")
                self.config["slack_token"] = slack_token

            slack_delivery = SlackDelivery(self.config, self.logger, email_delivery)
            slack_messages = slack_delivery.get_to_addrs_slack_messages_map(message)
            try:
                slack_delivery.slack_handler(message, slack_messages)
            except Exception:
                traceback.print_exc()
                pass

        # this section gets the map of metrics to send to datadog and delivers it
        if any(e.startswith("datadog") for e in message.get("action", ()).get("to", [])):
            from .datadog_delivery import DataDogDelivery

            datadog_delivery = DataDogDelivery(self.config, self.session, self.logger)
            datadog_message_packages = datadog_delivery.get_datadog_message_packages(message)

            try:
                datadog_delivery.deliver_datadog_messages(datadog_message_packages, message)
            except Exception:
                traceback.print_exc()
                pass

        # this section sends the full event to a Splunk HTTP Event Collector (HEC)
        if any(e.startswith("splunkhec://") for e in message.get("action", ()).get("to", [])):
            from .splunk_delivery import SplunkHecDelivery

            splunk_delivery = SplunkHecDelivery(self.config, self.session, self.logger)
            splunk_messages = splunk_delivery.get_splunk_payloads(message, sent_timestamp)

            try:
                splunk_delivery.deliver_splunk_messages(splunk_messages)
            except Exception:
                traceback.print_exc()
                pass
