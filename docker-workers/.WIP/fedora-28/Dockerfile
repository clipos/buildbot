# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright © 2019 ANSSI. All rights reserved.

FROM fedora:28

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

ENV LANG=C.UTF-8

# Update everything and install required packages:
#   - Python 2 for repo and Python 3.6 for the CLIP OS toolkit
#   - GnuPG 2 for repo
#   - qemu, OVMF and libvirt for VM recipes
#   - build-essential and Python 3.6 development bindings are required for some
#     Python packages which require to compile some CPython bindings.
RUN dnf upgrade --assumeyes \
    && dnf install --assumeyes \
        python2 python3-devel \
        gnupg git git-lfs openssh-clients \
        @development-tools \
        runc sudo squashfs-tools \
        qemu libvirt-devel libvirt-daemon \
        rust cargo \
    && dnf clean all

# Install repo
COPY repo /usr/local/bin/repo
RUN chmod a+x /usr/local/bin/repo

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
