"""Cloud Run function (CloudEvents). Triggers are declared in product.yaml."""
import functions_framework


@functions_framework.cloud_event
def handle(event):
    print(f"orders/gcs-ingest received {event['type']}: {event.data}")
