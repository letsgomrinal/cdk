"""Worker pool: long-running Pub/Sub pull consumer. Set SUBSCRIPTION in product.yaml env
and grant it under access.subscribe."""
import os

from google.cloud import pubsub_v1


def handle(message):
    print(f"orders/email-sender got {message.message_id}: {message.data[:200]!r}")
    message.ack()


def main():
    subscription = os.environ["SUBSCRIPTION"]  # projects/<p>/subscriptions/<s>
    subscriber = pubsub_v1.SubscriberClient()
    future = subscriber.subscribe(subscription, callback=handle)
    print(f"listening on {subscription}")
    future.result()


if __name__ == "__main__":
    main()
