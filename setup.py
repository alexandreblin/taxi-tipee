#!/usr/bin/env python
from setuptools import find_packages, setup
from taxi_tipee import __version__

install_requires = [
    'taxi>=6.0',
    'requests>=2.3.0',
]

setup(
    name='taxi_tipee',
    version=__version__,
    packages=find_packages(),
    description='Tipee backend for Taxi',
    author='Alexandre Blin',
    author_email='alexandre@blin.fr',
    url='https://github.com/alexandreblin/taxi-tipee',
    install_requires=install_requires,
    license='wtfpl',
    python_requires=">=3.6",
    entry_points={
        'taxi.backends': 'tipee = taxi_tipee.backend:TipeeBackend'
    },
    classifiers=[
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
    ]
)
