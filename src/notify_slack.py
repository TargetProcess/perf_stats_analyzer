import sys
import argparse
import xml.etree.ElementTree as ET
from collections import namedtuple
import requests
import urlparse
import datetime

parser = argparse.ArgumentParser(description='Analyze perf tests results and notify Slack.')
parser.add_argument('-f', '--file', type=str, nargs='?', help='XML-file with test results', default='results.xml')
parser.add_argument('--slack-notification-url', type=str, required=True, help='Slack notification service url')
parser.add_argument('--slack-channel', type=str, required=True, help='Slack notification channel')
parser.add_argument('--build-url', type=str, required=True, help='Current job url')

TestStats = namedtuple("TestStats", ['tests', 'failures', 'errors', 'time'])


def get_failed_tests(xml_file):
    tree = ET.parse(xml_file)
    root = tree.getroot()

    return TestStats(**root.attrib)


def tests_failed(test_stats):
    return int(test_stats.tests) > 0 and int(test_stats.failures) + int(test_stats.errors) > 0


def notify_success(response):
    return 200 <= response.status_code < 300 and response.text.upper() == 'OK'


def notify_slack(slack_notification_url, slack_channel, build_url):
    def post_raw(url, data):
        return requests.post(url, json=data)

    build_output_url = urlparse.urljoin(build_url, 'console')
    message = "I found performance degradation at {date}. You can see more here: {build_output_url}" \
        .format(date=datetime.datetime.now().date(), build_output_url=build_output_url)

    response = post_raw(slack_notification_url, {
        "text": message,
        "username": "Targetprocess",
        "channel": slack_channel
    })

    if not notify_success(response):
        sys.exit("Performance degradation notification wasn't send. Technical info: {status_code} {reason}"
                 .format(status_code=response.status_code, reason=response.text))


# launcher

if __name__ == '__main__':
    args, extra = parser.parse_known_args()

    test_stats = get_failed_tests(args.file)

    if tests_failed(test_stats):
        notify_slack(args.slack_notification_url, args.slack_channel, args.build_url)
