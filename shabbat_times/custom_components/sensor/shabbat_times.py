import asyncio
import datetime
import logging
import json
import requests
import voluptuous as vol
from collections import namedtuple
from custom_components.sensor import shabbat_times_util as shabbat
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_SCAN_INTERVAL, CONF_LONGITUDE, CONF_LATITUDE, CONF_NAME, CONF_TIME_ZONE
from homeassistant.util import Throttle
from homeassistant.helpers.entity import Entity
#from homeassistant.helpers.restore_state import async_get_last_state
from homeassistant.helpers.restore_state import RestoreEntity
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Shabbat Time"
HAVDALAH_MINUTES = 'havdalah_minutes_after_sundown'
CANDLE_LIGHT_MINUTES = 'candle_lighting_minutes_before_sunset'

HAVDALAH_DEFAULT = 42
CANDLE_LIGHT_DEFAULT = 30
SCAN_INTERVAL = datetime.timedelta(minutes=60)

SHABBAT_START = 'shabbat_start'
SHABBAT_END = 'shabbat_end'
LAST_UPDATE = 'last_update'
TITLE = 'title'
HEBREW_TITLE = 'hebrew_title'

SENSOR_ATTRIBUTES = [HAVDALAH_MINUTES, CANDLE_LIGHT_MINUTES,
  SHABBAT_START, SHABBAT_END, LAST_UPDATE, TITLE, HEBREW_TITLE]

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Inclusive(CONF_LATITUDE, 'coordinates',
                  'Latitude and longitude must exist together'): cv.latitude,
    vol.Inclusive(CONF_LONGITUDE, 'coordinates',
'Latitude and longitude must exist together'): cv.longitude,
    vol.Optional(CONF_TIME_ZONE): cv.time_zone,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(HAVDALAH_MINUTES, default=HAVDALAH_DEFAULT): int,
    vol.Optional(CANDLE_LIGHT_MINUTES, default=CANDLE_LIGHT_DEFAULT): int,
    vol.Optional(CONF_SCAN_INTERVAL, default=SCAN_INTERVAL): cv.time_period
})

def setup_platform(hass, config, add_devices, discovery_info=None):
    havdalah = config.get(HAVDALAH_MINUTES)
    candle_light = config.get(CANDLE_LIGHT_MINUTES)
    name = config.get(CONF_NAME)
    latitude = config.get(CONF_LATITUDE, hass.config.latitude)
    longitude = config.get(CONF_LONGITUDE, hass.config.longitude)    
    timezone = config.get(CONF_TIME_ZONE, hass.config.time_zone)

    add_devices([ShabbatTimes(hass, latitude, longitude, timezone, name, havdalah, candle_light)])


class ShabbatTimes(RestoreEntity, Entity):

    def __init__(self, hass, latitude, longitude, timezone, name, havdalah, candle_light):
        self._hass = hass
        self._latitude = latitude
        self._longitude = longitude
        self._timezone = timezone
        self._name = "Shabbat Times " + name
        self._havdalah = havdalah
        self._candle_light = candle_light
        self._state = 'Awaiting Update'
        self._shabbat_start = None
        self._shabbat_end = None
        self._last_update = None
        self._title = None
        self._hebrew_title = None


    @asyncio.coroutine
    def async_added_to_hass(self):
      """ Restore original state."""
      old_state = yield from self.async_get_last_state()
      _LOGGER.info('Old state: ' + str(old_state))
      if (not old_state or 
          old_state.attributes[LAST_UPDATE] is None or 
          old_state.attributes[SHABBAT_START] is None or
          old_state.attributes[SHABBAT_END] is None):
        self.update()
        return

      if shabbat.parse_time(old_state.attributes[SHABBAT_END], False) < datetime.datetime.now():
        _LOGGER.error("Current time is newer than shabbat end time. Updating.")
        self.update()
        return

      params = {key: old_state.attributes[key] for key in SENSOR_ATTRIBUTES
                if key in old_state.attributes}
      _LOGGER.debug('params: ' + str(params))
      self._state = old_state.state
      self._havdalah = params[HAVDALAH_MINUTES]
      self._candle_light = params[CANDLE_LIGHT_MINUTES]
      self._shabbat_start = params[SHABBAT_START]
      self._shabbat_end = params[SHABBAT_END]
      self._last_update = params[LAST_UPDATE]
      self._title = params[TITLE]
      self._hebrew_title = params[HEBREW_TITLE]
      _LOGGER.info('New state: ' + str(self))
 
    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def device_state_attributes(self):
        return{
            SHABBAT_START: self._shabbat_start,
            SHABBAT_END: self._shabbat_end,
            HAVDALAH_MINUTES: self._havdalah,
            CANDLE_LIGHT_MINUTES: self._candle_light,
            LAST_UPDATE: self._last_update,
            TITLE: self._title,
            HEBREW_TITLE: self._hebrew_title,
        }
      
    @Throttle(SCAN_INTERVAL)
    def update(self):
        self._state = 'Working'
        self._shabbat_start = None
        self._shabbat_end = None
        self._title = None

        fetcher = shabbat.ShabbatTimesFetcher(
          self._latitude, self._longitude, self._timezone, self._havdalah, 
          self._candle_light)
        parser = shabbat.ShabbatTimesParser(fetcher)
        now = datetime.datetime.now() 
        current_interval = parser.update(now)
        if current_interval is None:
          _LOGGER.error('Could not parse Shabbat Times!')
          if parser.error:
            self._state = parser.error
          else:
            self._state = 'Error'
        else:
          # Valid interval.
          self._shabbat_start = current_interval.start_time
          self._shabbat_end = current_interval.end_time
          self._title = current_interval.title
          self._hebrew_title = current_interval.hebrew_title
          _LOGGER.info('Setting Shabbat times to ' + str(current_interval))
          self._state = 'Updated'
          self._last_update = now
