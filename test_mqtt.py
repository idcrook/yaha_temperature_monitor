import errno
import time
import network
import binascii
import json
import sys

import asyncio
from machine import Pin, I2C

# Third party libraries
sys.path.append("/third-party")
from mqtt_as import MQTTClient
from mqtt_as import config as mqtt_config

from config import ONEWIRE_CONFIG, I2C_CONFIG, APP_CONFIG, unique_device_identifier
from secrets import WIFI_SSID, WIFI_PASSWORD, MQTT_SERVER, MQTT_PORT, MQTT_USER, MQTT_PASSWORD

ssid = WIFI_SSID
password = WIFI_PASSWORD
DEVNAME = APP_CONFIG.setdefault("device_name", "picow999")

# https://docs.micropython.org/en/latest/library/network.html#network.hostname
network.hostname(DEVNAME)
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(ssid, password)

mac = binascii.hexlify(network.WLAN().config('mac'), ':').decode()
udi = unique_device_identifier(mac)

# use name and unique device ID to generate if not specified
UNIQ_ID_PRE_ = APP_CONFIG.setdefault("unique_id", f"{DEVNAME}_{udi}_")
print(DEVNAME, mac, udi, UNIQ_ID_PRE_)

# # Wait for connect or fail
# max_wait = 12
# while max_wait > 0:

#     if wlan.status() < 0 or wlan.status() >= 3:
#         break
#     max_wait -= 1
#     print('waiting for connection...')
#     time.sleep(1)

# # Handle connection error
# if wlan.status() != 3:
#     raise RuntimeError('network connection failed')
# else:
#     print('connected')

# status = wlan.ifconfig()
# print('ip = ' + status[0])

mqtt_config['ssid'] = WIFI_SSID
mqtt_config['wifi_pw'] = WIFI_PASSWORD
mqtt_config['server'] = MQTT_SERVER

async def messages(client):  # Respond to incoming messages
    # If MQTT V5is used this would read
    # async for topic, msg, retained, properties in client.queue:
    async for topic, msg, retained in client.queue:
        print(topic.decode(), msg.decode(), retained)

async def up(client):  # Respond to connectivity being (re)established
    while True:
        await client.up.wait()  # Wait on an Event
        client.up.clear()
        # await client.subscribe('foo_topic', 1)  # renew subscriptions

async def main(client):
    await client.connect()
    for coroutine in (up, messages):
        asyncio.create_task(coroutine(client))
    n = 0
    while True:
        await asyncio.sleep(5)
        print('publish', n)
        # If WiFi is down the following will pause for the duration.
        await client.publish(f"{UNIQ_ID_PRE_}result", '{}'.format(n), qos=1)
        n += 1

# on macOS: brew install mosquitto
print(f"mosquitto_sub -h {MQTT_SERVER} -t {UNIQ_ID_PRE_}result")

mqtt_config["queue_len"] = 1  # Use event interface with default queue size
MQTTClient.DEBUG = True  # Optional: print diagnostic messages
client = MQTTClient(mqtt_config)
try:
    asyncio.run(main(client))
finally:
    client.close()  # Prevent LmacRxBlk:1 errors
