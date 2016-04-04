import argparse
import os
import re
import unittest
import xml.etree.ElementTree as ET
from collections import namedtuple
from itertools import groupby, takewhile

import numpy as np
import xmlrunner
from elasticsearch import Elasticsearch

parser = argparse.ArgumentParser(description='Analyze perf tests data within the time period.')
parser.add_argument('-u', '--url', type=str, nargs='?', help='ElasticSearch url', default='http://192.168.2.95:9200')
parser.add_argument('-w', '--window', type=int, nargs='?', help='Moving average window', default=10)
parser.add_argument('-d', '--days', type=int, nargs='?', help='Number of days to analyze', default=20)
parser.add_argument('-mf', '--merge_file', help='merge all test results xml into one file')

directory = '.results'

# data structures

StatRecord = namedtuple('StatRecord', [
    'branch',
    'name',
    'timestamp',
    'value'
])

MovingAverageRecord = namedtuple('TrendRecord', [
    'branch',
    'name',
    'value'
])

# place excluded metrics here
# metric can be temporarily excluded if it's very unstable and requires further investigation
exclude_metric = [
    lambda m: m.name in ['tc by us list - treeView # basic_load_cat'],
    lambda m: m.name.startswith('notifications')
]


def filter_excluded(metrics):
    return filter(lambda metric: all(map(lambda exclude: not exclude(metric), exclude_metric)), metrics)


# data processing

def get_stats_data(url, days):
    search_results = Elasticsearch([url]).search(
        size=50000,
        index='performance_tests_run_reports',
        body={
            'query': {
                'filtered': {
                    'query': {
                        'match': {
                            'metric_type': 'http_metric'
                        }
                    }
                }
            },
            'filter': {
                'range': {
                    'datetime': {
                        'gte': 'now-{days}d/d'.format(days=days)
                    }
                }
            }
        })['hits']['hits']

    def get_branch(record):
        return record['branch'] if record['branch'] != record['build'] else re.sub('_perf\d+', '', record['branch'])

    def get_name(record):
        return record['name_with_test'] if record['metric_type'] == 'http_metric' else record['name']

    return sorted(map(lambda r: StatRecord(branch=get_branch(r['_source']),
                                           name=get_name(r['_source']),
                                           timestamp=r['_source']['datetime'],
                                           value=r['_source']['median']),
                      search_results), key=lambda r: r.timestamp)


def get_moving_averages(stats_data, window):
    for branch, branch_records in groupby(sorted(stats_data, key=lambda r: r.branch), lambda r: r.branch):
        for key, test_records in groupby(sorted(branch_records, key=lambda r: r.name), lambda r: r.name):
            values = map(lambda r: r.value, test_records)

            if len(values) < window * 2:
                continue

            moving_average = holt_winters_second_order_ewma(np.array(values), span=window, beta=0.3)

            yield MovingAverageRecord(branch=branch, name=key, value=moving_average)


# unit tests

def generate_test_classes(moving_averages, window):
    def get_class(branch, moving_averages):
        class TestSequenceMeta(type):
            def __new__(mcs, name, bases, dict):
                def gen_test_instant_raising_trend(moving_average):
                    def test(self):
                        trend_percent = trend(moving_average.value) * 100
                        instant_threshold = 3

                        self.assertLessEqual(trend_percent, instant_threshold,
                                             'Instant performance degradation for "{test_name}" is {percent:3.2f}%'.format(
                                                 test_name=moving_average.name, percent=trend_percent))

                    return test

                def gen_test_long_raising_trend(moving_average):
                    def test(self):
                        deltas = zip(moving_average.value, moving_average.value[1:])
                        raising_trend = list(reversed(list(takewhile(lambda (prv, nxt): nxt > prv, reversed(deltas)))))
                        if len(raising_trend) > 0:
                            long_threshold = 15
                            long_trend_percent = trend([min(moving_average.value[-window:]), raising_trend[-1][1]]) * 100

                            self.assertLessEqual(long_trend_percent, long_threshold,
                                                 'Long time performance degradation for "{test_name}" is {percent:3.2f}%'.format(
                                                     test_name=moving_average.name, percent=long_trend_percent))

                    return test

                for moving_average in moving_averages:
                    property_name_instant = 'test_instant_' + moving_average.name.replace('.', '_')
                    dict[property_name_instant] = gen_test_instant_raising_trend(moving_average)
                    property_name_long = 'test_long_' + moving_average.name.replace('.', '_')
                    dict[property_name_long] = gen_test_long_raising_trend(moving_average)

                return type.__new__(mcs, 'Test_' + str(branch), bases, dict)

        class TestSequence(unittest.TestCase):
            __metaclass__ = TestSequenceMeta

        return TestSequence

    for branch, branch_moving_averages in groupby(moving_averages, key=lambda t: t.branch):
        yield get_class(branch, branch_moving_averages)


def run_tests(classes, merge_file):
    loader = unittest.TestLoader()
    for Klass in classes:
        test_suite = loader.loadTestsFromTestCase(Klass)
        xmlrunner.XMLTestRunner(output=directory).run(test_suite)

    if merge_file:
        merge_test_results(merge_file)


def merge_test_results(output_file):
    failures = 0
    tests = 0
    errors = 0
    time = 0.0
    cases = []
    for file_name in os.listdir(directory):
        tree = ET.parse(os.path.abspath(directory + '/' + file_name))
        test_suite = tree.getroot()
        failures += int(test_suite.attrib['failures'])
        tests += int(test_suite.attrib['tests'])
        errors += int(test_suite.attrib['errors'])
        time += float(test_suite.attrib['time'])
        cases.append(test_suite.getchildren())

    new_root = ET.Element('testsuite')
    new_root.attrib['failures'] = '%s' % failures
    new_root.attrib['tests'] = '%s' % tests
    new_root.attrib['errors'] = '%s' % errors
    new_root.attrib['time'] = '%s' % time
    for case in cases:
        new_root.extend(case)
    new_tree = ET.ElementTree(new_root)
    if os.path.isfile(output_file):
        os.remove(output_file)
    new_tree.write(output_file)


# stats calculations

def holt_winters_second_order_ewma(x, span, beta):
    N = x.size
    alpha = 2.0 / (1 + span)
    s = np.zeros((N,))
    b = np.zeros((N,))
    s[0] = x[0]
    for i in range(1, N):
        s[i] = alpha * x[i] + (1 - alpha) * (s[i - 1] + b[i - 1])
        b[i] = beta * (s[i] - s[i - 1]) + (1 - beta) * b[i - 1]
    return s


def trend(points):
    last_points = points[-2:]
    [y1, y2] = last_points
    delta = y2 - y1
    if y1 != 0:
        return delta / y1

    return 0


# launcher

if __name__ == '__main__':
    args, extra = parser.parse_known_args()

    raw_stats = get_stats_data(args.url, args.days)
    actual_stats = filter_excluded(raw_stats)
    moving_averages = list(get_moving_averages(actual_stats, args.window))

    classes = generate_test_classes(moving_averages, args.window)

    run_tests(classes, args.merge_file)
