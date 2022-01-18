import copy
import jmespath
import re

from c7n.filters.core import Filter, ValueFilter

from c7n.utils import local_session, type_schema, gcpLabelaise


class IamPolicyFilter(Filter):
    """
    Filters resources based on their IAM policy
    """

    value_filter_schema = copy.deepcopy(ValueFilter.schema)
    del value_filter_schema['required']

    user_role_schema = {
        'type': 'object',
        'additionalProperties': False,
        'required': ['user', 'role'],
        'properties': {
            'user': {'type': 'string'},
            'role': {'type': 'string'},
            'has': {'type': 'boolean'}
        }
    }

    extract_schema = {
        'type': 'object',
        'additionalProperties': False,
        'required': ['key', 'expr'],
        'properties': {
            'key': {'type': 'string'},
            'expr': {'type': 'string'},
            'regex': {'type': 'string'},
            'value_type': {'enum': ['gcp_label']},
        }
    }

    schema = type_schema(
        'iam-policy',
        **{'doc': value_filter_schema,
        'user-role': user_role_schema,
        'extract': extract_schema})

    def get_client(self, session, model):
        return session.client(
            model.service, model.version, model.component)

    def process(self, resources, event=None):
        if 'doc' in self.data:
            try:
                valueFilter = IamPolicyValueFilter(self.data['doc'], self.manager)
                resources = valueFilter.process(resources)
            except TypeError:
                valueFilter = IamPolicyValueFilter(self.data['doc'], self.manager, "bucket")
                resources = valueFilter.process(resources)
        if 'user-role' in self.data:
            user_role = self.data['user-role']
            key = user_role['user']
            val = user_role['role']
            op = 'in' if user_role.get('has', True) else 'not-in'
            value_type = 'swap'
            userRolePairFilter = IamPolicyUserRolePairFilter({'key': key, 'value': val,
            'op': op, 'value_type': value_type}, self.manager)
            resources = userRolePairFilter.process(resources)

        # NOTE news corp customisation to extract values from binding iam policies
        if "extract" in self.data:
            extract = self.data["extract"]
            for r in resources:
                expr = ".".join(f'"{e}"' if ":" in e else e for e in extract["expr"].split("."))
                v = jmespath.search(expr, r) or []
                if "regex" in extract:
                    # regex example: 'user:(.*)@news.com.au'
                    p = re.compile(extract["regex"])
                    v = self.extractString(v, p)
                if extract.get("value_type") == "gcp_label":
                    v = gcpLabelaise(v)
                # print(f"extracted {v}")
                r[extract["key"]] = v

        return resources

    def extractString(self, value, pattern):
        if isinstance(value, str):
            # NOTE group(1) will return the 1st capture (stuff within the brackets)
            result = pattern.search(value)
            return result.group(1) if result else None
        elif isinstance(value, list):
            return list(filter(None, [self.extractString(i, pattern) for i in value]))
        return value


class IamPolicyValueFilter(ValueFilter):
    """Generic value filter on resources' IAM policy bindings using jmespath

    :example:

    Filter all kms-cryptokeys accessible to all users
    or all authenticated users

    .. code-block :: yaml

       policies:
        - name: gcp-iam-policy-value
          resource: gcp.kms-cryptokey
          filters:
            - type: iam-policy
              doc:
                key: "bindings[*].members[]"
                op: intersect
                value: ["allUsers", "allAuthenticatedUsers"]
    """

    schema = type_schema('iam-policy', rinherit=ValueFilter.schema,)
#     permissions = 'GCP_SERVICE.GCP_RESOURCE.getIamPolicy',)

    def __init__(self, data, manager=None, identifier="resource"):
        super(IamPolicyValueFilter, self).__init__(data, manager)
        self.identifier = identifier

    def get_client(self, session, model):
        return session.client(
            model.service, model.version, model.component)

    def process(self, resources, event=None):
        model = self.manager.get_model()
        session = local_session(self.manager.session_factory)
        client = self.get_client(session, model)

        for r in resources:
            iam_policy = client.execute_command('getIamPolicy', self._verb_arguments(r))
            r["c7n:iamPolicy"] = iam_policy

        return super(IamPolicyValueFilter, self).process(resources)

    def __call__(self, r):
        return self.match(r['c7n:iamPolicy'])

    def _verb_arguments(self, resource):
        """
        Returns a dictionary passed when making the `getIamPolicy` and 'setIamPolicy' API calls.

        :param resource: the same as in `get_resource_params`
        """
        return {self.identifier: resource[self.manager.resource_type.id]}


class IamPolicyUserRolePairFilter(ValueFilter):
    """Filters resources based on specified user-role pairs.

    :example:

    Filter all projects where the user test123@gmail.com does not have the owner role

    .. code-block :: yaml

       policies:
        - name: gcp-iam-user-roles
          resource: gcp.project
          filters:
            - type: iam-policy
              user-role:
                user: "user:test123@gmail.com"
                has: false
                role: "roles/owner"
    """

    schema = type_schema('iam-user-roles', rinherit=ValueFilter.schema)
#     permissions = ('resourcemanager.projects.getIamPolicy',)

    def get_client(self, session, model):
        return session.client(
            model.service, model.version, model.component)

    def process(self, resources, event=None):
        model = self.manager.get_model()
        session = local_session(self.manager.session_factory)
        client = self.get_client(session, model)

        for r in resources:
            iam_policy = client.execute_command('getIamPolicy', {"resource": r["projectId"]})
            r["c7n:iamPolicyUserRolePair"] = {}
            userToRolesMap = {}

            for b in iam_policy["bindings"]:
                role, members = b["role"], b["members"]
                for user in members:
                    if user in userToRolesMap:
                        userToRolesMap[user].append(role)
                    else:
                        userToRolesMap[user] = [role]
            for user, roles in userToRolesMap.items():
                r["c7n:iamPolicyUserRolePair"][user] = roles
                # if user.startswith("user:"):
                #     print(f'{r["projectNumber"]};{r["projectId"]};{r["lifecycleState"]};{user[5:]};{",".join([i[6:] if i.startswith("roles/") else i for i in roles])}')

        return super(IamPolicyUserRolePairFilter, self).process(resources)

    def __call__(self, r):
        return self.match(r["c7n:iamPolicyUserRolePair"])

    def _verb_arguments(self, resource, identifier="resource"):
        """
        Returns a dictionary passed when making the `getIamPolicy` and 'setIamPolicy' API calls.

        :param resource: the same as in `get_resource_params`
        """
        return {identifier: resource[self.manager.resource_type.id]}
