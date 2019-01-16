# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright © 2019 ANSSI. All rights reserved.

"""Build steps abstraction class for the CLIP OS Project (or any of its
derivatives) buildbot instances"""

import os
import shlex
import textwrap

from typing import Optional, List, Dict, Union, Any, Sequence

# Convenience shorter names:
from buildbot.plugins import steps, util
from buildbot.process.properties import Property

from .commons import line  # utility functions and stuff


class ToolkitEnvironmentShellCommand(steps.ShellCommand):
    """Shell command step within a toolkit activated environment"""

    # The path to the file to source to activate the CLIP OS toolkit
    # environment (path relative from the repo root):
    SOURCE_ME_FILE = "toolkit/source_me.sh"

    def __init__(self,
                 command: Union[str, Sequence[Union[str, Property, util.Interpolate]]],
                 *args: Any, **kwargs: Any
                ) -> None:
        if isinstance(command, str):
            super().__init__(
                command=["/usr/bin/env", "bash", "-c",
                         "source {sourceme}\n\n{command}".format(
                             sourceme=shlex.quote(self.SOURCE_ME_FILE),
                             command=command,
                         )],
                *args,
                **kwargs,
            )
        elif isinstance(command, (list, tuple)):
            super().__init__(
                command=["/usr/bin/env", "bash", "-c",
                         'source {sourceme}; exec "$0" "$@"'.format(
                             sourceme=shlex.quote(self.SOURCE_ME_FILE),
                         )] + list(command),
                *args,
                **kwargs,
            )
        else:
            raise TypeError("command is not of expected type")


# vim: set ft=python ts=4 sts=4 sw=4 et tw=79:
