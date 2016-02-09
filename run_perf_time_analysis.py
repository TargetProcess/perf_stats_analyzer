import argparse
import unittest
from collections import namedtuple
from itertools import groupby
import xml.etree.ElementTree as ET

import numpy as np

import os
import re
import xmlrunner
from elasticsearch import Elasticsearch

parser = argparse.ArgumentParser(description='Analyze perf tests data within the time period.')
parser.add_argument('-u', '--url', type=str, nargs='?', help='ElasticSearch url', default='http://192.168.2.95:9200')
parser.add_argument('-w', '--window', type=int, nargs='?', help='Moving average window', default=10)
parser.add_argument('-d', '--days', type=int, nargs='?', help='Number of days to analyze', default=20)
parser.add_argument('-t', '--threshold', type=int, nargs='?', help='Threshold, %', default=2)
parser.add_argument('-mf', '--merge_file', help='merge all test results xml into one file')

directory = '.results'

# data structures

StatRecord = namedtuple('StatRecord', [
    'branch',
    'name',
    'timestamp',
    'value'
])

TrendRecord = namedtuple('TrendRecord', [
    'branch',
    'name',
    'value'
])


# data processing

def get_stats_data(url, days):
    search_results = Elasticsearch([url]).search(
        size=50000,
        index='performance_tests_run_reports',
        body={
            'query': {
                'filtered': {
                    'query': {
                        'match_all': {}
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

    return map(lambda r: StatRecord(branch=get_branch(r['_source']),
                                    name=get_name(r['_source']),
                                    timestamp=r['_source']['timestamp'],
                                    value=r['_source']['median']),
               search_results)


def get_trends(stats_data, window):
    for branch, branch_records in groupby(sorted(stats_data, key=lambda r: r.branch), lambda r: r.branch):
        for key, test_records in groupby(sorted(branch_records, key=lambda r: r.name), lambda r: r.name):
            values = map(lambda r: r.value, sorted(test_records, key=lambda r: r.timestamp))

            if len(values) < window * 2:
                continue

            moving_average = exponential_moving_average(values[-window * 2:], window)

            yield TrendRecord(branch=branch, name=key, value=trend(moving_average))


# unit tests

def generate_test_class(trends, threshold):
    class TestSequenceMeta(type):
        def __new__(mcs, name, bases, dict):
            def gen_test(trend):
                def test(self):
                    beautiful_value = trend.value * 100
                    self.assertLessEqual(beautiful_value, threshold,
                                         'Performance degradation for "{test_name}" is {percent:3.2f}%'.format(
                                             test_name=trend.name, percent=beautiful_value))

                return test

            for trend in trends:
                name = 'test_perf_on_{branch}_{test_name}'.format(branch=trend.branch, test_name=trend.name)
                dict[name] = gen_test(trend)
            return type.__new__(mcs, name, bases, dict)

    class TestSequence(unittest.TestCase):
        __metaclass__ = TestSequenceMeta

    return TestSequence


def run_tests(Klass, merge_file):
    loader = unittest.TestLoader()
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

def simple_moving_average(values, window):
    weights = np.repeat(1.0, window) / window

    return np.convolve(values, weights, 'valid')


def exponential_moving_average(values, window):
    weights = np.ma.exp(np.linspace(-.5, 0, window))
    weights /= weights.sum()

    return np.convolve(values, weights)[window - 1: len(values)]


def trend(points):
    last_points = points[-2:]
    [y1, y2] = last_points
    delta = y2 - y1
    avg = np.average(last_points)
    if avg == 0:
        return 0

    return delta / avg


# launcher

if __name__ == '__main__':
    args, extra = parser.parse_known_args()

    raw_stats = get_stats_data(args.url, args.days)
    trends = get_trends(raw_stats, args.window)

    Klass = generate_test_class(trends, args.threshold)

    run_tests(Klass, args.merge_file)
