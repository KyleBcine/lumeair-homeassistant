# LumeAir for Home Assistant

See your LumeAir air-quality sensors in Home Assistant: CO₂, particles
(PM1, PM2.5, PM4, PM10), VOC and NOx indexes, temperature, humidity,
pressure, an overall air-quality rating, and the sensor's own alerts. It
also installs the sensors' firmware updates.

Your readings stay on your home network. Home Assistant reads each sensor
directly every 30 seconds; nothing about your sensors goes through the
internet or a LumeAir server. The only thing it fetches from the internet is
the public list of firmware releases (see [Firmware updates](#firmware-updates)).

## Install

You need Home Assistant 2026.3 or later, on the same network as your
sensors.

1. Install **LumeAir** from Home Assistant's Marketplace (Settings ›
   Marketplace; on versions before 2026.11, HACS):

   [![Open in your Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=KyleBcine&repository=lumeair-homeassistant&category=integration)

   Until LumeAir is in the Marketplace's main catalog, add this repository
   as a custom repository first: ⋮ › Custom repositories, paste
   `https://github.com/KyleBcine/lumeair-homeassistant`, category
   Integration.
2. Restart Home Assistant.
3. Home Assistant finds your sensors by itself: Settings › Devices &
   services shows **Discovered: LumeAir-XXXXXX** for each one. Tap
   **Add**.
4. Paste the sensor's **pair code**. In the LumeAir app, go to Settings ›
   Home Assistant and tap **Copy pair code** next to the sensor.

The device takes the room name you gave the sensor in the app.

To add a sensor Home Assistant didn't find, use **Add integration ›
LumeAir** and paste its pair code; the code includes its address.

## What you get

| Entity | Notes |
|---|---|
| Air quality | Good, Moderate, Poor, Unhealthy, Very unhealthy or Hazardous: the worst of CO₂, particles and VOC, rated the same way as the app |
| Carbon dioxide | ppm |
| PM1, PM2.5, PM4, PM10 | µg/m³; unknown for the first few seconds after the sensor starts |
| VOC index | Relative to the room's usual air, where about 100 is normal; unknown for about a minute after the sensor starts |
| NOx index | Nitrogen oxides (gas stoves, heaters, traffic), relative to the room's usual air, where 1 is normal; unknown for the first minutes after the sensor starts. Not part of the air-quality rating, as in the app by default |
| Temperature, Humidity, Atmospheric pressure | |
| CO₂ alert, PM2.5 alert, PM10 alert, VOC alert | On while the reading is above your alert threshold. The thresholds are the ones set in the LumeAir app |
| Firmware | The sensor's firmware version, and the latest release; see below |
| Wi-Fi signal | Diagnostic, disabled by default |

Use them in dashboards, history, and automations, for example turning on a
fan when the CO₂ alert turns on.

## Firmware updates

When a new LumeAir firmware release is out, it shows under **Settings ›
Updates** for each sensor, with what changed. Tap **Install**: Home
Assistant shows the progress while the sensor downloads the release,
installs it and restarts, about two minutes. Home Assistant never installs
anything by itself, unless you set up an automation to.

- **Safe to try:** the sensor checks that each release is signed by
  LumeAir before installing it, and downloads it itself over HTTPS. If a new
  version doesn't work, the sensor goes back to the earlier one by itself.
- **Checking for releases:** every 6 hours Home Assistant downloads the
  public release list from the LumeAir website,
  `kylebcine.github.io/lumeair-site/firmware/manifest.json`. Nothing about
  your sensors is sent.
- **"Checking that the new version works":** right after an update, a
  sensor won't take another one for a few minutes.
- The LumeAir app offers the same updates; use whichever you like.

## Good to know

- **Pair code:** it holds the sensor's access key, which gives full access
  to the sensor. Home Assistant only reads it. Keep it private.
- **The key stays private:** the access key never crosses your network.
  Home Assistant signs each request with it instead of sending it, so
  nobody watching your network can copy the key. A signature covers only
  its own request and expires within a minute, and one that changes the
  sensor's settings works only once.
- **New address:** if your router gives the sensor a new IP address, Home
  Assistant follows it automatically.
- **Sensor set up again:** a sensor that's set up again in the app gets a new
  access key. Home Assistant then asks you to paste its new pair code.
- **Unavailable:** the sensor is unplugged or off the network. Its entities
  come back on their own.
- **Diagnostics:** the download leaves out the access key and addresses.

## Development

```
python -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

The sensor's local API is documented in the LumeAir firmware's
`docs/PROTOCOL.md`.

## License

MIT
