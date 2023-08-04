# This module calls the API gateway, extracts email addresses based on resource tags, account, account's cost center information, and updates resource details with the relevant email data to enhance communication capabilities.

import os
import json
import requests
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

PROVIDERS = {
    "AWS": 0,
    "Azure": 1,
    "GCP": 2,
}

def extract_appids(resource_list):
    appids = {tag.get("Value") for resource in resource_list for tag in resource.get("Tags", []) if tag.get("Key") == "appid"}
    return {"appid": list(appids)}

def call_api_and_update_resources(self, resources, event=None):
    try:
        # endpoint = os.environ.get('api_endpoint')
        endpoint = 'https://ownerlookupapi.services.dowjones.io/service'
        if not endpoint:
            raise ValueError("API endpoint not defined in environment variables.")
            
        resource_path = '/service'
        region = 'us-east-1'
        service = 'execute-api'

        session = boto3.Session(region_name=region)
        credentials = session.get_credentials()

        appids_data = extract_appids(resources)
        if self.account_id:
            appids_data["account"] = [self.account_id]

        request = AWSRequest(method='POST', url=endpoint + resource_path, headers={'Content-Type': 'application/json'})
        request.data = json.dumps(appids_data)
        SigV4Auth(credentials, service, region).add_auth(request)

        response = requests.post(
            request.url,
            headers=request.headers,
            data=request.data
        )
        response.raise_for_status()
        response_data = response.json()

        email_address = {}
        def extract_from_dict(data_dict, parent_key=""):
            nonlocal email_address
            for key, value in data_dict.items():
                current_key = f"{parent_key}.{key}" if parent_key else key
                if isinstance(value, dict):
                    extract_from_dict(value, parent_key=current_key)
                elif isinstance(value, str) and "@" in value:
                    if parent_key not in email_address:
                        email_address[parent_key] = {}
                    email_address[parent_key][key] = value

        extract_from_dict(response_data)

        for resource in resources:
            tags = resource.get("Tags", [])
            app_id = next((tag.get("Value") for tag in tags if tag.get("Key") == "appid"), None)
            owner_id = self.account_id

            if app_id:
                app_email_data = email_address.get(f"appid.{app_id}", {})
                for key, value in app_email_data.items():
                    if isinstance(value, str) and "@" in value:
                        resource[key] = value

            if owner_id:
                email_data = email_address.get(f"account.{owner_id}", {})
                for key, value in email_data.items():
                    if isinstance(value, str) and "@" in value:
                        resource[key] = value

                cost_cc_email_data = email_address.get(f"account.{owner_id}.cost_center_info", {})
                for key, value in cost_cc_email_data.items():
                    if isinstance(value, str) and "@" in value:
                        resource[key] = value

        return resources

    except requests.exceptions.RequestException as req_error:
        raise ValueError(f"Error making API request: {req_error}")
    except (ValueError, json.JSONDecodeError) as json_error:
        raise ValueError(f"Error processing API response: {json_error}")
    except Exception as error:
        raise ValueError(f"Unexpected error occurred: {error}")
