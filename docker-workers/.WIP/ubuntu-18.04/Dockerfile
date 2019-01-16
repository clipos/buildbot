# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright © 2019 ANSSI. All rights reserved.

FROM ubuntu:18.04

# TODO, FIXME: This Dockerfile is still a work-in-progress as it has been
# retrieved from an old version intended to be used by the legacy (and now
# abandoned) Jenkins CI.
#
# Here is a coarse-grained to-do list to make this Dockerfile usable again:
#   - review the build dependencies installed in that Docker image to match the
#     current build dependencies of the CLIP OS project
#   - install the Buildbot worker (following the BUILDBOT_VERSION build
#     argument provided by the builder and meant to be the same as the
#     Buildmaster)
#   - use a process supervisor/init system (e.g. dumb-init) to make sure that
#     the zombie child process by will be reaped if a build job happens to fail
#     and leave processes behind that will be reattached to PID 1
#   - use the tweaked "buildbot.tac" file
#   - any other missing point?
# The "debian-sid" Dockerfile can be used as a reference to complete this to-do
# list as this Dockerfile implements everything and is known to work without
# issue with Buildbot.
#
# The following command has been voluntarily added to fail the Docker image
# build as the resulting Docker image would not be usable with Buildbot without
# the missing parts described above.
RUN echo "Work-in-progress: This Dockerfile needs to be reworked." && false

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

# Gets rid of "(Reading database ... 5%" output.
RUN echo 'Dpkg::Use-Pty "0";' > /etc/apt/apt.conf.d/00usepty

# Update both packages index and installed packages
RUN apt-get -y -q update && apt-get -y -q --no-install-recommends upgrade

# Install all the required packages for this environment. See the section
# related to the development environment setup in the CLIP OS project
# documentation for the rationale behind every package:
RUN apt-get -y -q --no-install-recommends install \
        git git-lfs python2.7 gnupg2 repo \
        python3 python3-venv python3-dev build-essential pkg-config \
        bash sudo util-linux squashfs-tools coreutils locales \
        runc qemu libvirt-dev libvirt-daemon

# Create an unprivileged user
RUN useradd -m -U -G users user

# This unprivileged user is not so unprivileged because it can still use sudo
# to get root privileges within the container.
# This strangeness is explained by the fact that cosmk automatically recalls
# itself through sudo to get root privileges but still lower its running
# privileges for sections of code that do not require root permissions (see the
# ElevatedPrivileges class and its usage in the cosmk Python project for
# further details).
RUN echo "user ALL=(ALL:ALL) NOPASSWD: ALL" \
        > /etc/sudoers.d/user-without-passwd \
        && chmod 0440 /etc/sudoers.d/user-without-passwd

USER user
