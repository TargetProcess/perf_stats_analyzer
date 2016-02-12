import argparse
import xml.etree.ElementTree as ET
from collections import namedtuple
import requests
import json
import datetime

parser = argparse.ArgumentParser(description='Analyze perf tests results and notify TP.')
parser.add_argument('-f', '--file', type=str, nargs='?', help='XML-file with test results', default='results.xml')
parser.add_argument('--tp-url', type=str, nargs='?', help='TP url')
parser.add_argument('--tp-token', type=str, nargs='?', help='TP auth token')
parser.add_argument('--build-url', type=str, nargs='?', help='Current job url')

TestStats = namedtuple("TestStats", ['tests', 'failures', 'errors', 'time'])


def get_failed_tests(xml_file):
    tree = ET.parse(xml_file)
    root = tree.getroot()

    return TestStats(**root.attrib)


def tests_failed(test_stats):
    return test_stats.tests > 0 and test_stats.failures + test_stats.errors > 0


def notify_tp(url, token, build_url):
    with requests.Session() as session:
        def get_raw(collection, filter, include='[Id,Name]'):
            request_url = "{url}/api/v1/{collection}?token={token}&format=json&where={filter}&include={include})".format(
                url=url, token=token, collection=collection, filter=filter, include=include)

            print 'get_raw', request_url

            request = session.get(request_url)

            print 'get_raw', request.content

            return json.loads(request.content)["Items"]

        def post_raw(collection, data):
            request_url = "{url}/api/v1/{collection}?token={token}&format=json".format(url=url, token=token,
                                                                                       collection=collection)

            print 'post_raw', request_url

            request = session.post(request_url, data=json.dumps(data))

            print 'post_raw', request.content

            return json.loads(request.content)

        bug_name = 'Performance degradation. {date}'.format(date=datetime.datetime.now().date())
        description = '<!--markdown-->[Details]({build_url})'.format(build_url=build_url)

        existing_bugs = get_raw('Bugs', "(Name eq '{bug_name}')".format(bug_name=bug_name),
                                include='[Id,Name,EntityType[Id]]')

        if len(existing_bugs) == 0:
            project = get_raw('Projects', "(Name eq 'TP3')")[0]
            bug = post_raw('Bugs', {
                'name': bug_name,
                'description': description,
                'project': {
                    'id': project['Id']
                },
                'tags': 'maintenance'
            })
        else:
            existing_bug = existing_bugs[0]
            comment = post_raw('Comments', {
                'description': description,
                'general': {
                    'id': existing_bug['Id'],
                    'entityType': {
                        'id': existing_bug['EntityType']['Id']
                    }
                }
            })


# launcher

if __name__ == '__main__':
    args, extra = parser.parse_known_args()

    test_stats = get_failed_tests(args.file)

    if tests_failed(test_stats):
        notify_tp(args.tp_url, args.tp_token, args.build_url)
