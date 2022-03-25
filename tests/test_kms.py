# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
import json
import time


from c7n.resources.aws import shape_validate
from .common import BaseTest, functional


class KMSTest(BaseTest):
    def test_kms_grant(self):
        session_factory = self.replay_flight_data("test_kms_grants")
        p = self.load_policy(
            {
                "name": "kms-grant-count",
                "resource": "kms",
                "filters": [{"type": "grant-count"}],
            },
            session_factory=session_factory,
        )

        resources = p.run()
        self.assertEqual(len(resources), 0)

    def test_kms_key_alias_augment(self):
        session_factory = self.replay_flight_data("test_kms_key_alias")
        p = self.load_policy(
            {
                "name": "kms-key-alias-filter",
                "resource": "kms-key",
                "filters": [
                    {
                        "type": "value",
                        "key": "AliasNames",
                        "op": "in",
                        "value": "alias/aws/dms",
                        "value_type": "swap",
                    }
                ],
            },
            session_factory=session_factory,
        )

        resources = p.run()
        self.assertEqual(len(resources), 1)

    def test_key_rotation(self):
        session_factory = self.replay_flight_data("test_key_rotation")
        p = self.load_policy(
            {
                "name": "kms-key-rotation",
                "resource": "kms-key",
                "filters": [
                    {
                        "type": "key-rotation-status",
                        "key": "KeyRotationEnabled",
                        "value": True,
                    }
                ],
            },
            session_factory=session_factory,
        )

        resources = p.run()
        self.assertEqual(len(resources), 1)

    def test_set_key_rotation(self):
        session_factory = self.replay_flight_data("test_key_rotation_set")
        p = self.load_policy(
            {
                "name": "enable-key-rotation",
                "resource": "kms-key",
                "filters": [
                    {"tag:Name": "CMK-Rotation-Test"},
                    {
                        "type": "key-rotation-status",
                        "key": "KeyRotationEnabled",
                        "value": False,
                    },
                ],
                "actions": [{"type": "set-rotation", "state": True}],
            },
            session_factory=session_factory,
        )
        resources = p.run()
        self.assertEqual(len(resources), 1)
        client = session_factory(region="us-east-1").client("kms")
        key = client.get_key_rotation_status(KeyId=resources[0]["KeyId"])
        self.assertEqual(key["KeyRotationEnabled"], True)

    def test_kms_config_source(self):
        session_factory = self.replay_flight_data("test_kms_config_source")
        p = self.load_policy(
            {
                "name": "kms-config-source",
                "resource": "kms-key",
                "source": "config",
                "query": [
                    {"clause": "configuration.description = 'For testing the KMS config source'"}
                ],
                "filters": [
                    {"AliasNames[0]": "alias/config-source-testing"},
                    {"tag:ConfigTesting": "present"},
                ],
            },
            session_factory=session_factory,
            config={"region": "us-east-2"},
        )
        resources = p.run()
        self.assertEqual(len(resources), 1)

    def test_kms_access_denied(self):
        session_factory = self.replay_flight_data("test_kms_access_denied")
        p = self.load_policy(
            {
                "name": "survive-access-denied",
                "resource": "kms-key",
                "filters": [
                    {
                        "type": "value",
                        "key": "AliasNames[0]",
                        "op": "glob",
                        "value": "alias/test-kms*",
                    }
                ],
            },
            session_factory=session_factory,
            config={"region": "us-west-1"},
        )
        resources = p.run()
        self.assertEqual(len(resources), 2)

        # Restrictive key policies may prevent us from loading detailed
        # key information, but we should always have an Arn
        self.assertFalse(all('KeyState' in r for r in resources))
        self.assertTrue(all('Arn' in r for r in resources))

    @functional
    def test_kms_remove_matched(self):
        session_factory = self.replay_flight_data("test_kms_remove_matched")

        sts = session_factory().client("sts")
        current_user_arn = sts.get_caller_identity()["Arn"]

        client = session_factory().client("kms")
        key_id = client.create_key()["KeyMetadata"]["KeyId"]
        self.addCleanup(client.schedule_key_deletion, KeyId=key_id, PendingWindowInDays=7)

        client.put_key_policy(
            KeyId=key_id,
            PolicyName="default",
            Policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "DefaultRoot",
                            "Effect": "Allow",
                            "Principal": {"AWS": current_user_arn},
                            "Action": "kms:*",
                            "Resource": "*",
                        },
                        {
                            "Sid": "SpecificAllow",
                            "Effect": "Allow",
                            "Principal": {"AWS": current_user_arn},
                            "Action": "kms:*",
                            "Resource": "*",
                        },
                        {
                            "Sid": "Public",
                            "Effect": "Allow",
                            "Principal": "*",
                            "Action": "kms:*",
                            "Resource": "*",
                        },
                    ],
                }
            ),
        )

        self.assertStatementIds(client, key_id, "DefaultRoot", "SpecificAllow", "Public")

        p = self.load_policy(
            {
                "name": "kms-rm-matched",
                "resource": "kms-key",
                "filters": [
                    {"KeyId": key_id},
                    {"type": "cross-account", "whitelist": [self.account_id]},
                ],
                "actions": [{"type": "remove-statements", "statement_ids": "matched"}],
            },
            session_factory=session_factory,
        )

        resources = p.run()
        self.assertEqual([r["KeyId"] for r in resources], [key_id])

        if self.recording:
            time.sleep(60)  # takes time before new policy reflected

        self.assertStatementIds(client, key_id, "DefaultRoot", "SpecificAllow")

    def assertStatementIds(self, client, key_id, *expected):
        p = client.get_key_policy(KeyId=key_id, PolicyName="default")["Policy"]
        actual = [s["Sid"] for s in json.loads(p)["Statement"]]
        self.assertEqual(actual, list(expected))

    @functional
    def test_kms_remove_named(self):
        session_factory = self.replay_flight_data("test_kms_remove_named")
        client = session_factory().client("kms")
        key_id = client.create_key()["KeyMetadata"]["KeyId"]
        self.addCleanup(client.schedule_key_deletion, KeyId=key_id, PendingWindowInDays=7)

        client.put_key_policy(
            KeyId=key_id,
            PolicyName="default",
            Policy=json.dumps(
                {
                    "Version": "2008-10-17",
                    "Statement": [
                        {
                            "Sid": "DefaultRoot",
                            "Effect": "Allow",
                            "Principal": "*",
                            "Action": "kms:*",
                            "Resource": "*",
                        },
                        {
                            "Sid": "RemoveMe",
                            "Effect": "Allow",
                            "Principal": "*",
                            "Action": "kms:*",
                            "Resource": "*",
                        },
                    ],
                }
            ),
        )

        self.assertStatementIds(client, key_id, "DefaultRoot", "RemoveMe")

        p = self.load_policy(
            {
                "name": "kms-rm-named",
                "resource": "kms-key",
                "filters": [{"KeyId": key_id}],
                "actions": [{"type": "remove-statements", "statement_ids": ["RemoveMe"]}],
            },
            session_factory=session_factory,
        )

        resources = p.run()
        self.assertEqual(len(resources), 1)

        if self.recording:
            time.sleep(60)  # takes time before new policy reflected

        self.assertStatementIds(client, key_id, "DefaultRoot")


class KMSTagging(BaseTest):
    @functional
    def test_kms_key_tag(self):
        session_factory = self.replay_flight_data("test_kms_key_tag")
        client = session_factory().client("kms")
        key_id = client.create_key()["KeyMetadata"]["KeyId"]
        self.addCleanup(client.schedule_key_deletion, KeyId=key_id, PendingWindowInDays=7)
        policy = self.load_policy(
            {
                "name": "kms-key-tag",
                "resource": "kms-key",
                "filters": [{"KeyId": key_id}],
                "actions": [{"type": "tag", "key": "RequisiteKey", "value": "Required"}],
            },
            session_factory=session_factory,
        )
        resources = policy.run()
        self.assertEqual(len(resources), 1)
        tags = client.list_resource_tags(KeyId=key_id)["Tags"]
        self.assertEqual(tags[0]["TagKey"], "RequisiteKey")

    @functional
    def test_kms_key_remove_tag(self):
        session_factory = self.replay_flight_data("test_kms_key_remove_tag")
        client = session_factory().client("kms")
        key_id = client.create_key(Tags=[{"TagKey": "ExpiredTag", "TagValue": "Invalid"}])[
            "KeyMetadata"
        ]["KeyId"]
        self.addCleanup(client.schedule_key_deletion, KeyId=key_id, PendingWindowInDays=7)

        policy = self.load_policy(
            {
                "name": "kms-key-remove-tag",
                "resource": "kms-key",
                "filters": [{"KeyState": "Enabled"}, {"tag:ExpiredTag": "Invalid"}],
                "actions": [{"type": "remove-tag", "tags": ["ExpiredTag"]}],
            },
            session_factory=session_factory,
        )

        resources = policy.run()
        self.assertTrue(len(resources), 1)
        self.assertEqual(resources[0]["KeyId"], key_id)
        tags = client.list_resource_tags(KeyId=key_id)["Tags"]
        self.assertEqual(len(tags), 0)

    def test_kms_key_related(self):
        session_factory = self.replay_flight_data("test_kms_key_related")
        key_alias = "alias/aws/sqs"
        p = self.load_policy(
            {
                "name": "sqs-kms-key-related",
                "resource": "sqs",
                "source": "config",
                "query": [{"clause": "resourceName like 'test-kms%'"}],
                "filters": [
                    {
                        "type": "kms-key",
                        "key": "c7n:AliasName",
                        "value": key_alias,
                        "op": "eq",
                    }
                ],
            },
            session_factory=session_factory,
        )
        resources = p.run()
        client = session_factory().client("kms")
        self.assertEqual(len(resources), 2)
        target_key = client.describe_key(KeyId=key_alias)
        self.assertTrue(
            all(
                res['KmsMasterKeyId'] in (key_alias, target_key['KeyMetadata']['Arn'])
                for res in resources
            )
        )

    def test_kms_post_finding(self):
        factory = self.replay_flight_data('test_kms_post_finding')
        p = self.load_policy(
            {
                'name': 'kms',
                'resource': 'aws.kms',
                'actions': [
                    {
                        'type': 'post-finding',
                        'types': ['Software and Configuration Checks/OrgStandard/abc-123'],
                    }
                ],
            },
            session_factory=factory,
            config={'region': 'us-west-2'},
        )

        resources = p.resource_manager.get_resources(
            ['arn:aws:kms:us-west-2:644160558196:alias/c7n-test']
        )
        rfinding = p.resource_manager.actions[0].format_resource(resources[0])
        self.maxDiff = None
        self.assertEqual(
            rfinding,
            {
                'Details': {
                    'AwsKmsKey': {
                        'KeyId': '44d25a5c-7efa-44ed-8436-b9511ea921b3',
                        'KeyManager': 'CUSTOMER',
                        'KeyState': 'Enabled',
                        'CreationDate': 1493967398.394,
                        'Origin': 'AWS_KMS',
                    }
                },
                'Id': 'arn:aws:kms:us-west-2:644160558196:alias/44d25a5c-7efa-44ed-8436-b9511ea921b3',
                'Partition': 'aws',
                'Region': 'us-west-2',
                'Type': 'AwsKmsKey',
            },
        )

        shape_validate(rfinding['Details']['AwsKmsKey'], 'AwsKmsKeyDetails', 'securityhub')
