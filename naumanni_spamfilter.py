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
        job = group(
            test_spam.s(statuses[0].plainContent) for statuses in texts.values()
        )
        redis_updates = {}
        for spam_result in job().get():
            statuses = texts.get(spam_result['hash'], [])
            if not statuses:
                logger.warning('hash mismatch', statuses)
            for status in statuses:
                status.add_extended_attributes('spamfilter', spam_result)

            redis_updates[_make_redis_key(spam_result['hash'])] = json.dumps(spam_result)

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
def test_spam(rawPlainContent):
    # remove returns
    plainContent = rawPlainContent.replace('\n', ' ')

    http_client = httpclient.HTTPClient()
    body = urlencode({'texts': plainContent}, encoding='utf-8')
    response = http_client.fetch(
        SPAM_API_ENDPOINT,
        method='POST',
        body=body
    )

    rv = {
        'hash': _content_to_hexdigest(rawPlainContent),
        'test_text': plainContent,
    }

    if response.code == 200:
        try:
            spam, not_spam = response.body.decode('utf-8').strip().split(',')
            spam = float(spam)
            not_spam = float(not_spam)
            is_spam = spam > not_spam and spam >= 0.5
        except Exception as exc:
            rv['failed'] = str(exc)
        else:
            logger.debug('test_spam %s -> %f %f %r', plainContent, spam, not_spam, is_spam)
            rv.update({
                'spam_score': spam,
                'not_spam_score': not_spam,
                'is_spam': is_spam,
            })
    else:
        rv['failed'] = 'status code %s: %s'.format(response.code, response.reason)

    return rv
