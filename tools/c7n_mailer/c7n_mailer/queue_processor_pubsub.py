import base64
import json
import zlib

try:
    from google.oauth2.service_account import Credentials
    from c7n_gcp.client import Session
except ImportError as e:
    print("Using GCP Pub/Sub with c7n_mailer requires package c7n_gcp to be installed.")
    print(str(e))
    # raise Exception("Using GCP Pub/Sub with c7n_mailer requires package c7n_gcp to be installed.")

MAX_MESSAGES = 100


class MailerPubSubProcessor:
    def __init__(self, config, logger, session=None, processor=None):
        self.config = config
        self.logger = logger
        self.subscription = self.config.get("gcp_queue_url")
        self.processor = processor

        args = {}
        service_account_info = self.config.get("service_account_info")
        if service_account_info:
            with open(service_account_info, "r") as fp:
                sa_info = json.load(fp)

            # TODO find a better solution that doesn't directly reply on AWS KMS
            self.logger.info(f"Decrypting {service_account_info} with AWS KMS {processor.session}")
            try:
                CiphertextBlob = base64.b64decode(sa_info["private_key"])
                kms = processor.session.client("kms")
                pk = kms.decrypt(CiphertextBlob=CiphertextBlob)["Plaintext"].decode("utf8")
                sa_info["private_key"] = pk.replace("\\n", "\n")
            except Exception as e:
                self.logger.warning("Unable to decode/decrypt private key: " + str(e))

            creds = Credentials.from_service_account_info(sa_info)
            args["credentials"] = creds

        self.session = session or Session(**args)
        self.client = self.session.client("pubsub", "v1", "projects.subscriptions")

    def run(self):
        if not self.subscription:
            return
        self.logger.info(f"Downloading messages from {self.subscription}")

        messages = self.receive_messages()
        if len(messages) > 0:
            self.logger.info(f'Received {len(messages["receivedMessages"])} messages')
            for message in messages["receivedMessages"]:
                if self.processor:
                    self.processor.process_message(
                        self.unpack_to_dict(message["message"]["data"]),
                        messageId=messages["receivedMessages"][-1]["message"]["messageId"],
                    )
                else:
                    raise (NotImplementedError("process_message"))
                    # self.process_message(self.unpack_to_dict(message["message"]["data"]))
                # TODO ack with smaller batch, eg every 5 messages

            # Discard_date is the timestamp of the last published message in the messages list
            # and will be the date we need to seek to when we ack_messages
            discard_date = messages["receivedMessages"][-1]["message"]["publishTime"]
            self.ack_messages(discard_date)

        self.logger.info("No messages left in the GCP topic subscription.")

    def receive_messages(self):
        return self.client.execute_command(
            "pull",
            {
                "subscription": self.subscription,
                "body": {"returnImmediately": True, "max_messages": MAX_MESSAGES},
            },
        )

    def ack_messages(self, discard_datetime):
        """Acknowledge and Discard messages up to datetime using seek api command"""
        return self.client.execute_command(
            "seek", {"subscription": self.subscription, "body": {"time": discard_datetime}}
        )

    @staticmethod
    def unpack_to_dict(encoded_gcp_pubsub_message):
        return json.loads(zlib.decompress(base64.b64decode(encoded_gcp_pubsub_message)))
