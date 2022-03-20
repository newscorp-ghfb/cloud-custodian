# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
import base64
import json
import unittest
import zlib

from common import (
    logger,
    MAILER_CONFIG_GCP,
    GCP_MESSAGE,
    GCP_MESSAGES,
    PUBSUB_MESSAGE_DATADOG,
)
from c7n_mailer.gcp_mailer.gcp_queue_processor import MailerGcpQueueProcessor
from c7n_mailer.email_delivery import EmailDelivery
from c7n_mailer.utils import get_provider
from mock import call, MagicMock, patch


class GcpTest(unittest.TestCase):
    def setUp(self):
        self.compressed_message = GCP_MESSAGE
        self.loaded_message = json.loads(GCP_MESSAGE)

    @patch.object(EmailDelivery, "send_c7n_email")
    def test_process_message(self, mock_email):
        mock_email.return_value = True
        processor = MailerGcpQueueProcessor(MAILER_CONFIG_GCP, logger)
        self.assertTrue(processor.process_message(GCP_MESSAGES["receivedMessages"][0]))

    @patch.object(MailerGcpQueueProcessor, "receive_messages")
    def test_receive(self, mock_receive):
        mock_receive.return_value = {}
        processor = MailerGcpQueueProcessor(MAILER_CONFIG_GCP, logger)
        messages = processor.receive_messages()
        self.assertEqual(messages, {})

    @patch.object(MailerGcpQueueProcessor, "ack_messages")
    def test_ack(self, mock_ack):
        mock_ack.return_value = {}
        processor = MailerGcpQueueProcessor(MAILER_CONFIG_GCP, logger)
        self.assertEqual(processor.ack_messages("2019-05-13T18:31:17.926Z"), {})

    @patch.object(MailerGcpQueueProcessor, "receive_messages")
    def test_run(self, mock_receive):
        mock_receive.return_value = []
        processor = MailerGcpQueueProcessor(MAILER_CONFIG_GCP, logger)
        processor.run()

    def test_is_gcp_cloud(self):
        self.assertEqual(get_provider(MAILER_CONFIG_GCP), 2)

    @patch("common.logger.info")
    @patch.object(MailerGcpQueueProcessor, "receive_messages")
    def test_processor_run_logging(self, mock_receive, mock_log):
        mock_receive.return_value = []
        processor = MailerGcpQueueProcessor(MAILER_CONFIG_GCP, logger)
        processor.run()
        mock_log.assert_called_with(
            "No messages left in the gcp topic subscription," " now exiting c7n_mailer."
        )

    @patch("c7n_mailer.datadog_delivery.DataDogDelivery")
    def test_datadog_delivery(self, mock_datadog):
        datadog_mailer_config = {
            "queue_url": "projects/c7n-dev/subscriptions/getnotify",
            "datadog_api_key": "mock_api_key",
            "datadog_application_key": "mock_application_key",
        }

        datadog_compressed_message = MagicMock()
        datadog_compressed_message.content = base64.b64encode(
            zlib.compress(PUBSUB_MESSAGE_DATADOG.encode("utf8"))
        )
        datadog_loaded_message = json.loads(PUBSUB_MESSAGE_DATADOG)

        mock_datadog.return_value.get_datadog_message_packages.return_value = (
            "mock_datadog_message_map"
        )

        pubsub_message = {"message": {"data": datadog_compressed_message.content}}
        gcp_processor = MailerGcpQueueProcessor(datadog_mailer_config, logger)
        gcp_processor.process_message(pubsub_message)

        mock_datadog.assert_has_calls(
            [call().deliver_datadog_messages("mock_datadog_message_map", datadog_loaded_message)]
        )
