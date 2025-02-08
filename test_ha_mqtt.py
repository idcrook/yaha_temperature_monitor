import errno
import time
import network
import binascii
import onewire
from onewire import OneWireError
import ds18x20
import json
import sys

import asyncio
from machine import Pin

# Third party libraries
sys.path.append("/third-party")
from mqtt_as import MQTTClient
from mqtt_as import config as mqtt_config

import config
from config import ONEWIRE_CONFIG, I2C_CONFIG, APP_CONFIG
from config import unique_device_identifier, set_mqtt_disc_dev_id, CFG_DEV
from secrets import WIFI_SSID, WIFI_PASSWORD, MQTT_SERVER, MQTT_PORT, MQTT_USER, MQTT_PASSWORD

ssid = WIFI_SSID
password = WIFI_PASSWORD
DEVNAME = APP_CONFIG.setdefault("device_name", "picow999")

# https://docs.micropython.org/en/latest/library/network.html#network.hostname
network.hostname(DEVNAME)
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
# wlan.connect(ssid, password)

mac_addr = binascii.hexlify(network.WLAN().config('mac'), ':').decode()
udi = unique_device_identifier(mac_addr)

# use name and unique device ID to generate if not specified
UNIQ_ID_PRE = APP_CONFIG.setdefault("unique_id", f"{DEVNAME}_{udi}")
print(DEVNAME, mac_addr, udi, UNIQ_ID_PRE)
set_mqtt_disc_dev_id(UNIQ_ID_PRE)
print(CFG_DEV)


# 1-wire configs
ds_pin = Pin(ONEWIRE_CONFIG.get("data_pin", 22))
ds_sensor = ds18x20.DS18X20(onewire.OneWire(ds_pin))

roms = ds_sensor.scan()
#print (roms)

sensors = ONEWIRE_CONFIG.get("sensors", {})
#print(sensors)

found_sensors = {}
for device in roms:
    s = binascii.hexlify(device)
    readable_string = s.decode('ascii')
    #print(readable_string)
    if readable_string in sensors:
        info = {}
        info['name'] = sensors[readable_string]['name']
        info['device'] = device
        found_sensors[readable_string] = info

print("found 1-wire", found_sensors)


def cvt_CtoF(temperature):
    return (9. / 5.) * temperature + 32.0

last_read_temperature_F = 0.0

if True:
    ds_sensor.convert_temp()
    time.sleep_ms(750)

    try:
        for s_id, s_params in found_sensors.items():
            device = s_params['device']
            temperature = round(ds_sensor.read_temp(device), 1)
            print(s_id, temperature, "C")
            last_read_temperature_F = cvt_CtoF(temperature)
    except OneWireError as error:
        print("error with", device)
        print(error)
        # FIXME: hopefully a transient issue but add better handling
        pass

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
    state_topic = await mqtt_discovery(client)

    #     publish1 = {
    #     "bed1_temperature": 0.0
    # }

    while True:
        n = n + 1
        ds_sensor.convert_temp()
        await asyncio.sleep_ms(750) # required by hardware!

        try:
            for s_id, s_params in found_sensors.items():
                device = s_params['device']
                temperature = round(ds_sensor.read_temp(device), 1)
                print(s_id, temperature, "C")
                last_read_temperature_F = cvt_CtoF(temperature)
        except OneWireError as error:
            print("error with", device)
            print(error)
            # FIXME: hopefully a transient issue but add better handling
            pass

        pub_payload = {
            "bed1_temperature": f"{last_read_temperature_F:.1f}"
        }
        print(n, state_topic, pub_payload)
        await client.publish(state_topic, json.dumps(pub_payload), qos=1)

        await asyncio.sleep(5)

mqtt_config['ssid'] = WIFI_SSID
mqtt_config['wifi_pw'] = WIFI_PASSWORD
mqtt_config['server'] = MQTT_SERVER

TOP_TOPIC = config.get_top_topic()

async def mqtt_discovery(client):
    srom_readable = list(found_sensors.keys())[0][-4:]
    state_topic = TOP_TOPIC + f"/sensor/{UNIQ_ID_PRE}/state"
    topic1 = TOP_TOPIC + f"/sensor/{UNIQ_ID_PRE}/{srom_readable}/config"
    payload1 = {
        "stat_t": state_topic,
        "name": f"{UNIQ_ID_PRE}-bed1_temp",
        "uniq_id": f"{UNIQ_ID_PRE}-{srom_readable}-bed1_temp",
        "dev_cla": "temperature",
        "val_tpl": "{{ value_json.bed1_temperature | is_defined }}",
        "unit_of_meas": "°F",
    }
    payload1.update(CFG_DEV)

    print(topic1)
    print(json.dumps(payload1))
    print("discover config 1")
    await client.publish(topic1, json.dumps(payload1), qos=1)
    return state_topic

# on macOS: brew install mosquitto
print(f"mosquitto_sub -h {MQTT_SERVER} -t {TOP_TOPIC}/sensor/{UNIQ_ID_PRE}/\\#")

mqtt_config["queue_len"] = 1  # Use event interface with default queue size
MQTTClient.DEBUG = True  # Optional: print diagnostic messages
client = MQTTClient(mqtt_config)

try:
    asyncio.run(main(client))
finally:
    client.close()  # Prevent LmacRxBlk:1 errors
