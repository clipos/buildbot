# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright © 2019 ANSSI. All rights reserved.

import os
import sys

from twisted.application import service
from twisted.python.log import FileLogObserver, ILogObserver

from buildbot_worker.bot import Worker

# Setup worker:
basedir = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                       'workspaces')
application = service.Application('buildbot-worker')

# Special handling of workspaces directory (i.e. basedir) that happens to be
# owned by root (i.e. when it is a newly created Docker volume):
if os.path.isdir(basedir):
    stat = os.stat(basedir)
    if stat.st_uid == 0 and stat.st_gid == 0:
        import subprocess
        try:
            subprocess.run(["sudo", "chown",
                            "{uid}:{gid}".format(uid=os.getuid(),
                                                 gid=os.getgid()),
                            basedir], check=False)
        except FileNotFoundError:
            # sudo is not found: fail silently here, the error will reappear in
            # Worker loop logs anyway
            pass
else:
    os.makedirs(basedir)

# Log on stdout rather than in a file:
application.setComponent(ILogObserver, FileLogObserver(sys.stdout).emit)

# Fetch the configuration from the environment vars passed by
# DockerLatentWorker class:
try:
    buildmaster_host = os.environ["BUILDMASTER"]
    port = int(os.environ["BUILDMASTER_PORT"])
    workername = os.environ["WORKERNAME"]
    passwd = os.environ["WORKERPASS"]
except KeyError:
    print("A environment variable that would normally be provided by the "
          "DockerLatentWorker class is missing in the current environment.",
          file=sys.stderr)
    print("Ensure to run this Docker image through the use of the "
          "DockerLatentWorker class in a buildbot master instance.",
          file=sys.stderr)
    raise

# Delete the password and all the other environemtn vairables provided by
# DockerLatentWorker class from the environment so that they won't leak in the
# log output of this worker builds logs.
for envvarname in ["BUILDMASTER", "BUILDMASTER_PORT", "WORKERNAME",
                   "WORKERPASS"]:
    del os.environ[envvarname]

# Misc config:
keepalive = 600
umask = None
maxdelay = 300
allow_shutdown = None
maxretries = 10

# And run!
s = Worker(buildmaster_host, port, workername, passwd, basedir,
           keepalive, umask=umask, maxdelay=maxdelay,
           allow_shutdown=allow_shutdown, maxRetries=maxretries)
s.setServiceParent(application)

# vim: set ft=python ts=4 sts=4 sw=4 tw=79 et:
