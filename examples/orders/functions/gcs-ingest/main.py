import functions_framework


@functions_framework.cloud_event
def handle(event):
    print(f"new object: {event.data.get('bucket')}/{event.data.get('name')}")
