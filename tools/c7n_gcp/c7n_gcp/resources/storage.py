# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
from googleapiclient.errors import HttpError
from google.cloud import storage
from c7n_gcp.actions.labels import LabelDelayedAction, SetLabelsAction
from c7n_gcp.filters.labels import LabelActionFilter
from c7n.utils import type_schema, local_session
from c7n_gcp.actions import MethodAction, SetIamPolicy
from c7n_gcp.provider import resources
from c7n_gcp.query import QueryResourceManager, TypeInfo
from c7n_gcp.filters import IamPolicyFilter


@resources.register('bucket')
class Bucket(QueryResourceManager):

    class resource_type(TypeInfo):
        service = 'storage'
        version = 'v1'
        component = 'buckets'
        scope = 'project'
        enum_spec = ('list', 'items[]', {'projection': 'full'})
        name = id = 'name'
        default_report_fields = [
            "name", "timeCreated", "location", "storageClass"]
        asset_type = "storage.googleapis.com/Bucket"
        scc_type = "google.cloud.storage.Bucket"
        metric_key = 'resource.labels.bucket_name'

        @staticmethod
        def get(client, resource_info):
            return client.execute_command(
                'get', {'bucket': resource_info['bucket_name']})

        @staticmethod
        def get_label_params(resource, all_labels):
            return {'bucket': resource['name'],
                    'fields': 'labels',
                    'body': {'labels': all_labels}}


@Bucket.filter_registry.register('iam-policy')
class BucketIamPolicyFilter(IamPolicyFilter):
    """
    Overrides the base implementation to process bucket resources correctly.
    """
    permissions = ('storage.buckets.getIamPolicy',)

    def _verb_arguments(self, resource):
        verb_arguments = {"bucket": resource["name"]}
        return verb_arguments


@Bucket.filter_registry.register('marked-for-op')
class BucketLabelActionFilter(LabelActionFilter):
    pass


def invoke_bucket_api(action, params):
    try:
        # NOTE override the client with storage.Client
        session = local_session(action.manager.session_factory)
        client = storage.Client(
            project=session.get_default_project(),
            credentials=session._credentials)
        bucket = client.get_bucket(params["bucket"])
        bucket.labels = params["body"]["labels"]
        bucket.patch()
    except HttpError as e:
        if e.resp.status in action.ignore_error_codes:
            return e
        raise


@Bucket.action_registry.register('set-labels')
class BucketSetLabelsAction(SetLabelsAction):

    def invoke_api(self, client, op_name, params):
        return invoke_bucket_api(self, params)


@Bucket.action_registry.register('mark-for-op')
class BucketLabelDelayedAction(LabelDelayedAction):

    def invoke_api(self, client, op_name, params):
        return invoke_bucket_api(self, params)


@Bucket.action_registry.register('set-iam-policy')
class BucketSetIamPolicy(SetIamPolicy):
    """
    Overrides the base implementation to process Bucket resources correctly.
    """

    permissions = ('storage.buckets.getIamPolicy', 'storage.buckets.setIamPolicy')

    def get_resource_params(self, model, resource):
        params = super().get_resource_params(model, resource)
        params["body"]["bindings"] = params["body"]["policy"]["bindings"]
        del params["body"]["policy"]
        return params

    def _verb_arguments(self, resource):
        verb_arguments = {"bucket": resource["name"]}
        return verb_arguments


@Bucket.action_registry.register('set-uniform-access')
class BucketLevelAccess(MethodAction):
    '''Uniform access disables object ACLs on a bucket.

    Enabling this means only bucket policies (and organization bucket
    policies) govern access to a bucket.

    When enabled, users can only specify bucket level IAM policies
    and not Object level ACL's.

    Example Policy:

    .. code-block:: yaml

      policies:
       - name: enforce-uniform-bucket-level-access
         resource: gcp.bucket
         filters:
          - iamConfiguration.uniformBucketLevelAccess.enable: false
         actions:
          - type: set-uniform-access
            # The following is also the default
            state: true
    '''

    schema = type_schema('set-uniform-access', state={'type': 'boolean'})
    method_spec = {'op': 'patch'}
    method_perm = 'update'

    # the google docs and example on this api appear to broken.
    # https://cloud.google.com/storage/docs/using-uniform-bucket-level-access#rest-apis
    #
    # instead we observe the behavior gsutil interaction to effect the same.
    # the key seems to be the undocumented projection parameter
    #
    def get_resource_params(self, model, resource):
        enabled = self.data.get('state', True)
        return {'bucket': resource['name'],
                'fields': 'iamConfiguration',
                'projection': 'noAcl',  # not documented but
                'body': {'iamConfiguration': {'uniformBucketLevelAccess': {'enabled': enabled}}}}
