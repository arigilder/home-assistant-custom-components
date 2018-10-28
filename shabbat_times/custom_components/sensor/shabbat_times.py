import asyncio
import datetime
import logging
import json
import requests
import voluptuous as vol
from collections import namedtuple
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_SCAN_INTERVAL, CONF_LONGITUDE, CONF_LATITUDE, CONF_NAME, CONF_TIME_ZONE
from homeassistant.util import Throttle
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.restore_state import async_get_last_state
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

SENSOR_ATTRIBUTES = [HAVDALAH_MINUTES, CANDLE_LIGHT_MINUTES,
  SHABBAT_START, SHABBAT_END, LAST_UPDATE]

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

# Really, this is Shabbat & Chag.
ShabbatInterval = namedtuple('ShabbatInterval', ['start_time', 'end_time'])

def setup_platform(hass, config, add_devices, discovery_info=None):
    havdalah = config.get(HAVDALAH_MINUTES)
    candle_light = config.get(CANDLE_LIGHT_MINUTES)
    name = config.get(CONF_NAME)
    latitude = config.get(CONF_LATITUDE, hass.config.latitude)
    longitude = config.get(CONF_LONGITUDE, hass.config.longitude)    
    timezone = config.get(CONF_TIME_ZONE, hass.config.time_zone)

    add_devices([ShabbatTimes(hass, latitude, longitude, timezone, name, havdalah, candle_light)])


class ShabbatTimes(Entity):

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


    @asyncio.coroutine
    def async_added_to_hass(self):
      """ Restore original state."""
      old_state = yield from async_get_last_state(self.hass, self.entity_id)
      _LOGGER.error(old_state)
      if (not old_state or 
          old_state.attributes[LAST_UPDATE] is None or 
          old_state.attributes[SHABBAT_START] is None or
          old_state.attributes[SHABBAT_END] is None):
        self.update()
        return
      _LOGGER.error(old_state.attributes[SHABBAT_END])
      if self.parse_time(old_state.attributes[SHABBAT_END], False) < datetime.datetime.now():
        _LOGGER.error("Current time is newer than shabbat end time. Updating.")
        self.update()
        return

      params = {key: old_state.attributes[key] for key in SENSOR_ATTRIBUTES
                if key in old_state.attributes}
      self._state = old_state.state
      self._havdalah = params[HAVDALAH_MINUTES]
      self._candle_light = params[CANDLE_LIGHT_MINUTES]
      self._shabbat_start = params[SHABBAT_START]
      self._shabbat_end = params[SHABBAT_END]
      self._last_update = params[LAST_UPDATE]
      _LOGGER.error(self)
 
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
        }
      
    def parse_time(self, timestr, includes_timezone=True):
      return datetime.datetime.strptime(
        timestr[0:-6] if includes_timezone else timestr, 
        '%Y-%m-%dT%H:%M:%S')

    def fetchTimes(self, year, month):
      """Fetches JSON for times for year/month.
      
      Returns:
        A list of ShabbatIntervals.
      """

      hebcal_url = ("http://www.hebcal.com/hebcal/?v=1&cfg=json&maj=off&"
                    "min=off&mod=off&nx=off&s=on&year=%d&month=%d&ss=off"
                    "&mf=off&c=on&geo=pos&latitude=%f&longitude=%f&"
                    "tzid=%s&m=%d&s=off&i=off&b=%d") % (
                    year, month, self._latitude, self._longitude, 
                    self._timezone, self._havdalah, self._candle_light)
      hebcal_response = requests.get(hebcal_url)
      hebcal_json_input = hebcal_response.text
      hebcal_decoded = json.loads(hebcal_json_input)
      
      intervals = []
      
      if 'error' in hebcal_decoded:
          self._state = hebcal_decoded['error']
          _LOGGER.error('Hebcal error: ' + hebcal_decoded['error'])
          return []

      cur_interval = []
      for item in hebcal_decoded['items']:
          if (item['category'] == 'candles'):
              ret_date = self.parse_time(item['date'])
              cur_interval.append(ret_date)
          elif (item['category'] == 'havdalah'):
              ret_date = self.parse_time(item['date'])
              if cur_interval:
                intervals.append(ShabbatInterval(cur_interval[0], ret_date))
                cur_interval = []
              else:
                # This is leftover from the previous month.
                intervals.append(ShabbatInterval(datetime.datetime.min, ret_date))

      if cur_interval:
          # Leftover half-open interval.
          intervals.append(ShabbatInterval(cur_interval[0], datetime.datetime.max))
      _LOGGER.debug("Shabbat intervals: " + str(intervals))
      return intervals

    def IsAdjacentHalfOpenInterval(self, half_open_interval, next_interval):
      return (half_open_interval.end_time == datetime.datetime.max and 
              next_interval.start_time != datetime.datetime.min and
              (next_interval.start_time - half_open_interval.start_time).days == 1)

    @Throttle(SCAN_INTERVAL)
    def update(self):
        _LOGGER.info("Updating Shabbat Times")
        self._state = 'Working'
        self._shabbat_start = None
        self._shabbat_end = None
        today = datetime.date.today()
        now = datetime.datetime.now() #+ datetime.timedelta(7)
        if (today.weekday() == 5):
            # Back up the Friday in case it's still currently Shabbat.
            friday = today + datetime.timedelta(-1)
        else:
            friday = today + datetime.timedelta((4-today.weekday()) % 7)

        saturday = friday + datetime.timedelta(+1)
        _LOGGER.debug('friday %d-%d', friday.year, friday.month)
        
        intervals = self.fetchTimes(friday.year, friday.month)
        if not intervals:
          self._state = 'Could not retrieve intervals.'
          _LOGGER.error(self._state)
          return
          
        # If it's Motzei Shabbat, and there are no Shabbatot left in the month, 
        # we need to advance the month and try again.
        # This only happens on Motzei Shabbat because of the line above where we
        # back up to the preceding Friday.
        if intervals[-1].end_time < now:
          _LOGGER.debug('Last monthly Motzei Shabbat; advancing times')
          friday = friday + datetime.timedelta(+7)
          saturday = friday + datetime.timedelta(+1)
          _LOGGER.debug(friday)
          intervals = self.fetchTimes(friday.year, friday.month)
          if not intervals:
            _LOGGER.error('Could not retrieve next intervals!')
            return         

        # TODO: Need to add case for if it's currently Shabbat and the 1st of month (prev_intervals) -- Aug/Sep/Oct 2018 good test case
        # If the last interval is an open interval (i.e. last day of month is a Friday)...
        if intervals[-1].end_time == datetime.datetime.max:
          # ...fetch the next month to complete the interval
          next_year = friday.year + (1 if friday.month == 12 else 0)
          # Mod 13 to allow month 12 to appear. Good test case: Nov./Dec. 2018
          next_month = ((friday.month + 1) % 13)
          next_intervals = self.fetchTimes(next_year, next_month)
          _LOGGER.debug(next_intervals)
          if not next_intervals:
            _LOGGER.error('Could not retrieve next intervals!')
            return
          # If the start of the next month is a half-open interval, OR it appears to be a complete interval, though
          # with a start_time adjacent to the current month's half-open start time 
          # (e.g. Sep 30 Erev YT Day 1, Oct 1 night starts YT Day 2, end Oct 2)
          # then it is considered to be a valid completion.
          if next_intervals[0].start_time != datetime.datetime.min and not self.IsAdjacentHalfOpenInterval(intervals[-1], next_intervals[0]):
            _LOGGER.error("Current month ends with open interval; next month did not begin with open interval!")
            self._state = 'INTERVAL_ERROR'
            return
          intervals[-1] = ShabbatInterval(intervals[-1].start_time, next_intervals[0].end_time)
          
        if intervals[0].start_time == datetime.datetime.min:
          year = friday.year
          month = friday.month
          if friday.month == 0:
            month = 12
            year -= 1
          else:
            month -= 1
          prev_intervals = self.fetchTimes(year, month)
          #_LOGGER.debug(prev_intervals)
          if not prev_intervals:
            _LOGGER.error('Could not retrieve previous intervals!')
            return
          if prev_intervals[-1].end_time != datetime.datetime.max:
            _LOGGER.error("Current month starts with open interval; previous month did not end with open interval!")
            self._state = 'INTERVAL_ERROR'
            return
          intervals[0] = ShabbatInterval(prev_intervals[-1].start_time, intervals[0].end_time)
          
        
        # Sort intervals by start time.
        intervals.sort(key=lambda x: x.start_time)

        # Find first interval after "now".
        for interval in intervals:
          # Skip intervals in the past.
          if interval.end_time < now:
            continue
          # If interval start is greater than today, OR interval start is <= today
          # but end time is > today (i.e. it is currently shabbat), pick that
          # interval.
          if interval.start_time > now or (interval.start_time <= now and interval.end_time > now):
            self._shabbat_start = interval.start_time
            self._shabbat_end = interval.end_time
            _LOGGER.info('Setting Shabbat times to ' + str(interval))
            break

        self._state = 'Updated'
        self._last_update = now

