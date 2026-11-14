"""Cloud Run function (CloudEvents). Triggers are declared in product.yaml."""
import functions_framework


@functions_framework.cloud_event
def handle(event):
    print(f"__PRODUCT__/__NAME__ received {event['type']}: {event.data}")
