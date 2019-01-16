# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright © 2019 ANSSI. All rights reserved.

import os
import sys

from twisted.application import service
from twisted.python.log import FileLogObserver, ILogObserver

from buildbot.master import BuildMaster

# Setup master:
basedir = os.path.abspath(os.path.dirname(__file__))  # relocatable tac file
configfile = 'master.py'

# note: this line is matched against to check that this is a buildmaster
# directory; do not edit it.
application = service.Application('buildmaster')
application.setComponent(ILogObserver, FileLogObserver(sys.stdout).emit)

# Default umask for server
umask = None

# And run!
m = BuildMaster(basedir, configfile, umask)
m.setServiceParent(application)

# vim: set ft=python ts=4 sts=4 sw=4 tw=79 et:
