# -*- coding: utf-8 -*-

name = 'deadline_submission_api'

version = '2.0.0'

description = \
    """
    Object-oriented submission API of Deadline.
    """

authors = ['Hao Long']

requires = [
    'addict-2.4.0',
    'deadline_api-10',
    'farm_environment-2',
    'python-2.7..4',
    'hal_config-2',
    'hal_paths-2'
]

def commands():
    """Set up package."""
    env.PYTHONPATH.prepend("{this.root}/site-packages")  # noqa: F821

uuid = '61b2a11a-2fba-4cc7-b3b5-94cd82cab9c2'

timestamp = 1614787796

tests = \
    {'python-2.7': {'command': 'pytest {root}/site-packages/deadline_submission_api --verbosity=2',
                    'requires': ['pytest-4.6',
                                 'pytest_mock-1.10',
                                 'addict-2.1',
                                 'deadline_api-8.0',
                                 'farm_environment-1.3..2',
                                 'python-2.7',
                                 'hal_config-1',
                                 'hal_paths-1.6..2']}}

format_version = 2

homepage = 'https://gitlab.rezpipeline.com/internal/deadline_submission_api'

dev_requires = [
    'pytest-4.6',
    'pytest_mock-1.10',
    'addict-2.1',
    'deadline_api-8.0',
    'farm_environment-1.3..2',
    'python-2.7',
    'hal_config-1',
    'hal_paths-1.6..2'
]
