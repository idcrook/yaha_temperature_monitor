# import re

from device import ONEWIRE_CONFIG, I2C_CONFIG, APP_CONFIG

def unique_device_identifier(mac_addr_hexlified):
    """Use MAC address to generate a unique string for this device."""
    # Let's start with last three nibbles of MAC address
    trailing_nibbles = mac_addr_hexlified.replace(":", "")[-3:]
    return trailing_nibbles

#TOP_TOPIC= 'sandbox'
TOP_TOPIC= 'homeassistant'

SWVER = "0.1"
HWVER = "0.1"
MDL   = "Pico temp"
MDL_ID = "picow_ds_bme280"
MNF    = "idcrook-labs"
brand  = "seedomatic"
NAME = f"{brand} {MDL}"

CFG_DEV = {
    "sw": SWVER,
    "hw": HWVER,
    "mdl": MDL,
    "mdl_id": MDL_ID,
    "mf": MNF,
    "name": NAME,
    "ids": [],
}

def set_mqtt_disc_dev_id(identifiers):
    if isinstance(identifiers, list):
        CFG_DEV['ids'] = identifiers
    elif isinstance(identifiers, tuple):
        CFG_DEV['ids'] = list(*identifiers)
    else:
        CFG_DEV['ids'] = [identifiers]

def get_top_topic():
    """Top topic to use for Home Assistant MQTT."""
    return TOP_TOPIC
