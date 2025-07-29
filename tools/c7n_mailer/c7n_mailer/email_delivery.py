# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
from typing import Dict, List
import jmespath
from itertools import chain

from c7n_mailer.smtp_delivery import SmtpDelivery
import c7n_mailer.azure_mailer.sendgrid_delivery as sendgrid

from .ldap_lookup import LdapLookup
from .utils import (
    decrypt, get_resource_tag_targets, get_provider,
    get_aws_username_from_event, Providers)
from .utils_email import get_mimetext_message, is_email
from .dedup_dynamodb import dedup_check_and_write


class EmailDelivery:

    def __init__(self, config, session, logger):
        self.config = config
        self.logger = logger
        self.session = session
        self.provider = get_provider(self.config)
        if self.provider == Providers.AWS:
            self.aws_ses = session.client('ses', region_name=config.get('ses_region'))
        self.ldap_lookup = self.get_ldap_connection()
        self.jp_key = jmespath.compile(
            config.get("servicenow_it_service_key", "custodian_it_service"))
        self.servicenow_url = config.get("servicenow_url")

    def get_ldap_connection(self):
        if self.config.get('ldap_uri'):
            credential = decrypt(
                self.config, self.logger, self.session, 'ldap_bind_password')
            self.config['ldap_bind_password'] = credential
            return LdapLookup(self.config, self.logger)
        return None

    def get_valid_emails_from_list(self, targets):
        emails = []
        for target in targets:
            if target in ('resource-owner', 'event-owner'):
                continue
            target = target.replace(";", ",").replace(":", ",")
            for email in target.split(','):
                email = email.strip()
                if not email:
                    continue
                if is_email(email):
                    emails.append(email)
                # gcp doesn't support the '@' character in their label values so we
                # allow users to specify an email_base_url to append to the end of their
                # owner contact tags
                if not is_email(email) and self.config.get('email_base_url'):
                    full_email = "%s@%s" % (email, self.config['email_base_url'])
                    if is_email(full_email):
                        emails.append(full_email)
        return emails

    def get_event_owner_email(self, targets, event):  # TODO: GCP-friendly
        if 'event-owner' in targets:
            aws_username = get_aws_username_from_event(self.logger, event)
            if aws_username:
                # is using SSO, the target might already be an email
                if is_email(aws_username):
                    return [aws_username]
                # if the LDAP config is set, lookup in ldap
                elif self.config.get('ldap_uri', False):
                    return self.ldap_lookup.get_email_to_addrs_from_uid(aws_username)

                # the org_domain setting is configured, append the org_domain
                # to the username from AWS
                elif self.config.get('org_domain', False):
                    org_domain = self.config.get('org_domain', False)
                    self.logger.info('adding email %s to targets.', aws_username + '@' + org_domain)
                    return [aws_username + '@' + org_domain]
                else:
                    self.logger.warning('unable to lookup owner email. \
                            Please configure LDAP or org_domain')
            else:
                self.logger.info('no aws username in event')
        return []

    def get_ldap_emails_from_resource(self, sqs_message, resource):
        ldap_uid_tag_keys = self.config.get('ldap_uid_tags', [])
        ldap_uri = self.config.get('ldap_uri', False)
        if not ldap_uid_tag_keys or not ldap_uri:
            return []
        # this whole section grabs any ldap uids (including manager emails if option is on)
        # and gets the emails for them and returns an array with all the emails
        ldap_uid_tag_values = get_resource_tag_targets(resource, ldap_uid_tag_keys)
        email_manager = sqs_message['action'].get('email_ldap_username_manager', False)
        ldap_uid_emails = []
        # some types of resources, like iam-user have 'Username' in the resource, if the policy
        # opted in to resource_ldap_lookup_username: true, we'll do a lookup and send an email
        if sqs_message['action'].get('resource_ldap_lookup_username'):
            ldap_uid_emails = ldap_uid_emails + self.ldap_lookup.get_email_to_addrs_from_uid(
                resource.get('UserName'),
                manager=email_manager
            )
        for ldap_uid_tag_value in ldap_uid_tag_values:
            ldap_emails_set = self.ldap_lookup.get_email_to_addrs_from_uid(
                ldap_uid_tag_value,
                manager=email_manager
            )
            ldap_uid_emails = ldap_uid_emails + ldap_emails_set
        return ldap_uid_emails

    def get_resource_owner_emails_from_resource(self, sqs_message, resource):
        if 'resource-owner' not in sqs_message['action'].get('to', []):
            return []
        resource_owner_tag_keys = self.config.get('contact_tags', [])
        resource_owner_tag_values = get_resource_tag_targets(resource, resource_owner_tag_keys)
        explicit_emails = self.get_valid_emails_from_list(resource_owner_tag_values)

        # resolve the contact info from ldap
        ldap_emails = []
        org_emails = []
        non_email_ids = list(set(resource_owner_tag_values).difference(explicit_emails))
        if self.config.get('ldap_uri', False):
            ldap_emails = list(chain.from_iterable([self.ldap_lookup.get_email_to_addrs_from_uid
                                                    (uid) for uid in non_email_ids]))

        elif self.config.get('org_domain', False):
            self.logger.debug(
                "Using org_domain to reconstruct email addresses from contact_tags values")
            org_domain = self.config.get('org_domain')
            org_emails = [uid + '@' + org_domain for uid in non_email_ids]

        return list(chain(explicit_emails, ldap_emails, org_emails))

    def get_account_emails(self, sqs_message):  # TODO: GCP-friendly
        email_list = []

        if 'account-emails' not in sqs_message['action'].get('to', []):
            return []

        account_id = sqs_message.get('account_id', None)
        self.logger.debug('get_account_emails for account_id: %s.', account_id)

        if account_id is not None:
            account_email_mapping = self.config.get('account_emails', {})
            self.logger.debug(
                'get_account_emails account_email_mapping: %s.', account_email_mapping)
            email_list = account_email_mapping.get(account_id, [])
            self.logger.debug('get_account_emails email_list: %s.', email_list)

        return self.get_valid_emails_from_list(email_list)

    # this function returns a dictionary with a tuple of emails as the key
    # and the list of resources as the value. This helps ensure minimal emails
    # are sent, while only ever sending emails to the respective parties.
    def get_email_to_addrs_to_resources_map(self, sqs_message):
        # policy_to_emails always get sent to any email msg that goes out
        # these were manually set by the policy writer in notify to section
        # or it's an email from an aws event username from an ldap_lookup
        email_to_addrs_to_resources_map = {}
        targets = sqs_message['action'].get('to', []) + \
            (sqs_message['action']['cc'] if 'cc' in sqs_message['action'] else [])
        no_owner_targets = self.get_valid_emails_from_list(
            sqs_message['action'].get('owner_absent_contact', [])
        )
        # policy_to_emails includes event-owner if that's set in the policy notify to section
        policy_to_emails = self.get_valid_emails_from_list(targets)
        # if event-owner is set, and the aws_username has an ldap_lookup email
        # we add that email to the policy emails for these resource(s) on this sqs_message
        event_owner_email = self.get_event_owner_email(targets, sqs_message['event'])

        account_emails = self.get_account_emails(sqs_message)

        policy_to_emails = policy_to_emails + event_owner_email + account_emails
        for resource in sqs_message['resources']:
            # this is the list of emails that will be sent for this resource
            resource_emails = []
            # add in any ldap emails to resource_emails
            resource_emails = resource_emails + self.get_ldap_emails_from_resource(
                sqs_message,
                resource
            )
            resource_emails = resource_emails + policy_to_emails
            # add in any emails from resource-owners to resource_owners
            ro_emails = self.get_resource_owner_emails_from_resource(
                sqs_message,
                resource
            )

            resource_emails = resource_emails + ro_emails
            # if 'owner_absent_contact' was specified in the policy and no resource
            # owner emails were found, add those addresses
            if len(ro_emails) < 1 and len(no_owner_targets) > 0:
                resource_emails = resource_emails + no_owner_targets
            # we allow multiple emails from various places, we'll unique with set to not have any
            # duplicates, and we'll also sort it so we always have the same key for other resources
            # and finally we'll make it a tuple, since that is hashable and can be a key in a dict
            resource_emails = tuple(sorted(set(resource_emails)))
            # only if there are valid emails available, add it to the map
            if resource_emails:
                email_to_addrs_to_resources_map.setdefault(resource_emails, []).append(resource)
        if email_to_addrs_to_resources_map == {}:
            self.logger.debug('Found no email addresses, sending no emails.')
        # eg: { ('milton@initech.com', 'peter@initech.com'): [resource1, resource2, etc] }
        return email_to_addrs_to_resources_map

    def get_to_addrs_email_messages_map(self, sqs_message):
        to_addrs_to_resources_map = self.get_email_to_addrs_to_resources_map(sqs_message)
        to_addrs_to_mimetext_map = {}
        for to_addrs, resources in to_addrs_to_resources_map.items():
            to_addrs_to_mimetext_map[to_addrs] = get_mimetext_message(
                self.config,
                self.logger,
                sqs_message,
                resources,
                list(to_addrs)
            )
        # eg: { ('milton@initech.com', 'peter@initech.com'): mimetext_message }
        return to_addrs_to_mimetext_map

    def get_grouped_resources(self, message, attr_group=None) -> Dict[str, List]:
        groupby_key = (message['action'].get(attr_group, {}).get('resource_groupby')
            or message['action'].get('resource_groupby'))
        if not groupby_key:
            return {'default': message['resources']}

        grouped_resources = {}
        jp = jmespath.compile(groupby_key)

        for resource in message['resources']:
            groupby_value = jp.search(resource) or 'default'
            grouped_resources.setdefault(groupby_value, []).append(resource)
        # eg: { 'CLOUDOPS': [resource1, resource2, etc] }
        return grouped_resources

    def get_group_email_messages_map(self, sqs_message):
        servicenow_address = self.config.get('servicenow_address')
        dedicated_addresses = self.config.get("servicenow_dedicated_addresses")

        groupby_to_resources_map = self.get_grouped_resources(sqs_message, "servicenow")
        groupby_to_mimetext_map = {}
        for group_name, resources in groupby_to_resources_map.items():
            # print(f"{group_name}: {[r[r['c7n_resource_type_id']] for r in resources]}")
            # NOTE if having a dedicated address, use it regardless it_service
            if dedicated_addresses:
                account_id = sqs_message.get("account_id")
                for da in dedicated_addresses:
                    if account_id in da.get("accounts", []):
                        products = da.get("products")
                        if not products or group_name in products:
                            servicenow_address = da.get("email", servicenow_address)
                            break

            snow_conf = sqs_message["action"].get("servicenow", {})
            # FIXME should search all resources in the group until found
            it_service = self.jp_key.search(resources[0]) or snow_conf.get("it_service")
            # NOTE override it_service for 'default' group, which should be more desirable
            if group_name == "default":
                it_service = snow_conf.get("it_service")
            if not it_service:
                self.logger.info(
                    f"ServiceNow: Skip {len(resources)} resources due to "
                    f"it_service value not found for product {group_name}"
                )
                continue
            groupby_to_mimetext_map[group_name] = get_mimetext_message(
                self.config,
                self.logger,
                sqs_message,
                resources,
                [servicenow_address],
                "servicenow_template"
            )
        # eg: { 'Jira': mimetext_message }
        return groupby_to_mimetext_map

    def send_c7n_email(self, sqs_message, email_to_addrs, mimetext_msg):
        # Build deduplication key
        policy = sqs_message.get('policy', {}).get('name', 'unknown')
        account_id = sqs_message.get('account_id', sqs_message.get('account', 'unknown'))
        account = sqs_message.get('account', 'unknown')
        region = sqs_message.get('region', 'unknown')
        recipient = ",".join(email_to_addrs)
        partition_key = str(sqs_message.get('execution_start', 'default'))
        dedup_id = f"email|{policy}|{account_id}|{account}|{region}|{recipient}"

        if dedup_check_and_write(partition_key, dedup_id):
            self.logger.info(f"Duplicate email suppressed for {dedup_id}")
            return
        try:
            # if smtp_server is set in mailer.yml, send through smtp
            if 'smtp_server' in self.config:
                smtp_delivery = SmtpDelivery(config=self.config,
                                             session=self.session,
                                             logger=self.logger)
                # TODO should use the To in mimetext_msg rather than email_to_addrs
                smtp_delivery.send_message(message=mimetext_msg, to_addrs=email_to_addrs)
            # TODO this looks like a bug, should be push up a level to sqs_queue_processor.py
            elif 'sendgrid_api_key' in self.config:
                sendgrid_delivery = sendgrid.SendGridDelivery(config=self.config,
                                                             session=self.session,
                                                             logger=self.logger)
                sendgrid_delivery.sendgrid_handler(
                    sqs_message,
                    self.get_to_addrs_email_messages_map(sqs_message)
                )
            # if smtp_server or sendgrid_api_key isn't set in mailer.yml, use aws ses normally.
            else:
                self.aws_ses.send_raw_email(RawMessage={'Data': mimetext_msg.as_string()})

            # NOTE mimetext_msg should not be none unless only use sendgrid
            if not mimetext_msg:
                mimetext_msg = {"To": email_to_addrs}
            # NOTE borrow 'action' object to carry the delivery result
            sqs_message["action"]["delivered_email"] = mimetext_msg.get('To')
            if self.servicenow_url:
                sqs_message["action"]["delivered_email_url"] = self.servicenow_url
        except Exception as error:
            self.logger.warning(
                "Error policy:%s account:%s sending to:%s \n\n error: %s\n\n mailer.yml: %s" % (
                    sqs_message['policy'],
                    sqs_message.get('account', ''),
                    mimetext_msg.get('To'),
                    error,
                    self.config
                )
            )
        self.logger.info("Sending account:%s policy:%s %s:%s email:%s to %s" % (
            sqs_message.get('account', ''),
            sqs_message['policy']['name'],
            sqs_message['policy']['resource'],
            mimetext_msg.get('resource_count', str(len(sqs_message['resources']))),
            mimetext_msg.get('email_template', sqs_message['action'].get('template', 'default')),
            mimetext_msg.get('To')))
