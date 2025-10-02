import json
import requests
import boto3
from botocore.config import Config
from dataclasses import dataclass

@dataclass
class SecretConfig:
    name: str
    region: str
    token_key: str = "okta_api_token"

class OktaLookup:
    def __init__(self, domain:str, secret_config:SecretConfig):
        """
        """
        self.domain = domain
        self.secret_config = secret_config
        self.okta_token = None

    def get_secret_token(self) -> str:
        if not self.okta_token:
            config = Config(retries={'max_attempts': 5, 'mode': 'standard'})
            client = boto3.client('secretsmanager', region_name=self.secret_config.region, config=config)
            secret = client.get_secret_value(SecretId=self.secret_config.name)['SecretString']
            self.okta_token = json.loads(secret)[self.secret_config.token_key]
        return self.okta_token

    def get_headers(self):
        return {
            'Authorization': f'SSWS {self.get_secret_token()}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

    def get_user_by_email(self, email: str):
        """Get Okta user info by email (login)."""
        url = f"{self.domain}/api/v1/users"
        params = {"q": email}  # or use 'filter': f'profile.login eq "{email}"'

        response = requests.get(url, headers=self.get_headers(), params=params)
        response.raise_for_status()

        users = response.json()
        if not users:
            return None  # no match found
        return users[0]  # first matching user

    def get_user_manager_email(self, user_email: str):
        user = self.get_user_by_email(user_email)
        return user["profile"]["managerEmail"] if user else None