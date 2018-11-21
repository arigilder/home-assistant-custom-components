# Shabbat Times Sensor
**Component Type** : `platform`</br>
**Platform Name** : `shabbat_times`</br>
**Domain Name** : `sensor`</br>
**Component Script** : [`custom_components/sensor/shabbat_times.py`](custom_components/sensor/shabbat_times.py)</br>

[Community Discussion](https://community.home-assistant.io/t/get-shabbat-times-from-hebcal-api-custom-sensor/32429)</br>

#### Component Description
The component works in a similar manner as the *rest* type sensor, it send an api request towards [Hebcal's Shabbat Times API](https://www.hebcal.com/home/197/shabbat-times-rest-api) and retrieves the **upcoming** or **current** Shabbat start and end date and time, and sets them as attributes within a created sensor.</br>
The component can create multiple sensors for multiple cities around the world, the selected city is identified by its geoname which can selected [here](https://github.com/hebcal/dotcom/blob/master/hebcal.com/dist/cities2.txt).

**Table Of Contents**
- [Installation](#installation)
- [Configuration](#configuration)
  - [Configuration Keys](#configuration-keys)
- [States](#states)
- [Special Notes](#special-notes)

## Installation

- Copy files [`custom_components/sensor/shabbat_times.py`](custom_components/sensor/shabbat_times.py) and [`custom_components/sensor/shabbat_times_util.py`](custom_components/sensor/shabbat_times_util.py) to your `ha_config_dir/custom_components/sensor` directory.
- Configure like instructed in the Configuration section below.
- Restart Home-Assistant.

## Configuration
To use this component in your installation, add the following to your `configuration.yaml` file:

```yaml
# Example configuration.yaml

sensor:
  - platform: shabbat_times
    geonames: "IL-Haifa,IL-Rishon LeZion"
    candle_lighting_minutes_before_sunset: 0
    havdalah_minutes_after_sundown: 40
```
This configuration will create two sensors:
- *sensor.shabbat_times_il_haifa*
- *sensor.shabbat_times_il_rishon_lezion*

Each sensor will have its own set of attributes:
- *shabbat_start*
- *shabbat_end*

Which will be calculated based on configuration optional values **candle_lighting_minutes_before_sunset** and **havdalah_minutes_after_sundown**.
These attributes are available for use within templates like so:
- *{{ states.sensor.shabbat_times_il_haifa.attributes.shabbat_start }}* will show the Shabbat start date and time in Haifa.
- *{{ states.sensor.shabbat_times_il_rishon_lezion.attributes.shabbat_end }}* will show the Shabbat end date and time in Rishon Lezion.

### Configuration Keys
- **geonames** (*Required*): A valid geoname selected [here](https://github.com/hebcal/dotcom/blob/master/hebcal.com/dist/cities2.txt), multiple geonames separated by a comma is allowed.
- **candle_lighting_minutes_before_sunset** (*Optional*): Minutes to subtract from the sunset time for calculation of the candle lighting time. (default = 30)
- **havdalah_minutes_after_sundown** (*Optional*): Minutes to add to the sundown time for calculation of the Shabbat end time. (default = 42)
- **scan_interval** (*Optional*): Seconds between updates. (default = 60)

## States
- *Awaiting Update*: the sensor hasn't been updated yet.
- *Working*: the sensor is being updated at this moment.
- *Error...*: the api has encountered an error.
- *Updated*: the sensor has finished updating.

## "Shabbat Mode" Sensors
A particularly useful application of this sensor is to be able to run automations when Shabbat/Yom Tov begins/ends. There are a few ways to do this, but a particularly handy way is to use a template sensor. This can be implemented as a regular sensor or as a binary sensor, but this example shows a regular sensor. Be sure to replace YOUR_SHABBAT_TIMES with the actual name of your shabbat_times sensor:

```yaml
sensor:
  - platform: template
    sensors:
      shabbat_mode:
        friendly_name: Shabbat Mode
        value_template: >-
          {%- set now_time = as_timestamp(strptime(states.sensor.date__time.state, "%Y-%m-%d, %H:%M")) %}
          {%- if not is_state("sensor.YOUR_SHABBAT_TIMES", "Updated") -%}
            unknown
          {%- elif now_time >= as_timestamp(state_attr("sensor.YOUR_SHABBAT_TIMES", "shabbat_start"))
             and now_time < as_timestamp(state_attr("sensor.YOUR_SHABBAT_TIMES", "shabbat_end")) -%}
            on
          {%- else -%}
            off
          {%- endif -%}
```

Defining the template sensor this way has the benefit that if your HomeAssistant server reboots on Shabbat, the Shabbat Mode sensor will be up-to-date.

One additional requirement for this template sensor is that you define the date__time sensor. That is because now() does not update properly in template sensors; for details see this [forum post](https://community.home-assistant.io/t/how-to-replace-entity-id-in-template-sensors/40540/2?u=kallb123). Here's an example on how to configure that:

```yaml
sensor:
  - platform: time_date
    display_options:
      - 'time'
      - 'date'
      - 'date_time'
```

## Automations

If you've set up a "Shabbat Mode" sensor as described above, it's quite easy to use it to build an automation. Here's an example:

```yaml
automation:
  - alias: Shabbat Mode On
    trigger:
      entity_id: sensor.shabbat_mode
      from: 'off'
      platform: state
      to: 'on'
    action:
    - service: notify.notify
      data:
        message: 'Shabbat mode is on'
    - service: tts.google_say
      entity_id: media_player.kitchen_speaker
      data:
        message: "It's candle lighting time. Shabbat Shalom!"
    - service: switch.turn_off
      data:
        entity_id: switch.garage_floodlight
    - service: scene.turn_on
      data:
        entity_id: scene.dining
    - service: light.turn_off
      data:
        entity_id: light.master_bedroom_main_lights
```

TODO(arigilder): Describe more advanced hysteresis via input_booleans.

## Special Notes
- The sensors will always show the date and time for the next Shabbat, unless the Shabbat is now, and therefore the sensors will show the current Shabbat date and time.
