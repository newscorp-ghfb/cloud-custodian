# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

import unittest

from c7n_mailer.gcp_mailer.utils import gcp_decrypt
from mock import Mock


class GcpUtilsTest(unittest.TestCase):
    def test_gcp_decrypt_raw(self):
        self.assertEqual(gcp_decrypt({"test": "value"}, Mock(), "test", Mock()), "value")
        self.assertEqual(gcp_decrypt({"test": "value"}, Mock(), "test", Mock()), "value")
