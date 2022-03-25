# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
from gcp_common import BaseTest
from c7n_gcp.filters.metrics import GCPMetricsFilter


class TestGCPMetricsFilter(BaseTest):
    def test_metrics(self):

        session_factory = self.replay_flight_data("filter-metrics")

        p = self.load_policy(
            {
                "name": "test-metrics",
                "resource": "gcp.instance",
                "filters": [
                    {
                        'type': 'metrics',
                        'name': 'compute.googleapis.com/instance/cpu/utilization',
                        'metric-key': 'metric.labels.instance_name',
                        'aligner': 'ALIGN_MEAN',
                        'days': 14,
                        'value': 0.1,
                        'filter': ' resource.labels.zone = "us-east4-c"',
                        'op': 'less-than',
                    }
                ],
            },
            session_factory=session_factory,
        )
        resources = p.run()
        self.assertEqual(len(resources), 1)
        metric_name = 'compute.googleapis.com/instance/cpu/utilization.ALIGN_MEAN.REDUCE_NONE'
        metric = resources[0]['c7n.metrics'][metric_name]
        self.assertGreater(0.1, metric['points'][0]['value']['doubleValue'])

    def test_metrics_resource_regex(self):

        session_factory = self.replay_flight_data("filter-metrics")

        p = self.load_policy(
            {
                "name": "test-metrics",
                "resource": "gcp.instance",
                "filters": [
                    {
                        'type': 'metrics',
                        'name': 'compute.googleapis.com/instance/cpu/utilization',
                        'metric-key': 'metric.labels.instance_name',
                        'aligner': 'ALIGN_MEAN',
                        'days': 14,
                        'value': 0.1,
                        'filter': ' resource.labels.zone = "us-east4-c"',
                        'op': 'less-than',
                    }
                ],
            },
            session_factory=session_factory,
        )
        resources = p.run()
        self.assertEqual(len(resources), 1)
        metric_name = 'compute.googleapis.com/instance/cpu/utilization.ALIGN_MEAN.REDUCE_NONE'
        metric = resources[0]['c7n.metrics'][metric_name]
        self.assertGreater(0.1, metric['points'][0]['value']['doubleValue'])

    def test_no_metrics_found(self):

        session_factory = self.replay_flight_data("filter-no-metrics")

        p = self.load_policy(
            {
                "name": "test-metrics",
                "resource": "gcp.instance",
                "filters": [
                    {
                        'type': 'metrics',
                        'name': 'compute.googleapis.com/instance/cpu/utilization',
                        'metric-key': 'metric.labels.instance_name',
                        'aligner': 'ALIGN_MEAN',
                        'days': 14,
                        'value': 0.1,
                        'filter': ' resource.labels.zone = "us-east4-d"',
                        'op': 'less-than',
                    }
                ],
            },
            session_factory=session_factory,
        )
        resources = p.run()
        self.assertEqual(len(resources), 0)

    def test_batch_resources(self):
        policy = self.load_policy({"name": "test_batch_resources", "resource": "gcp.instance"})

        metric_filter = GCPMetricsFilter(
            {
                'type': 'metrics',
                'name': 'compute.googleapis.com/instance/cpu/utilization',
                'metric-key': 'metric.labels.instance_name',
                'value': 0.1,
                'filter': ' resource.labels.zone = "us-east4-d"',
                'op': 'less-than',
            },
            manager=policy.resource_manager,
        )
        resources = [{"name": "test_very_long_name"}] * 300
        metric_filter.process([])
        batch = metric_filter.get_batched_query_filter(resources)

        self.assertEqual(len(batch), 2)
        self.assertLess(len(batch[0]), 11000)
        self.assertIn('resource.labels.zone = "us-east4-d"', batch[0])
        self.assertIn('metric.type = "compute.googleapis.com/instance/cpu/utilization"', batch[0])
        self.assertIn('resource.labels.zone = "us-east4-d"', batch[1])
        self.assertIn('metric.type = "compute.googleapis.com/instance/cpu/utilization"', batch[1])


class TestSecurityComandCenterFindingsFilter(BaseTest):
    def test_findings(self):

        session_factory = self.replay_flight_data("filter-scc-findings")

        p = self.load_policy(
            {
                "name": "test-scc-findings",
                "resource": "gcp.bucket",
                "filters": [
                    {
                        'type': 'scc-findings',
                        'org': 111111111111,
                        'key': 'category',
                        'value': 'BUCKET_LOGGING_DISABLED',
                    }
                ],
            },
            session_factory=session_factory,
        )
        resources = p.run()
        self.assertEqual(len(resources), 1)
        self.assertEqual(
            resources[0]['c7n:matched-findings'][0]['category'],
            'BUCKET_LOGGING_DISABLED',
        )

    def test_findings_no_key(self):

        session_factory = self.replay_flight_data("filter-scc-findings")

        p = self.load_policy(
            {
                "name": "test-scc-findings",
                "resource": "gcp.bucket",
                "filters": [{'type': 'scc-findings', 'org': 111111111111}],
            },
            session_factory=session_factory,
        )
        resources = p.run()
        self.assertEqual(len(resources), 1)
