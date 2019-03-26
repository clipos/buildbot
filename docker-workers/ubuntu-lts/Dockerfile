# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright © 2019 ANSSI. All rights reserved.

# According to Docker Hub, ubuntu:latest always points to the latest LTS
# release of Ubuntu (i.e. as of 2019-03-26, this means Ubuntu 18.04).
FROM ubuntu:latest

# [BUILDBOT-SPECIFIC] Get buildbot-worker version to install to make it match
# the one used by the master and the buildbot worker name to use for this
# image.
ARG BUILDBOT_WORKER_VERSION

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
        cargo \
        runc qemu libvirt-dev libvirt-daemon \
        libarchive-tools

# [BUILDBOT-SPECIFIC] Installs pip in order to be able to install the
# buildbot-worker:
RUN apt-get -y -q --no-install-recommends install \
        build-essential python3-dev python3-setuptools python3-pip dumb-init

# Create an unprivileged user:
# [BUILDBOT-SPECIFIC] The name and the user's home directory location are
# special for buildbot-worker:
RUN useradd -m -d /var/buildbot -U -G users buildbot

# This unprivileged user is not so unprivileged because it can still use sudo
# to get root privileges within the container.
# This strangeness is explained by the fact that cosmk automatically recalls
# itself through sudo to get root privileges but still lower its running
# privileges for sections of code that do not require root permissions (see the
# ElevatedPrivileges class and its usage in the cosmk Python project for
# further details).
RUN echo "buildbot ALL=(ALL:ALL) NOPASSWD: ALL" \
        > /etc/sudoers.d/user-without-passwd \
        && chmod 0440 /etc/sudoers.d/user-without-passwd

# Drop to non-root user and change working directory to its homedir:
USER buildbot
WORKDIR /var/buildbot

# [BUILDBOT-SPECIFIC] Install buildbot-worker and create the worker working
# directory:
RUN pip3 install --user --upgrade --force-reinstall pip &&\
    /var/buildbot/.local/bin/pip install --user \
            "buildbot-worker==${BUILDBOT_WORKER_VERSION:?}"

# [BUILDBOT-SPECIFIC] Override PATH with Pip user-local bin location:
ENV PATH="/var/buildbot/.local/bin:${PATH}"

# [BUILDBOT-SPECIFIC] Create the buildbot-worker working directory and copy the
# Twisted application configuration for the buildbot-worker application (this
# tac file has been tweaked for special use via the DockerLatentWorker class in
# the buildmaster):
RUN mkdir /var/buildbot/worker
COPY buildbot.tac /var/buildbot/worker/buildbot.tac
WORKDIR /var/buildbot/worker
VOLUME /var/buildbot/worker/workspaces

# [BUILDBOT-SPECIFIC] Sets metadata to show up in the Buildbot UI that
# describes this worker:
RUN mkdir -p info &&\
    echo >info/host "Dockerized CLIP OS build environment based on latest Ubuntu LTS release. Docker image generated on $(date --utc +%Y-%m-%dT%H:%M:%SZ)"

# [BUILDBOT-SPECIFIC] Sets the entrypoint to buildbot-worker and sets default
# command line arguments to it:
ENTRYPOINT ["dumb-init", "--"]
CMD ["twistd", "-ny", "buildbot.tac"]
