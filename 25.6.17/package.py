# -*- coding: utf-8 -*-

name = 'maya_dy_plugins'

version = '0.3.0'

description = 'dy plugins in Maya.'

authors = ['Yu.Dong']

tools = []

plugin_for = ['maya']

requires = [
    'maya-2020..2025',
]

variants = [
    ['platform-windows']
]

def commands():
    """Set up package."""
    MAYA_MAJOR_VERSION = getenv('REZ_MAYA_MAJOR_VERSION')
    MAYA_MINOR_VERSION = getenv('REZ_MAYA_MINOR_VERSION')

    HOUDINI_VERSION_FOLDER = "maya{MAYA_MAJOR_VERSION}.{MAYA_MINOR_VERSION}".format(
        MAYA_MAJOR_VERSION=MAYA_MAJOR_VERSION,
        MAYA_MINOR_VERSION=MAYA_MINOR_VERSION
    )

    env.PYTHONPATH.prepend("{this.root}/%s/site-packages" % HOUDINI_VERSION_FOLDER)  # noqa: F821


uuid = '8ad1e5a4-11a4-4958-9b7a-ee2c8d0e27c9'

timestamp = 1651480808

tests = {}

format_version = 3

homepage = 'https://gitlab.rezpipeline.com/internal/maya_dy_toolbox'
