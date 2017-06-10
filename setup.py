from setuptools import setup

setup(
    name='naumanni-spamfilter',
    version='0.1',
    author='Shin Adachi',
    author_email='shn@glucose.jp',
    license='AGPL',
    py_modules=['naumanni_spamfilter'],
    entry_points={
        'naumanni.plugins': [
            'spamfilter = naumanni_spamfilter:SpamFilterPlugin',
        ]
    }
)
