"""Constants for the LumeAir integration."""

from datetime import timedelta

DOMAIN = "lumeair"

CONF_DEVICE_ID = "device_id"
# True once the sensor has taken a signed request (firmware 0.7.0+): it is
# then never sent the plain access key again.
CONF_SIGNS = "signs"

# The sensor's SEN66 measures every second; every 30 s is plenty for Home
# Assistant's history and automations.
SCAN_INTERVAL = timedelta(seconds=30)

# Metrics the sensor alerts on, as /alerts names them.
ALERT_METRICS = ("co2", "pm25", "pm10", "voc")

MANUFACTURER = "LumeAir"
MODEL = "Air sensor"
