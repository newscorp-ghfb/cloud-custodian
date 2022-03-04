# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

import unittest

from c7n_mailer.gcp_mailer.utils import gcp_decrypt
from mock import Mock


class GcpUtilsTest(unittest.TestCase):
    def test_gcp_decrypt_raw(self):
        self.assertEqual(gcp_decrypt({"test": "value"}, Mock(), "test", Mock()), "value")
        self.assertEqual(gcp_decrypt({"test": "value"}, Mock(), "test", Mock()), "value")

    # def test_gcp_decrypt_secret(self):  # TODO: Identify how to properly mock gcp client library
    #     config = {"test": {"type": "gcp.secretmanager", "secret": "projects/c7n-dev/secrets/smtp_pw"}}
    #     session_mock = Mock()
    #     session_mock.client().get_secret().value = "value"
    #     session_mock.get_session_for_resource.return_value = session_mock

    #     self.assertEqual(gcp_decrypt(config, Mock(), "test"), "value")
