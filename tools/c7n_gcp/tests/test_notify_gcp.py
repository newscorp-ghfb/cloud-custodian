# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

from unittest import mock

from gcp_common import BaseTest
from c7n_gcp.client import Session


class NotifyTest(BaseTest):

    @mock.patch("c7n.ctx.uuid.uuid4", return_value="00000000-0000-0000-0000-000000000000")
    @mock.patch("c7n.ctx.time.time", return_value=1661883360)
    @mock.patch("c7n_gcp.actions.notify.version", '0.9.18')
    def test_pubsub_notify(self, *args, **kwargs):
        factory = self.replay_flight_data("notify-action")

        orig_client = Session.client
        stub_client = mock.MagicMock()
        calls = []

        def client_factory(*args, **kw):
            calls.append(args)
            if len(calls) == 1:
                return orig_client(*args, **kw)
            return stub_client

        self.patch(Session, 'client', client_factory)

        p = self.load_policy({
            'name': 'test-notify',
            'resource': 'gcp.pubsub-topic',
            'filters': [
                {
                    'name': 'projects/cloud-custodian/topics/gcptestnotifytopic'
                }
            ],
            'actions': [
                {'type': 'notify',
                 'template': 'default',
                 'priority_header': '2',
                 'subject': 'testing notify action',
                 'to': ['user@domain.com'],
                 'transport':
                     {'type': 'pubsub',
                      'topic': 'projects/cloud-custodian/topics/gcptestnotifytopic'}
                 }
            ]}, session_factory=factory)

        resources = p.run()
        print("resources", resources)

        self.assertEqual(len(resources), 1)
        stub_client.execute_command.assert_called_once()

        stub_client.execute_command.assert_called_with(
            'publish', {
                'topic': 'projects/cloud-custodian/topics/gcptestnotifytopic',
                'body': {
                    'messages': {
                        # NOTE updated below due to c7n_resource_type_id added to response
                        'data': ('eJzdUztvwjAQ3v0rkOcmEJAoMHXq1l9QVZGxDzBybMs+o0aI/14/Eh4SU9Wp'
                                 'HjLc5/sed86ZUDiBRrqZ6KDUC6GMcxM0tlLEGuXBoxGS6aqZrxt6w5+DDvbS'
                                 '6IQxpVLBGiV5HwtnQjXrIEEIHittUO760uNNcDxDe25rG7Y+bCs0VvKE76RC'
                                 'cD7Cn+SOxTpzBI5+ypUJorp6meZGP41USajoFDJyIV85AUaTV0LsbSa8OULo'
                                 'rGKYqwJ2LCjMWZw0TmLfHoAJcAmdp3p0m5yM0aTeTwrXpChlSpPlaPDg3oTp'
                                 'mNQ1Nx3NhtAx7a1xWOY0GiqDKN3J/q9Dx9jkEmngG3hIjoblzoZTPfmMhz70'
                                 'eWTZZbNcNqvVYrGcRfgUtzNsfVav62ZFr0N+DPSPJ3z3jv/ipUY6/qo3Hwz5'
                                 'AcT73R9QWHOoeKMdRdsUaVhruZGX/gNvpj8R')
                    }}})
