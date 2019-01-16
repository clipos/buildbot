# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright © 2019 ANSSI. All rights reserved.

"""Miscellanous utility functions and helpers that may be used globally in this
code base."""

import textwrap


def rewrap(msg: str) -> str:
    """Rewrap a message by stripping the unneeded indentation and removing
    leading and trailing whitespaces."""
    return textwrap.dedent(msg).strip()


def line(msg: str) -> str:
    """Rewrap a message by stripping the unneeded indentation, removing leading
    and trailing whitespaces and joining all the lines into one unique text
    line.

    >>> line('''
            A potentially long message that
            can overflow the 79 chars limit
            of PEP 8.
    ''')
    "A potentially long message that can overflow the 79 chars limit of PEP 8."

    """
    return ' '.join([line.strip() for line in msg.split("\n")
                                  if len(line.strip())])

# vim: set ft=python ts=4 sts=4 sw=4 et tw=79:
