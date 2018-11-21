import datetime
import json
import logging
import shabbat_times_util

def load_json(f):
  with open(f, 'r') as json_file:
    contents = json_file.read()
    return json.loads(contents)
  return None

class FakeFetcher(shabbat_times_util.ShabbatTimesFetcher):
  def __init__(self):
    self._cache = {
      (2018, 8): load_json('tests/august_2018.json'),
      (2018, 9): load_json('tests/september_2018.json'),
      (2018, 10): load_json('tests/october_2018.json'),
      (2018, 11): load_json('tests/november_2018.json'),
      (2018, 12): load_json('tests/december_2018.json'),
      (2019, 1): load_json('tests/january_2019.json'),
      (2018, 0): load_json('tests/all_2018.json'),
    }
 
  def _fetchHebcalResponse(self, year, month):
    if (year, month) in self._cache:
      return self._cache[(year, month)]
    return None

def assignInterval(d, intervals):
  for interval in intervals:
    # Skip intervals in the past.
    if interval.end_time < d:
      continue
    if interval.start_time > d or (interval.start_time <= d and interval.end_time > d):
      return interval
  raise
    
def main():
#  logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s.py:%(lineno)s - %(levelname)s - %(message)s')
  fetcher = FakeFetcher()
  all_intervals = fetcher.fetchTimes(2018, 0)
  parser = shabbat_times_util.ShabbatTimesParser(fetcher)
  
  d = datetime.datetime(2018, 8, 1, 22, 0)
  end = datetime.datetime(2019, 1, 1)
  # d = datetime.datetime(2018, 8, 24)
  # end = datetime.datetime(2018, 9, 2)
  golden_intervals = {}
  while d < end:
    golden_interval = assignInterval(d, all_intervals)
    #print(golden_interval)
    parsed_interval = parser.update(d)
    print(d, parsed_interval, golden_interval, parser.error)
    
    if parsed_interval is None:
      break
    if parsed_interval != golden_interval:
      print('Mismatch! Expected %s, got %s' % (str(golden_interval), str(parsed_interval)))
      break
    #print(d, interval)
    d = d + datetime.timedelta(1)
    #d = d + datetime.timedelta(hours=1, minutes=1)
  return

if __name__ == '__main__':
  main()
