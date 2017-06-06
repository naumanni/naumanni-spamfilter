# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import timedelta
from hashlib import sha256
import json
import logging
from urllib.parse import urlencode

from celery import current_app as current_celeryapp, group
from flask import Blueprint, request, current_app as current_flaskapp
from tornado import httpclient

from naumanni import celery
from naumanni.mastodon_models import Account, Status
from naumanni.plugin import Plugin
from naumanni.web.utils import api_jsonify

logger = logging.getLogger(__name__)

SPAMFILTER = 'spamfilter'
SPAM_API_ENDPOINT = 'https://mstdn.onosendai.jp/ai/spam/'
blueprint = Blueprint(SPAMFILTER, __name__)

SPAM_REPORT_REDIS_KEY = '{}:report'.format(__name__)


class SpamFilterPlugin(Plugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def on_after_initialize_webserver(self, webserver):
        """webserver初期化後によばれるので、このPluginのAPIを追加する"""
        webserver.flask_app.register_plugin_blueprint(SPAMFILTER, blueprint)

    def on_after_configure_celery(self, celeryapp):
        """Celery初期化後によばれるので、Periodic Taskを追加する"""
        # 5分毎にレポートを送信する
        celeryapp.add_periodic_task(
            5 * 60.0,
            bulk_report_spams.s(),
        )
        bulk_report_spams.delay()

    def on_filter_statuses(self, objects, entities):
        redis = current_celeryapp.naumanni.redis

        #
        texts = defaultdict(list)
        for status in objects.values():
            h = _content_to_hexdigest(status.plainContent)
            texts[h].append(status)

        if not texts:
            return objects

        # 1. RedisでOGPが保存済みかしらべてgetする
        keys = list(texts.keys())
        cached = redis.mget([_make_redis_key(h) for h in keys])
        for h, cached_spam_result in zip(keys, cached):
            if cached_spam_result and cached_spam_result != b'a':
                cached_spam_result = json.loads(cached_spam_result)
                statuses = texts.pop(h)
                for status in statuses:
                    status.add_extended_attributes('spamfilter', cached_spam_result)

        # 2. 全部celeryする
        tests = list(texts.items())
        job = test_spams.delay([{
            'uri': statuses[0].uri,
            'content': _strip_content(statuses[0].plainContent),
        } for h, statuses in tests])
        result = job.get()
        if 'failed' in result:
            logger.error('spam api failed: %s', result['failed'])
        else:
            redis_updates = {}
            for idx, spam_result in enumerate(result):
                h, statuses = tests[idx]

                if not statuses:
                    logger.warning('hash mismatch: %r', statuses)
                elif statuses[0].uri != spam_result['uri']:
                    logger.warning('uri mismatch: %r', statuses)
                    continue
                for status in statuses:
                    status.add_extended_attributes('spamfilter', spam_result)

                redis_updates[_make_redis_key(h)] = json.dumps(spam_result)

        # 3. RedisにCacheを保存しておく
        if redis_updates:
            expires = timedelta(hours=6)
            with redis.pipeline() as pipe:
                pipe.mset(redis_updates)
                for key in redis_updates.keys():
                    pipe.expire(key, expires)
                pipe.execute()

        return objects


@blueprint.route('/report', methods=['POST'])
def report_spam():
    status = Status(**request.json['status'])
    account = Account(**request.json['account'])

    report = json.dumps({
        'account': {
            'acct': account.acct,
        },
        'content': status.content,
        'uri': status.uri,
        'spoiler_text': status.spoiler_text,

        '_plain_content': _strip_content(status.content),
        '_reporter': 'shn@oppai.tokyo',
    })

    # push
    redis = current_flaskapp.naumanni.redis
    redis.sadd(SPAM_REPORT_REDIS_KEY, report)

    return api_jsonify({'result': 'ok'})


@celery.task
def test_spams(statuses):
    http_client = httpclient.HTTPClient()
    data = json.dumps({'texts': statuses, 'spams': ''})
    body = urlencode({'json': data}, encoding='utf-8')

    try:
        response = http_client.fetch(
            SPAM_API_ENDPOINT,
            method='POST',
            body=body
        )
    except httpclient.HTTPError as exc:
        print(exc)
        print(exc.response.body.decode('utf-8'))
        logger.error(exc.response.body.decode('utf-8'))
        raise

    if response.code == 200:
        rv = []
        response = json.loads(response.body.decode('utf-8'))
        logger.debug('response: %r', response)
        for idx, score in enumerate(response):
            bad_score, good_score = score['bad'], score['good']
            is_spam = bad_score > good_score and bad_score >= 0.5

            rv.append({
                'uri': score['uri'],
                'bad_score': bad_score,
                'good_score': good_score,
                'is_spam': is_spam,
            })
        return rv
    else:
        return {
            'failed': 'status code %s: %s'.format(response.code, response.reason)
        }


@celery.task(ignore_result=True)
def bulk_report_spams():
    redis = current_celeryapp.naumanni.redis
    with redis.pipeline() as pipe:
        pipe.smembers(SPAM_REPORT_REDIS_KEY)
        pipe.delete(SPAM_REPORT_REDIS_KEY)
        result = pipe.execute()
        reports = result[0]

    if not reports:
        logger.info('no report spams')
        return

    # api側の仕様で謎なことになっている
    # manually make json
    data = {
        'spams': json.loads(b'[' + b',\n'.join(reports) + b']'),
        'texts': ''
    }

    http_client = httpclient.HTTPClient()
    body = urlencode({'json': json.dumps(data)}, encoding='utf-8')
    logger.debug(body)
    try:
        http_client.fetch(
            SPAM_API_ENDPOINT,
            method='POST',
            body=body,
            headers={
                'Content-Type': 'application/json; charset=utf-8'
            }
        )
    except httpclient.HTTPError as exc:
        print(exc)
        print(exc.response.body.decode('utf-8'))
        logger.error(exc.response.body.decode('utf-8'))
        raise


def _content_to_hexdigest(plainContent):
    return sha256(plainContent.encode('utf8')).hexdigest()


def _make_redis_key(hash):
    return '{}:spam:{}'.format(__name__, hash)


def _strip_content(c):
    return c.replace('\n', ' ')
