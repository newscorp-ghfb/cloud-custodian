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
                        'data': ('eJzdU7tOAzEQ7O8rItfcJSFSCKmo6PgChE6OvUmMfF7LXkecovw7ftzlgaBB'
                                 'VLhwsbM7O7NrHysGBzDE1hMTtL6rGBcCg6FWyRhjQmOQtQieUCpu2CXhB9TB'
                                 'TqFJINc6BSxqJfoYOFbM8A4SROCpNkhq25caj8GJDO2EbWzY+LCpCa0SCd8q'
                                 'TeB8hF+rKxbr8B0E+ekXGdNc6KeRKjUqfQpZdaresgWKIs+E1NtMeFFE0FnN'
                                 'KUclbHnQlL04hU5R3+6BS3AJvU/xqDYpGa0ps5sUrknplCkxt2PBg3uS2HFl'
                                 'GoEdy4LIceMtOipzGgWVQZTqJP/XpqPt6hRp4ANESIqG9c6GU39zjYfd1Hni'
                                 'WeV8uZyvVovFchbhQ9zOsPVZ89jMV+w85FtD/3jCV+/4L15qpBMPZv3CSexB'
                                 'Pl/9gMKaTcWMdmzaJkvDWktGXvon+3ZBpQ==')
                    }}})
