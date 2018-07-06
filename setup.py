#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  Copyright 2017 Spotify AB.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing,
#  software distributed under the License is distributed on an
#  "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
#  KIND, either express or implied.  See the License for the
#  specific language governing permissions and limitations
#  under the License.
try:
    from setuptools import setup
    from setuptools.command.test import test as TestCommand
except ImportError:
    from distutils.core import setup
    from distutils.cmd import Command as TestCommand

import sys


class tox(TestCommand):
    description = "run tox tests"
    user_options = [("tox-args=", None, "Arguments to pass to tox")]

    def initialize_options(self):
        TestCommand.initialize_options(self)
        self.tox_args = ""

    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        import os
        os.chdir(os.path.dirname(os.path.realpath(__file__)))
        # import here, cause outside the eggs aren't loaded
        import tox
        errno = tox.cmdline(args=self.tox_args.split())
        sys.exit(errno)


setup(pbr=True, scripts=["bin/tfr-tool"])
