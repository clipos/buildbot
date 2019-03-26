# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright © 2019 ANSSI. All rights reserved.

# According to Docker Hub, fedora:latest always points to the latest stable
# release of Fedora (i.e. as of 2019-03-26, this means Fedora 29).
FROM fedora:latest

# [BUILDBOT-SPECIFIC] Get buildbot-worker version to install to make it match
# the one used by the master and the buildbot worker name to use for this
# image.
ARG BUILDBOT_WORKER_VERSION

ENV LANG=C.UTF-8

# Upgrade already installed packages
RUN dnf upgrade --assumeyes

# Install all the required packages for this environment. See the section
# related to the development environment setup in the CLIP OS project
# documentation for the rationale behind every package:
RUN dnf install --assumeyes \
        python2 python3-devel \
        gnupg git git-lfs openssh-clients \
        @development-tools \
        runc sudo squashfs-tools \
        qemu libvirt-devel libvirt-daemon \
        rust cargo \
        dumb-init \
        bsdtar \
    && dnf clean all

# As repo is not packaged by Fedora, let's resort to the good old fetch from
# Google servers (but verify at least the integrity of the downloaded binary):
# The command below is inspired from the AOSP environment Dockerfile:
#   https://android.googlesource.com/platform/build/+/master/tools/docker/Dockerfile
# and has been updated with the latest SHA-256 checksum of repo 1.25:
#   https://source.android.com/setup/build/downloading.
RUN curl -o /usr/local/bin/repo 'https://storage.googleapis.com/git-repo-downloads/repo' &&\
    echo "d06f33115aea44e583c8669375b35aad397176a411de3461897444d247b6c220  /usr/local/bin/repo" | sha256sum --strict -c - &&\
    chmod a+x /usr/local/bin/repo

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
    echo >info/host "Dockerized CLIP OS build environment based on latest Fedora stable release. Docker image generated on $(date --utc +%Y-%m-%dT%H:%M:%SZ)"

# [BUILDBOT-SPECIFIC] Sets the entrypoint to buildbot-worker and sets default
# command line arguments to it:
ENTRYPOINT ["dumb-init", "--"]
CMD ["twistd", "-ny", "buildbot.tac"]
