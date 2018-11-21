import datetime
import logging
import json
import requests
from collections import namedtuple

_LOGGER = logging.getLogger(__name__)

# Really, this is Shabbat & Chag.
ShabbatInterval = namedtuple('ShabbatInterval', ['start_time', 'end_time', 'title', 'hebrew_title'])

def parse_time(timestr, includes_timezone=True):
  return datetime.datetime.strptime(
    timestr[0:-6] if includes_timezone else timestr, 
    '%Y-%m-%dT%H:%M:%S')

class ShabbatTimesFetcher:
    def __init__(self, latitude, longitude, timezone, havdalah, candle_light):
        self._latitude = latitude
        self._longitude = longitude
        self._timezone = timezone
        self._havdalah = havdalah
        self._candle_light = candle_light
        self.error = None
        
    def _fetchHebcalResponse(self, year, month):
      hebcal_url = ("http://www.hebcal.com/hebcal/?v=1&cfg=json&maj=off&"
                    "min=off&mod=off&nx=off&s=on&year=%d&month=%d&ss=off"
                    "&mf=off&c=on&geo=pos&latitude=%f&longitude=%f&"
                    "tzid=%s&m=%d&s=off&i=off&b=%d") % (
                    year, month, self._latitude, self._longitude, 
                    self._timezone, self._havdalah, self._candle_light)
      _LOGGER.debug(hebcal_url)
      hebcal_response = requests.get(hebcal_url)
      hebcal_json_input = hebcal_response.text
      return json.loads(hebcal_json_input)
      
    def fetchTimes(self, year, month):
      """Fetches JSON for times for year/month.
      
      Returns:
        A list of ShabbatIntervals.
      """
      self.error = None
      hebcal_decoded = self._fetchHebcalResponse(year, month)
      intervals = []
      
      if 'error' in hebcal_decoded:
          self.error = hebcal_decoded['error']
          _LOGGER.error('Hebcal error: ' + hebcal_decoded['error'])
          return []
          
      def IsMajorHoliday(item):
        return (item['category'] == 'holiday' and 
                (item.get('subcat', '') == 'major' or 
                 item.get('yomtov', False) == True))

      cur_interval = []
      cur_title = ''
      cur_hebrew_title = ''
      half_open_start = False
      for item in hebcal_decoded['items']:
          if (item['category'] == 'candles'):
              ret_date = parse_time(item['date'])
              cur_interval.append(ret_date)
          elif (cur_title == '' and 
                (cur_interval or 'yomtov' in item or item['category'] == 'parashat') and 
                (IsMajorHoliday(item) or item['category'] == 'parashat')):
            # Conditions for setting title:
            # 1) Title has not yet been set (take the first of a multi-day yomtov)
            # 2a) There is a candlelighting interval in progress, OR
            # 2b) There is NO interval in progress, but the month starts with a
            #     parasha (i.e. Shabbat is the 1st of the month) or a Yom Tov.
            # 3) The title element is itself a major holiday or parasha (so exclude
            #    all minor holidays and CH"M but not CH"M Shabbat).
            cur_title = item['title']
            cur_hebrew_title = item['hebrew']
            if not cur_interval:
              # We might have advance knowledge that the first of the month should
              # be a half-open start. This accounts for the case e.g. Sep 30 Erev YT 
              # Day 1, Oct 1 night starts YT Day 2, end Oct 2).
              # If we don't set this, on Oct 1 midnight and on, the interval's start 
              # might be parsed as candlelighting on Oct 1 night.
              # By forcing this here, we later set the start interval to be half-open.
              half_open_start = True
          elif (item['category'] == 'havdalah'):
              ret_date = parse_time(item['date'])
              if cur_interval:
                if half_open_start:
                  intervals.append(ShabbatInterval(datetime.datetime.min, ret_date, cur_title, cur_hebrew_title))
                else: 
                  intervals.append(ShabbatInterval(cur_interval[0], ret_date, cur_title, cur_hebrew_title))
                cur_interval = []
                cur_title = ''
                cur_hebrew_title = ''
                half_open_start = False
              else:
                # This is leftover from the previous month.
                intervals.append(ShabbatInterval(datetime.datetime.min, ret_date, cur_title, cur_hebrew_title))
                cur_title = ''
                cur_hebrew_title = ''
                half_open_start = False

      if cur_interval:
          # Leftover half-open interval.
          intervals.append(ShabbatInterval(cur_interval[0], datetime.datetime.max, cur_title, cur_hebrew_title))
      _LOGGER.debug("Shabbat intervals: " + str(intervals))
      return intervals

      

def IsAdjacentHalfOpenInterval(half_open_interval, next_interval):
  return (half_open_interval.end_time == datetime.datetime.max and 
          next_interval.start_time != datetime.datetime.min and
          (next_interval.start_time - half_open_interval.start_time).days == 1)

class ShabbatTimesParser:
    def __init__(self, fetcher):
      self._fetcher = fetcher
      self.error = None

    def update(self, now):
        _LOGGER.info("Updating Shabbat Times (now=" + str(now) + ")")
        self.error = None
        assert now
        today = datetime.datetime(now.year, now.month, now.day)
        if (today.weekday() == 5):
            # Back up the Friday in case it's still currently Shabbat.
            friday = today + datetime.timedelta(-1)
        else:
            friday = today + datetime.timedelta((4-today.weekday()) % 7)

        saturday = friday + datetime.timedelta(+1)
        _LOGGER.debug('friday %d-%d', friday.year, friday.month)
        
        intervals = self._fetcher.fetchTimes(friday.year, friday.month)
        if not intervals:
          self.error = 'Could not retrieve intervals.'
          _LOGGER.error(self.error)
          return None
          
        # If it's Motzei Shabbat, and there are no Shabbatot left in the month, 
        # we need to advance the month and try again.
        # This only happens on Motzei Shabbat because of the line above where we
        # back up to the preceding Friday.
        if intervals[-1].end_time < now:
          _LOGGER.debug('Last monthly Motzei Shabbat; advancing times')
          friday = friday + datetime.timedelta(+7)
          saturday = friday + datetime.timedelta(+1)
          _LOGGER.debug(friday)
          intervals = self._fetcher.fetchTimes(friday.year, friday.month)
          if not intervals:
            _LOGGER.error('Could not retrieve next intervals!')
            return None  

        # TODO: Need to add case for if it's currently Shabbat and the 1st of month (prev_intervals) -- Aug/Sep/Oct 2018 good test case
        # If the last interval is an open interval (i.e. last day of month is a Friday)...
        if intervals[-1].end_time == datetime.datetime.max:
          # ...fetch the next month to complete the interval
          next_year = friday.year + (1 if friday.month == 12 else 0)
          # Mod 13 to allow month 12 to appear. Good test case: Nov./Dec. 2018
          next_month = ((friday.month + 1) % 13)
          _LOGGER.debug('Current month ends with open interval; retrieving next month (%04d-%02d)' % (next_year, next_month))
          next_intervals = self._fetcher.fetchTimes(next_year, next_month)
          if not next_intervals:
            _LOGGER.error('Could not retrieve next intervals!')
            return None
          # If the start of the next month is a half-open interval, OR it appears
          # to be a complete interval, though with a start_time adjacent to the 
          # current month's half-open start time (e.g. Sep 30 Erev YT Day 1, 
          # Oct 1 night starts YT Day 2, end Oct 2) then it is considered to be 
          # a valid completion.
          if (next_intervals[0].start_time != datetime.datetime.min and 
              not IsAdjacentHalfOpenInterval(intervals[-1], next_intervals[0])):
            _LOGGER.error("Current month ends with open interval; next month did not begin with open interval!")
            self.error = 'INTERVAL_ERROR'
            return None
          intervals[-1] = ShabbatInterval(intervals[-1].start_time, 
                                          next_intervals[0].end_time, 
                                          intervals[-1].title or next_intervals[0].title,
                                          intervals[-1].hebrew_title or next_intervals[0].hebrew_title)
          # Tack on the remaining intervals after stitching together the open
          # intervals. This handles the case of Motzei Shabbat AFTER the 
          # stitched interval, when Shabbat ends on the 1st of the month 
          # (e.g. 8/31->9/1@8pm; update for shabbat times at 10pm)
          intervals.extend(next_intervals[1:])
          
        if intervals[0].start_time == datetime.datetime.min:
          year = friday.year
          month = friday.month
          if friday.month == 0:
            month = 12
            year -= 1
          else:
            month -= 1
          _LOGGER.debug('Current month starts with open interval; fetching previous month')
          prev_intervals = self._fetcher.fetchTimes(year, month)
          #_LOGGER.debug(prev_intervals)
          if not prev_intervals:
            _LOGGER.error('Could not retrieve previous intervals!')
            return None
          if prev_intervals[-1].end_time != datetime.datetime.max:
            _LOGGER.error("Current month starts with open interval; previous month did not end with open interval!")
            self.error = 'INTERVAL_ERROR'
            return None
          intervals[0] = ShabbatInterval(prev_intervals[-1].start_time, 
                                         intervals[0].end_time, 
                                         prev_intervals[-1].title or intervals[0].title,
                                         prev_intervals[-1].hebrew_title or intervals[0].hebrew_title)          
        
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
            _LOGGER.info('Setting Shabbat times to ' + str(interval))
            return interval
        self.error = 'Unknown Error'
        return None
