# -*- coding: utf-8 -*-
from collections import defaultdict
from hashlib import sha256
import functools
import itertools
import json
import logging
from urllib.parse import urlencode

from tornado import httpclient, ioloop, web

from naumanni.mastodon_models import Account, Status
from naumanni.plugin import Plugin

logger = logging.getLogger(__name__)

SPAMFILTER = 'spamfilter'
SPAM_API_ENDPOINT = 'https://mstdn.onosendai.jp/ai/spam/'

SPAM_REPORT_REDIS_KEY = '{}:report'.format(__name__)


class SpamFilterPlugin(Plugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.report_task = None

    def on_after_initialize_webserver(self, webserver):
        """webserver初期化後によばれるので、必要なWorkerなどをセットアップする"""
        # このPluginのAPIを追加する
        webserver.application.add_plugin_handlers(SPAMFILTER, [
            ('/report', ReportSpamHandler, {'app_ref': self.app_ref}),
        ])

    def on_after_start_first_process(self):
        # 5分毎にレポートを送信する
        self.report_task = ioloop.PeriodicCallback(
            functools.partial(bulk_report_spams, self.app_ref),
            30000,
            # 5 * 60 * 1000,
        )
        self.report_task.start()

    def on_before_stop_server(self):
        if self.report_task:
            self.report_task.stop()

    async def on_filter_statuses(self, objects, entities):
        #
        texts = defaultdict(list)
        for status in objects.values():
            h = _content_to_hexdigest(status.plainContent)
            texts[h].append(status)

        if not texts:
            return objects

        # 1. RedisでOGPが保存済みかしらべてgetする
        keys = list(texts.keys())
        async with self.app.get_async_redis() as redis:
            cached = await redis.mget(*[_make_redis_key(h) for h in keys])
        for h, cached_spam_result in zip(keys, cached):
            if cached_spam_result:
                cached_spam_result = json.loads(cached_spam_result)
                statuses = texts.pop(h)
                for status in statuses:
                    status.add_extended_attributes('spamfilter', cached_spam_result)

        # 2. 全部celeryする
        test_contents = [{
            'uri': statuses[0].uri,
            'content': _strip_content(statuses[0].plainContent),
        } for h, statuses in texts.items()]
        # contentが空だと500エラー返してくるみたいなので省く
        test_contents = list(filter(lambda x: len(x['content']), test_contents))

        result = await test_spams(test_contents)

        if 'failed' in result:
            logger.error('spam api failed: %s', result['failed'])
            return objects
        else:
            redis_updates = {}
            for idx, spam_result in enumerate(result):
                for h, statuses in texts.items():
                    if statuses[0].uri == spam_result['uri']:
                        break
                else:
                    logger.warning('uri mismatch: %s %r', spam_result['uri'], spam_result)
                    continue
                if not statuses:
                    logger.warning('hash mismatch: %r', statuses)
                    continue

                for status in statuses:
                    status.add_extended_attributes('spamfilter', spam_result)

                redis_updates[_make_redis_key(h)] = json.dumps(spam_result)

        # 3. RedisにCacheを保存しておく
        if redis_updates:
            async with self.app.get_async_redis() as redis:
                pipe = redis.pipeline()
                pipe.mset(*itertools.chain.from_iterable(redis_updates.items()))
                for key in redis_updates.keys():
                    pipe.expire(key, 6.0 * 60 * 60)  # 6hours to expire
                await pipe.execute()

        return objects


class ReportSpamHandler(web.RequestHandler):
    def initialize(self, app_ref):
        self.app_ref = app_ref

    async def post(self):
        app = self.app_ref()
        if not app:
            # app is gone
            raise web.HTTPError(500)

        request_json = json.loads(self.request.body)
        status = Status(**request_json['status'])
        account = Account(**request_json['account'])

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
        async with app.get_async_redis() as redis:
            redis.sadd(SPAM_REPORT_REDIS_KEY, report)

        self.write({'result': 'ok'})
        await self.flush()


async def test_spams(statuses):
    data = json.dumps({'texts': statuses, 'spams': ''})
    body = urlencode({'json': data}, encoding='utf-8')

    try:
        response = await httpclient.AsyncHTTPClient().fetch(
            SPAM_API_ENDPOINT,
            method='POST',
            body=body
        )
    except httpclient.HTTPError as exc:
        response = exc.response
        logger.error(exc.response.body.decode('utf-8'))
        return {
            'failed': 'status code {}: {}'.format(response.code, response.reason),
            'request': body,
            'response': response.body.decode('utf-8'),
        }

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


async def bulk_report_spams(app_ref):
    app = app_ref()
    if not app:
        raise RuntimeError('app is gone')

    async with app.get_async_redis() as redis:
        pipe = redis.pipeline()
        pipe.smembers(SPAM_REPORT_REDIS_KEY)
        pipe.delete(SPAM_REPORT_REDIS_KEY)
        result = await pipe.execute()
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

    body = urlencode({'json': json.dumps(data)}, encoding='utf-8')
    logger.debug(body)
    try:
        await httpclient.AsyncHTTPClient().fetch(
            SPAM_API_ENDPOINT,
            method='POST',
            body=body,
            headers={
                'Content-Type': 'application/json; charset=utf-8'
            }
        )
    except httpclient.HTTPError as exc:
        logger.error(exc.response.body.decode('utf-8'))
        raise


def _content_to_hexdigest(plainContent):
    return sha256(plainContent.encode('utf8')).hexdigest()


def _make_redis_key(hash):
    return '{}:spam:{}'.format(__name__, hash)


def _strip_content(c):
    return c.replace('\n', ' ')
