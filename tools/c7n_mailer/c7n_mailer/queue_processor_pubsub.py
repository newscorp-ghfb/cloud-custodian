import base64
import json
import zlib

try:
    from c7n_gcp.client import Session
except ImportError:
    raise Exception("Using GCP Pub/Sub with c7n_mailer requires package c7n_gcp to be installed.")

MAX_MESSAGES = 100


class MailerPubSubProcessor:
    def __init__(self, config, logger, session=None, processor=None):
        self.config = config
        self.logger = logger
        self.subscription = self.config.get("gcp_queue_url")
        self.session = session or Session()
        self.client = self.session.client("pubsub", "v1", "projects.subscriptions")
        self.processor = processor

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
