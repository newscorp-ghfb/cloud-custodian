# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

from unittest import mock

from gcp_common import BaseTest
from c7n_gcp.client import Session


class NotifyTest(BaseTest):

    def test_pubsub_notify(self):
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
                        'data': ('eJzdU7tuwyAU3fkKi7mOlSxVM3Xq1i+IKovAtUOFuQgulawo/'
                                 '14eteNKnapOXc/hngdcrozDB1jix8ZGYx4YF1JitNRrlTAuYyB'
                                 'UWth2f3ja8zv/M+lh1GgzJ4zJgEOj5ZyAK+NWTJApgkCtRdLDX'
                                 'GcCRi8LNUq3c/Ec4rkldFpmftCGwIdEn9hGxXl8B0mhkwajatcs'
                                 'XRkMXZLKRtWnirEbeysNKIVcBWl2RfCeiGByRlBBFQwiGipdvEa'
                                 'vae4vIBT4zB4yntLmJEs1bcemajXVqUhiseMxgH9WOAltdxInXg'
                                 'KRFzY49FTvaQlUL6JO5/i/Lp1qs9ta/LvJP2692a2/2J4kJx/t8'
                                 'VWQvIB62WxlVS2l0ol+Me1zpa9/VE+Uh/gE2Z8jug==')
                    }}})
