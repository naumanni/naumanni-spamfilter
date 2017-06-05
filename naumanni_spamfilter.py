# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import timedelta
from hashlib import sha256
import json
import logging
from urllib.parse import urlencode

from celery import current_app, group
from tornado import httpclient

from naumanni import celery
from naumanni.plugin import Plugin

logger = logging.getLogger(__name__)

SPAM_API_ENDPOINT = 'https://mstdn.onosendai.jp/ai/spam/'


def _content_to_hexdigest(plainContent):
    return sha256(plainContent.encode('utf8')).hexdigest()


def _make_redis_key(hash):
    return '{}:spam:{}'.format(__name__, hash)


class SpamFilterPlugin(Plugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def on_filter_statuses(self, objects, entities):
        redis = current_app.naumanni_app.redis

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
        job = test_spams.delay([statuses[0].plainContent for h, statuses in tests])
        result = job.get()
        if 'failed' in result:
            logger.error('spam api failed: %s', result['failed'])
        else:
            redis_updates = {}
            for idx, spam_result in enumerate(result):
                h, statuses = tests[idx]

                if 'failed' in spam_result:
                    logger.error('spam api failed : %s', spam_result['failed'])
                else:
                    if not statuses:
                        logger.warning('hash mismatch', statuses)
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


@celery.task
def test_spams(rawPlainContents):
    # remove returns
    plainContents = [txt.replace('\n', ' ') for txt in rawPlainContents]

    http_client = httpclient.HTTPClient()
    body = urlencode({'texts': '\n'.join(plainContents), 'spams': ''}, encoding='utf-8')
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
        response = response.body.decode('utf-8').strip().splitlines()
        logger.debug('response: %r', response)
        for idx, ln in enumerate(response):
            plainContent = plainContents[idx]
            rawPlainContent = rawPlainContents[idx]

            result = {
                'hash': _content_to_hexdigest(rawPlainContent),
                'test_text': plainContent,
            }
            try:
                bad_score, good_score = ln.split(',')
                bad_score = float(bad_score)
                good_score = float(good_score)
                is_spam = bad_score > good_score and bad_score >= 0.5
            except Exception as exc:
                result['failed'] = str(exc)
            else:
                logger.debug('test_spam %s -> %f %f %r', plainContent, bad_score, good_score, is_spam)
                result.update({
                    'bad_score': bad_score,
                    'good_score': good_score,
                    'is_spam': is_spam,
                })
            rv.append(result)
        return rv
    else:
        return {
            'failed': 'status code %s: %s'.format(response.code, response.reason)
        }
