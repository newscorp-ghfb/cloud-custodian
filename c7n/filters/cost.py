import os
from typing import Dict

from c7n.cache import InMemoryCache
from c7n.filters import COST_ANNOTATION_KEY
from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport

from .core import OPERATORS, Filter


class Cost(Filter):
    """Annotate resource monthly cost with Infracost pricing API.
    It aims to provide an approximate cost for a generic case. For example,
    it only grabs the on-demand price with no pre-installed software for EC2 instances.

    Please use INFRACOST_API_ENDPOINT and INFRACOST_API_KEY environment vars
    to specify the API config.

    .. code-block:: yaml

    policies:
      - name: ec2-cost
        resource: ec2
        filters:
          - type: cost
            # monthly price = unit price * 730 hours
            quantity: 730
            op: greater-than
            # USD
            value: 20


    reference: https://www.infracost.io/docs/cloud_pricing_api/overview/
    """

    schema = {
        'type': 'object',
        'additionalProperties': False,
        'required': ['type'],
        'properties': {
            'api_endpoint': {'type': 'string'},
            'api_key': {'type': 'string'},
            # 'currency': {'type': 'number'},
            'quantity': {'type': 'number'},
            'op': {'$ref': '#/definitions/filters_common/comparison_operators'},
            'type': {'enum': ['cost']},
            'value': {'type': 'number'},
        },
    }
    schema_alias = True

    def __init__(self, data, manager=None):
        super().__init__(data, manager)
        self.cache = InMemoryCache({})
        self.api_endpoint = data.get(
            "api_endpoint",
            os.environ.get("INFRACOST_API_ENDPOINT", "https://pricing.api.infracost.io"),
        )
        self.api_key = data.get("api_key", os.environ.get("INFRACOST_API_KEY"))

    def validate(self):
        name = self.__class__.__name__
        if self.api_endpoint is None:
            raise ValueError("%s Filter requires Infracost pricing_api_endpoint" % name)

        if self.api_key is None:
            raise ValueError("%s Filter requires Infracost api_key" % name)
        return super(Cost, self).validate()

    def process(self, resources, event=None):
        transport = RequestsHTTPTransport(
            url=self.api_endpoint + "/graphql",
            headers={'X-Api-Key': self.api_key},
            verify=True,
            retries=5,
        )
        client = Client(transport=transport, fetch_schema_from_transport=True)
        query = gql(self.get_query())
        return [r for r in resources if self.process_resource(r, client, query)]

    def process_resource(self, resource, client, query):
        price = self.get_price(resource, client, query)
        resource[COST_ANNOTATION_KEY] = price
        op = self.data.get('operator', 'ge')
        value = self.data.get('value', -1)
        return OPERATORS[op](price["USD"], value)

    def get_price(self, resource, client, query):
        params = self.get_params(resource)
        quantity = self.get_quantity(resource)
        price = self._get_price(client, query, params, quantity)
        price['USD'] = round(price['USD'], 2)
        return price

    def _get_price(self, client, query, params, quantity=1):
        cache_key = str(params)
        price: Dict = self.cache.get(cache_key)
        if not price:
            price = self.invoke_infracost(client, query, params)
            self.cache.save(cache_key, price)

        total = price.copy()
        # TODO support configurable currency
        total["USD"] = float(total["USD"]) * quantity
        total["quantity"] = quantity
        return total

    def invoke_infracost(self, client, query, params):
        result = client.execute(query, variable_values=params)
        self.log.info(f"Infracost {params}: {result}")
        total = len(result["products"][0]["prices"])
        if total > 1:
            self.log.warning(f"Found {total} price options, expecting 1")
        return result["products"][0]["prices"][0]

    def get_query(self):
        raise NotImplementedError("use subclass")

    def get_params(self, resource):
        raise NotImplementedError("use subclass")

    def get_quantity(self, resource):
        return self.data.get("quantity", 1)
