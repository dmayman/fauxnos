import paho.mqtt.client as mqtt

def on_connect(client, userdata, flags, rc, properties=None):
    print(f"Connected with result code {rc}")
    client.subscribe("fauxnos/#")

def on_message(client, userdata, msg):
    print(f"{msg.topic}: {msg.payload.decode()}")

# Use the new callback API version
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

client.connect("localhost", 1883, 60)
client.loop_forever()