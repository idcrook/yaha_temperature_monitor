# micropython program to publish sensor data to MQTT for use by Home Assistant
#
# See TODO.md

# import errno
import time
import network
import binascii
import json
import sys
from collections import OrderedDict

import asyncio
import ds18x20
import onewire
from onewire import OneWireError
from ssd1306 import SSD1306_I2C
import machine
from machine import Pin, I2C, WDT

# Third party libraries
sys.path.append("/third-party")
from mqtt_as import MQTTClient
from mqtt_as import config as mqtt_config
from micropython_bmpxxx import bmpxxx

import config
from config import ONEWIRE_CONFIG, I2C_CONFIG, APP_CONFIG
from config import unique_device_identifier, set_mqtt_disc_dev_id, CFG_DEV
from secrets import WIFI_SSID, WIFI_PASSWORD, MQTT_SERVER #, MQTT_PORT, MQTT_USER, MQTT_PASSWORD

ssid = WIFI_SSID
password = WIFI_PASSWORD
DEVNAME = APP_CONFIG.setdefault("device_name", "picow999")
ONBOARD_LED = APP_CONFIG.setdefault("blink_onboard_led", False)
LED_PIN = Pin('LED', Pin.OUT)

# https://docs.micropython.org/en/latest/library/machine.html#machine.reset_cause
# https://docs.micropython.org/en/latest/library/machine.html#machine-constants
reset_cause = machine.reset_cause()
if reset_cause == machine.PWRON_RESET:
    print("Starting from PWRON_RESET")
# elif reset_cause == machine.HARD_RESET:
#     print("Starting from HARD_RESET (system initiated)")
elif reset_cause == machine.WDT_RESET:
    print("Starting from WDT_RESET (Watchdog Timer)")
# elif reset_cause == machine.SOFT_RESET:
#     print("Starting from micropython Soft Reset")
# elif reset_cause == machine.DEEPSLEEP_RESET:
#     print("Starting from Deep Sleep event")
else:
    print(f"Starting from unknown reset type: {reset_cause}")

# https://docs.micropython.org/en/latest/library/network.html#network.hostname
network.hostname(DEVNAME)
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(ssid, password)

mac = binascii.hexlify(network.WLAN().config('mac'),':').decode()
udi = unique_device_identifier(mac)

# use name and unique device ID to generate if not specified
UNIQ_ID_PRE = APP_CONFIG.setdefault("unique_id", f"{DEVNAME}_{udi}")
print(DEVNAME, mac, udi, UNIQ_ID_PRE)
set_mqtt_disc_dev_id(UNIQ_ID_PRE)
print(CFG_DEV)

########################################################################
#  Detect devices from the config files
SENSOR_STATES_TO_USE = {
    "bed1_temperature": None,
    "bed2_temperature": None,
    "bed3_temperature": None,
    "humidity_ambient": None,
    "temperature_ambient": None
}

def _get_ds_state_name(name):
    return  f"{name}_temperature"

########################################################################
# 1-wire configs
ds_pin = Pin(ONEWIRE_CONFIG.get("data_pin", 22))
DS_SENSOR_IFC = ds18x20.DS18X20(onewire.OneWire(ds_pin))

DS_SENSORS = ONEWIRE_CONFIG.get("sensors", {})
DS_SENSORS_FOUND = {}

roms = DS_SENSOR_IFC.scan()
for device in roms:
    s = binascii.hexlify(device)
    readable = s.decode('ascii')
    #print(readable)
    if readable in DS_SENSORS:
        info = {}
        info['name'] = DS_SENSORS[readable]['name']
        info['object_id'] = readable[-4:]
        info['device_type'] = 'ds18b20'
        info['interface'] = device
        DS_SENSORS_FOUND[readable] = info
        state_to_use = _get_ds_state_name(info['name'])
        SENSOR_STATES_TO_USE[state_to_use] = info['object_id']

print ("found 1-wire(s)", DS_SENSORS_FOUND)

if True:
    DS_SENSOR_IFC.convert_temp()
    time.sleep_ms(750)

    try:
        for s_id, s_params in DS_SENSORS_FOUND.items():
            device = s_params['interface']
            temperature = round(DS_SENSOR_IFC.read_temp(device), 1)
            print(s_id, temperature, "C")
    except OneWireError as error:
        print("error with", device)
        print(error)
        # FIXME: hopefully a transient issue but add better handling
        pass

########################################################################
# I2C configs
i2c_bus_info = I2C_CONFIG['bus']
i2c_bus = i2c_bus_info['bus_number']
i2c_sda = Pin(i2c_bus_info['sda_pin'])
i2c_scl = Pin(i2c_bus_info['scl_pin'])

i2c = I2C(i2c_bus, sda=i2c_sda, scl=i2c_scl)

# I2C sensors config - bme280
I2C_SENSORS = I2C_CONFIG.get('sensors', [])
I2C_SENSORS_FOUND = {}

for sensor in I2C_SENSORS:
    for s_type, s_params in sensor.items():
        if s_type == 'bme280':
            address = s_params.setdefault('address', 0x77)
            # FIXME: Handle RuntimeError if not found, e.g.
            # RuntimeError: BME280 sensor not found at specified I2C address (0x77).
            this = bmpxxx.BME280(i2c, address=address)
            info = {}
            info['device_type'] = s_type
            info['address'] = address
            info['object_id'] = 'amb'
            info['interface'] = this
            I2C_SENSORS_FOUND[address] = info
            sensor_to_use = 'temperature_ambient'
            SENSOR_STATES_TO_USE[sensor_to_use] = "ambT"
            sensor_to_use = 'humidity_ambient'
            SENSOR_STATES_TO_USE[sensor_to_use] = "ambH"


for i2c_address, s_params in I2C_SENSORS_FOUND.items():
    sensor_interface = s_params['interface']
    name = s_params['device_type']
    if name == 'bme280':
        temperature = sensor_interface.temperature
        humidity = sensor_interface.humidity
        dewpoint = sensor_interface.dew_point
        print(f"{name}:> {temperature:.1f}C rel humid:{humidity:.1f}% dewpt:{dewpoint:.1f}C")

########################################################################
# I2C displays config
I2C_DISPLAYS = []
I2C_DISPLAYS_FOUND = False
i2c_displays = I2C_CONFIG.get('displays', [])

I2C_USE_DISPLAYS = APP_CONFIG.get('display_temperature_readings', False)

# assume zero or one (no more) display for now
if len(i2c_displays) and I2C_USE_DISPLAYS:
    display_info = i2c_displays[0]
    #print(display_info)
    for d_type, d_params in display_info.items():
        address = d_params['address']
        h = d_params['height']
        w = d_params['width']
        skip_down_pixels = d_params['second_line_padding']
        display = SSD1306_I2C(w, h, i2c)
        display.fill(0)
        display.text(DEVNAME, 0, 0, 1)
        display.text(UNIQ_ID_PRE, 0, 12 + skip_down_pixels, 1)
        display.show()
        info = {'device_type': d_type, 'interface': display,
                'height': h, 'width': w, 'pad_after_first_line': skip_down_pixels}
        info.update(d_params)
        I2C_DISPLAYS_FOUND = True
        I2C_DISPLAYS.append(info)

print("displays found:", I2C_DISPLAYS)
if I2C_DISPLAYS_FOUND:
    time.sleep(2)
    # do not clear - to aid in reset debugging
    if False:
        I2C_DISPLAYS[0]['interface'].fill(0)
        I2C_DISPLAYS[0]['interface'].show()

# require at least one DS probe sensor to have been found
if not DS_SENSORS_FOUND:
    print("ERROR: No 1-wire sensors found.")
    print(f"Looked for {list(DS_SENSORS.keys())}")
    if I2C_DISPLAYS_FOUND:
        I2C_DISPLAYS[0]['interface'].fill(0)
        I2C_DISPLAYS[0]['interface'].text("ERROR ERROR", 0, 0, 1)
        I2C_DISPLAYS[0]['interface'].text("No 1-W DS sensor", 0, 12, 1)
        I2C_DISPLAYS[0]['interface'].show()

    if ONBOARD_LED:
        for i in range(15):
            LED_PIN(True)
            time.sleep_ms(150)
            LED_PIN(False)
            time.sleep_ms(850)
    # FIXME: put something better here
    sys.exit(1)


### End accessory detection

def _display_readings(values):
    """Show readings on connected display."""
    #print(values)
    display = I2C_DISPLAYS[0]['interface']
    width = I2C_DISPLAYS[0]['width']
    # height = I2C_DISPLAYS[0]['height'] # use for height check?
    second_line_padding = I2C_DISPLAYS[0]['pad_after_first_line']

    line_height = 12     # TODO: Make this configuratble?
    total_columns = 2
    reading_width = width // total_columns

    display.fill(0)
    line_no = 0
    column_no = 0
    for short_name, value in values.items():
        if short_name.startswith('bed'):
            s = f"{short_name[-2:]} {value:.1f}F"
        else:
            s = f"{short_name}{value}"
            if  short_name.startswith('amb') and column_no != 0:
                # start new line
                line_no = line_no + 1
                column_no = 0

        x = column_no * reading_width
        y = line_no * line_height
        #print(f"{y:2d} {x:3d}|{s}")
        ypadding = second_line_padding if line_no >= 1 else 0
        display.text(s, x, y+ypadding, 1)
        (line_no, column_no) = divmod (line_no * total_columns + column_no + 1,
                                       total_columns)
    display.show()

########################################################################


print(SENSOR_STATES_TO_USE)

def cvt_CtoF(temperature):
    return round((9. / 5.) * temperature + 32.0, 1)

def _json_dumps(s):
    return bytes(json.dumps(s, separators=(',', ':')), 'utf-8')

async def messages(client):  # Respond to incoming messages
    ha_status_topic = TOP_TOPIC + "/status"
    # If MQTT V5is used this would read
    # async for topic, msg, retained, properties in client.queue:
    async for topic, msg, retained in client.queue:
        t = topic.decode()
        m = msg.decode()
        print(t, m)
        if t == ha_status_topic:
            if m == 'online':
                print(f"Received HA status message {m}")
                # re-discover since we received MQTT birth message
                state_topic = await mqtt_discovery(client)
                print(f"sensor state in: {state_topic}")
            else:
                print(f"Received HA status message: {m}")
                # Should anything else be done here??

async def up(client):  # Respond to connectivity being (re)established
    ha_status_topic = TOP_TOPIC + "/status"
    while True:
        await client.up.wait()  # Wait on an Event
        client.up.clear()
        # await client.subscribe('foo_topic', 1)  # renew subscriptions
        await client.subscribe(ha_status_topic, 1)

async def sleep_for_ms(n: int, wdt):
    """Sleep for N milliseconds, feeding watchdog."""
    i = 2000
    do_heartbeat = False
    if ONBOARD_LED and APP_CONFIG.get("heartbeat_onboard_led", True):
        do_heartbeat = True
        duty_cycle = 5
        period = 2000

    while i <= n:
        # should be fine as long as this loop duration (1000 ms) is much less than WDT
        if do_heartbeat:
            for x in range(i // period):
                LED_PIN.value(True)
                await asyncio.sleep_ms(duty_cycle)
                LED_PIN.value(False)
                await asyncio.sleep_ms(period - duty_cycle)
        else:
            await asyncio.sleep_ms(i)
        #print("t", end="")

        wdt.feed()
        # handle a non-integer of seconds
        if n < i:
            break
        else:
            n = n - i

    await asyncio.sleep_ms(n)
    # shouldn't hurt :)
    wdt.feed()

async def main(client):
    # Wi-Fi network starts here, using mqtt_as capability
    connect_attempts = 0
    MAX_ATTEMPTS = 10
    while connect_attempts < MAX_ATTEMPTS:
        try:
            connect_attempts = connect_attempts + 1
            print(f"connection attempt {connect_attempts}")
            if connect_attempts == 1:
                await client.connect(quick=True)
            else:
                await client.connect()
            break
        # OSError: Wi-Fi connect timed out
        except OSError as eos:
            print(f"OSError on connect attempt {connect_attempts}")
            await asyncio.sleep(2)
        except Exception as e:
            raise
            # FIXME: add any other proper error handling here

    if connect_attempts == MAX_ATTEMPTS:
        machine.reset()

    for coroutine in (up, messages):
        asyncio.create_task(coroutine(client))

    # Start Watchdog Timer (WDT)
    if use_hardware_watchdog := APP_CONFIG.get("enable_hardware_watchdog", False):
        print("using HARDWARE watchdog timer")
        # On rp2040 devices, the maximum timeout is 8388 ms.
        wdt = WDT(timeout=8300)
    else:
        print("using DUMMY watchdog timer")
        wdt = type('WDT', (object,), { "feed": lambda *self: None })

    state_topic = await mqtt_discovery(client)
    print(f"sensor state in: {state_topic}")

    n = 0
    display_values = OrderedDict([])
    DS_WAIT_MS = 750
    sleep_duration_ms = int(APP_CONFIG.get('sensor_read_interval_seconds', 30) * 1000) - DS_WAIT_MS
    while True:
        n = n + 1
        state_update = {}
        display_values['N'] = f"={n:>5}"

        if ONBOARD_LED: LED_PIN.value(True)
        wdt.feed()

        DS_SENSOR_IFC.convert_temp()
        time.sleep_ms(DS_WAIT_MS) # required for DS sensors

        if ONBOARD_LED: LED_PIN.value(False)
        wdt.feed()

        try:
            for s_id, s_params in DS_SENSORS_FOUND.items():
                device = s_params['interface']
                name = s_params['name']
                state_name = _get_ds_state_name(name)
                temperature = DS_SENSOR_IFC.read_temp(device)
                # print(s_id, name, temperature, "C")
                tF = cvt_CtoF(temperature)
                state_update[state_name] = tF
                display_values[name] = tF
        except OneWireError as error:
            print("error with", device)
            print(error)
            # FIXME: hopefully a transient issue but add better handling
            pass

        for i2c_address, s_params in I2C_SENSORS_FOUND.items():
            sensor_interface = s_params['interface']
            name = s_params['device_type']
            if name == 'bme280':
                temperature = round(sensor_interface.temperature, 1)
                humidity = round(sensor_interface.humidity, 1)
                # print(f"{name}:> {temperature:.1f}C rel humid:{humidity:.1f}% dewpt:{dewpoint:.1f}C")
                tF = cvt_CtoF(temperature)
                state_update['temperature_ambient'] = tF
                state_update['humidity_ambient'] = humidity
                display_value = f" {tF:.1f}F {humidity:.0f}%"
                display_values['amb'] = display_value


        pub_payload = _json_dumps(state_update)
        #print(n, state_topic, pub_payload)
        await client.publish(state_topic, pub_payload, qos=1)
        if I2C_DISPLAYS_FOUND:
            _display_readings(display_values)
        else:
            print(list(display_values.items()))

        if use_hardware_watchdog:
            await sleep_for_ms(sleep_duration_ms, wdt)
        else:
            await asyncio.sleep_ms(sleep_duration_ms)


async def mqtt_discovery(client):

    state_topic = TOP_TOPIC + f"/sensor/{UNIQ_ID_PRE}/state"

    first_ds = True
    for s_id, s_params in DS_SENSORS_FOUND.items():
        readable = s_params['object_id']
        name =  s_params['name']
        state_name = _get_ds_state_name(name)
        topic = TOP_TOPIC + f"/sensor/{UNIQ_ID_PRE}/{readable}/config"
        payload = {
            "name": f"{name}_temp",
            "device_class": "temperature",
            "state_topic": state_topic,
            "unit_of_measurement": "°F",
            "suggested_display_precision": 1,
            "expire_after": 60 * 3, # TODO: make configurable
            "force_update": True,
            "value_template": f"{{{{ value_json.{state_name} | is_defined }}}}",
            "unique_id": f"{UNIQ_ID_PRE}_{readable}_{name}_temp",
            "device" : CFG_DEV,
        }
        if first_ds:
            first_ds = False
        else:
            payload['device'] = {}
            payload['device']['ids'] = CFG_DEV['ids']

        message = _json_dumps(payload)
        #print(topic, message)
        await client.publish(topic, message, qos=1)

    for i2c_address, s_params in I2C_SENSORS_FOUND.items():
        name = s_params['device_type']
        address = s_params['address']
        valueT = 'temperature_ambient'
        topicT = TOP_TOPIC + f"/sensor/{UNIQ_ID_PRE}/ambT/config"
        payloadT = {
            "stat_t": state_topic,
            "name": "amb_temp",
            "uniq_id": f"{UNIQ_ID_PRE}_{name}_{address}_amb_temp",
            "dev_cla": "temperature",
            "val_tpl": f"{{{{ value_json.{valueT} | is_defined }}}}",
            "unit_of_meas": "°F",
            "device" : {  "ids":  CFG_DEV['ids']  },
        }
        messageT = _json_dumps(payloadT)
        #print(topicT, messageT)
        await client.publish(topicT, messageT, qos=1)

        valueH = 'humidity_ambient'
        topicH = TOP_TOPIC + f"/sensor/{UNIQ_ID_PRE}/ambH/config"
        payloadH = {
            "stat_t": state_topic,
            "name": "amb_humid",
            "uniq_id": f"{UNIQ_ID_PRE}_{name}_{address}_amb_humid",
            "dev_cla": "humidity",
            "val_tpl": f"{{{{ value_json.{valueH} | is_defined }}}}",
            "unit_of_meas": "%",
            "device" : {  "ids":  CFG_DEV['ids']  },
        }
        messageH = _json_dumps(payloadH)
        #print(topicH, messageH)
        await client.publish(topicH, messageH, qos=1)


    return state_topic

TOP_TOPIC = config.get_top_topic()

mqtt_config['ssid'] = WIFI_SSID
mqtt_config['wifi_pw'] = WIFI_PASSWORD
mqtt_config['server'] = MQTT_SERVER
mqtt_config["queue_len"] = 1  # Use event interface with default queue size

if mqtt_client_debug := APP_CONFIG.get("mqtt_client_debug", True):
    print("enabling mqtt client DEBUG messages")
    MQTTClient.DEBUG = True  # Optional: print diagnostic messages
else:
    MQTTClient.DEBUG = False

client = MQTTClient(mqtt_config)

# on macOS: brew install mosquitto
print(f"mosquitto_sub -h {MQTT_SERVER} -t {TOP_TOPIC}/sensor/{UNIQ_ID_PRE}/\\#")

try:
    asyncio.run(main(client))
finally:
    client.close()  # Prevent LmacRxBlk:1 errors
