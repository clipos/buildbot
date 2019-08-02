# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright © 2019 ANSSI. All rights reserved.

import re
import string

from typing import Any, Optional, List, Dict

import buildbot
import buildbot.worker.docker

# Convenience shorter names:
from buildbot.plugins import steps, util


class DockerLatentWorker(buildbot.worker.docker.DockerLatentWorker):
    """Docker latent worker for CLIP OS project builds

    .. warning::
        We may need to run the CLIP OS build environment Docker container as
        privileged (i.e. the container will have all the POSIX capabilities
        available and have full access to the devices of the host) for multiple
        reasons:

        1. cosmk makes use of squashfs files as support for the SDK container
           images. This requires to be able to create and manipulate loop
           devices (i.e. ``/dev/loop*``) to mount these squashfs files.
        2. ``CAP_SYS_ADMIN`` is also required to run OCI containers with the
           ``runc`` runtime (e.g. for SDK containers) for namespaces creation
           and for mountpoint creation.
        3. SDK containers can be shown some devices (such as ``/dev/kvm``) for
           special programs running within SDKs (e.g. libguestfs).

    """

    # The Docker images to use as CLIP OS build environments per distro
    # userland:
    FLAVORS = {
        "debian-sid": {
            "docker_build_context": "docker-workers/debian-sid",
            "description": "Debian sid with a CLIP OS build environment",
        },
        "fedora-stable": {
            "docker_build_context": "docker-workers/fedora-stable",
            "description": "Latest stable Fedora with a CLIP OS build environment",
        },
        "ubuntu-lts": {
            "docker_build_context": "docker-workers/ubuntu-lts",
            "description": "Latest Ubuntu LTS with a CLIP OS build environment",
        },
    }

    # The basedir for the buildbot worker in the Docker container (see the
    # buildbot.tac of the worker for more details):
    WORKSPACES_DIR = "/var/buildbot/worker/workspaces"

    # The name to use for the Docker images tags of the CLIP OS build
    # environment/buildbot Dockerized workers:
    DOCKER_IMAGE_TAG_PREFIX = "clipos_buildbot-worker"

    # The name to use for the Docker images tags of the CLIP OS build
    # environment/buildbot Dockerized workers:
    DOCKER_VOLUME_NAME_FOR_WORKSPACES_PREFIX = "clipos_buildbot-worker-workspaces"

    @classmethod
    def docker_image_tag(cls, flavor: str):
        return "{}:{}".format(cls.DOCKER_IMAGE_TAG_PREFIX, flavor)

    def __init__(self,
                 flavor: str,
                 docker_host: str,
                 buildmaster_host_for_dockerized_workers: str,
                 privileged: bool = False,
                 container_network_mode: Optional[str] = None,
                 **kwargs: Any) -> None:
        # Custom properties:
        self.flavor = flavor
        self.privileged = privileged

        # Forge the name to use for this worker:
        name = self.flavor
        if self.privileged:
            name += "_privileged"

        docker_image = self.docker_image_tag(self.flavor)

        # Override hostconfig
        hostconfig = kwargs.get("hostconfig", dict())
        try:
            del kwargs["hostconfig"]
        except KeyError:
            pass
        # Custom Docker container properties (see API documentation of both
        # Buildbot and docker-py):
        if container_network_mode:
            hostconfig.update({"network_mode": container_network_mode})
        hostconfig.update({"privileged": privileged})

        # Override properties with a set of custom properties for the builders
        # that will make use of this worker:
        properties = kwargs.get("properties", dict())
        try:
            del kwargs["properties"]
        except KeyError:
            pass
        properties.update({
            "clipos_docker_image_flavor": self.flavor,
        })

        # The volume name to host the worker workspaces
        self.docker_volume_name_for_workspaces = "{}_{}".format(
            self.DOCKER_VOLUME_NAME_FOR_WORKSPACES_PREFIX,
            re.sub('[^A-Za-z0-9]+', '_', name))

        # Override volumes:
        volumes = kwargs.get("volumes", list())
        try:
            del kwargs["volumes"]
        except KeyError:
            pass
        volumes.append('{volume_name}:{workspaces_dir}'.format(
            volume_name=self.docker_volume_name_for_workspaces,
            workspaces_dir=self.WORKSPACES_DIR))

        # and then call parent init that will do the rest of the work:
        super().__init__(
            name,

            # Leave the parent LatentWorker class generate a random password
            # (this one will be communicated via a environment variable which
            # will be carefully stripped before processing the build job work):
            password=None,

            # Tell to the Docker worker to be created to join the Buildmaster
            # to the proper IP address:
            masterFQDN=buildmaster_host_for_dockerized_workers,

            # Our Docker settings:
            image=docker_image,
            docker_host=docker_host,
            autopull=False,
            alwaysPull=False,
            hostconfig=hostconfig,
            volumes=volumes,

            # Properties brough by the worker to builders:
            properties=properties,

            **kwargs,  # the rest of the parameters
        )

# vim: set ft=python ts=4 sts=4 sw=4 et tw=79:
