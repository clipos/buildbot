# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright © 2019 ANSSI. All rights reserved.

"""CLIP OS Project Buildbot continuous integration master node configuration"""

import datetime
import json
import os
import string
import sys

from typing import Dict, Any, Optional

import clipos

from buildbot.plugins import changes, schedulers, util, worker
from buildbot.schedulers.forcesched import oneCodebase
from clipos.commons import line  # utility functions and stuff


#
# PRIVATE SETUP SETTINGS RELATIVE TO THE BUILDBOT MASTER DEPLOYMENT
#
# There are some private settings that depends directly on the way this
# Buildbot master instance has been deployed. Usually these settings come from
# the environment variables of the Docker container instance running the
# Buildbot master (e.g. BUILDBOT_MASTER_PB_PORT which indicates the port number
# on which Buildbot is expected to listen).
# However, since the environment may be exposed in some of the builds and since
# some of these variables may contain sensitive information (e.g. the password
# to the Buildbot database), a "setup_settings.json" file is expected to be
# created by the Docker container entrypoint script which is also in charge of
# stripping those values from the environment. This avoids exposing such
# settings in the Buildbot local workers.
#

# If the provided filepath cannot be found, the following class will load
# default dummy settings that will correspond to a local deployment for testing
# purposes (mainly for debugging purposes for developers).
setup = clipos.buildmaster.SetupSettings("setup_settings.json")

# Just a quick check to be sure the artifacts directory is there and properly
# set up (otherwise, fail miserably not to leave a chance for a builder to run
# with this):
if not os.access(setup.artifacts_dir, os.R_OK | os.W_OK | os.X_OK):
    raise Exception(line(
        """Artifacts directory {!r} seems not writable by the Buildbot
        user.""").format(setup.artifacts_dir))


#
# BUILDBOT MASTER CONFIGURATION DATA STRUCTURE INITIALIZATION
#
# This is the dictionary that the buildmaster pays attention to. The variable
# MUST be named BuildmasterConfig. A shorter alias is defined for typing
# convenience below.
#

# Also define a shorter alias ("c") to save typing:
BuildmasterConfig = c = setup.buildmaster_config_base()


#
# WORKERS
#
# The 'workers' list defines the set of recognized workers. Each element is a
# Worker object, specifying a unique worker name and password.
#

# This worker MUST only be used for build jobs requiring access to the
# Docker socket. The builders tied to this worker should be carefully reviewed
# as some nasty stuff can be done when a user has access to the Docker daemon:
docker_operations_worker = worker.LocalWorker('_docker-client-localworker')

# All the Docker latent workers defined and usable by the CLIP OS project
# buildbot:
all_clipos_docker_latent_workers = []
for flavor in clipos.workers.DockerLatentWorker.FLAVORS:
    # Generate both privileged and unprivileged versions of container workers:
    for privileged in [False, True]:
        all_clipos_docker_latent_workers.append(
            clipos.workers.DockerLatentWorker(
                flavor=flavor,
                privileged=privileged,
                container_network_mode=setup.docker_worker_containers_network_mode,
                docker_host=setup.docker_host_uri,
                use_volume_for_workspaces=True,

                # By default, max_builds is unlimited, reduce this:
                max_builds=5,  # TODO: any better heuristic?
            )
        )

c['workers'] = [
    # The worker for the Docker operations (create Docker images to be used as
    # Docker latent workers):
    docker_operations_worker,

    # All the Docker latent workers for CLIP OS build (the build envs):
    *all_clipos_docker_latent_workers,
]

# Since the various flavors of Buildbot worker are expected to produce the same
# result
reference_worker_flavor = 'debian-sid'



#
# BUILDERS
#
# The 'builders' list defines the Builders, which tell Buildbot how to perform
# a build: what steps, and which workers can execute them.  Note that any
# particular build will only take place on one worker.
#

# Builders that build the CLIP OS Dockerized build environment images to be
# then used by the clipos.workers.DockerLatentWorker:
docker_buildenv_image_builders = []
for flavor, props in clipos.workers.DockerLatentWorker.FLAVORS.items():
    docker_buildenv_image_builders.append(
        util.BuilderConfig(
            name='docker-worker-image env:{}'.format(flavor),  # keep this short
            description=line(
                """Build the Docker image to use as a Buildbot Docker latent
                worker based upon a {} userland.""").format(
                    props['description']),
            tags=['docker-worker-image', "docker-env:{}".format(flavor)],

            # Temporary: Always build on the worker that have access to the
            # Docker socket:
            workernames=[
                docker_operations_worker.name,
            ],

            factory=clipos.build_factories.BuildDockerImage(
                flavor=flavor, buildmaster_setup=setup),
        )
    )

# The builder that generates the repo dir and git lfs archive artifacts from
# scratch:
repo_sync_builder = util.BuilderConfig(
    name='repo-sync',
    description=line(
        """Synchronize the CLIP OS source tree and produce a tarball from the
        ".repo" directory contents. This tarball is then archived as a reusable
        artifact for the other builders. This is done in order to speed up the
        other builds and avoid overloading the Git repositories server with
        constant repo syncs."""),
    tags=['repo-sync', 'update-artifacts'],

    # The reference CLIP OS build environemnt latent Docker worker that is NOT
    # privileged:
    workernames=[
        worker.name for worker in all_clipos_docker_latent_workers
        if worker.flavor == reference_worker_flavor and not worker.privileged
    ],

    factory=clipos.build_factories.RepoSyncFromScratchAndArchive(
        # Pass on the buildmaster setup settings
        buildmaster_setup=setup,
    ),

    properties={
        "cleanup_workspace": True,
    },
)

# Builders for CLIP OS for master branch of manifest for all the build
# environment flavors:
clipos_fromscratch_builders = []
for flavor in clipos.workers.DockerLatentWorker.FLAVORS:
    builder = util.BuilderConfig(
        name='clipos env:{}'.format(flavor),
        tags=['clipos', 'from-scratch', 'docker-env:{}'.format(flavor)],
        workernames=[
            worker.name for worker in all_clipos_docker_latent_workers
            if worker.flavor == flavor and worker.privileged
        ],
        factory=clipos.build_factories.ClipOsProductBuildBuildFactory(
            # Pass on the buildmaster setup settings
            buildmaster_setup=setup,
        ),
        properties={
            "cleanup_workspace": True,
            "force_source_tree_artifacts_fetch": False,
            "buildername_providing_repo_quicksync_artifacts": repo_sync_builder.name,
        },
    )
    # Keep a reference on the reference builder environment for the nightly
    # scheduler:
    if flavor == reference_worker_flavor:
        clipos_fromscratch_on_reference_builder = builder
    clipos_fromscratch_builders.append(builder)

clipos_incremental_on_reference_builder = util.BuilderConfig(
    name='clipos incremental env:{}'.format(reference_worker_flavor),
    tags=['clipos', 'incremental-build',
          'docker-env:{}'.format(reference_worker_flavor)],
    workernames=[
        worker.name for worker in all_clipos_docker_latent_workers
        if worker.flavor == reference_worker_flavor and worker.privileged
    ],
    factory=clipos.build_factories.ClipOsProductBuildBuildFactory(
        # Pass on the buildmaster setup settings
        buildmaster_setup=setup,
    ),
    properties={
        "cleanup_workspace": False,
        "force_source_tree_artifacts_fetch": False,
        "buildername_providing_repo_quicksync_artifacts": repo_sync_builder.name,

        "reuse_sdks_artifact": True,
        "buildername_providing_sdks_artifact": clipos_fromscratch_on_reference_builder.name,
    },
)

# Customizable build for CLIP OS
customizable_clipos_builder = util.BuilderConfig(
    name='clipos custom env:{}'.format(reference_worker_flavor),
    tags=['clipos', 'custom', 'docker-env:{}'.format(reference_worker_flavor)],
    workernames=[
        worker.name for worker in all_clipos_docker_latent_workers
        if worker.flavor == reference_worker_flavor and worker.privileged
    ],
    factory=clipos.build_factories.ClipOsProductBuildBuildFactory(
        # Pass on the buildmaster setup settings
        buildmaster_setup=setup,
    ),
    properties={
        # new
        "buildername_providing_repo_quicksync_artifacts": repo_sync_builder.name,
        #"buildername_providing_sdks_artifact": clipos_fromscratch_on_reference_builder.name,
    },
)


c['builders'] = [
    # All the CLIP OS Dockerized build env image builders:
    *docker_buildenv_image_builders,

    # Repo sync test
    repo_sync_builder,

    # CLIP OS build from scratch
    *clipos_fromscratch_builders,

    # CLIP OS incremental build from the prebuild artifacts from the "from
    # scratch" identical build
    clipos_incremental_on_reference_builder,

    # Fully customizable CLIP OS builder
    customizable_clipos_builder,
]



#
# SCHEDULERS
#
# Configure the Schedulers, which decide how to react to incoming changes.
#

# CLIP OS builds schedulers:
clipos_incremental_build_intraday_sched = schedulers.Nightly(
    name='clipos-master-intraday-incremental-build',
    builderNames=[
        clipos_incremental_on_reference_builder.name,
    ],
    dayOfWeek='1,2,3,4,5',  # only work days: from Monday (1) to Friday (5)
    hour=12, minute=30,  # at 12:30 (i.e. during lunch)
    codebases={"": {
        "repository": setup.clipos_manifest_git_url,
        "branch": "master",
    }},
)

clipos_build_nightly_sched = schedulers.Nightly(
    name='clipos-master-nightly-build',
    builderNames=[
        clipos_fromscratch_on_reference_builder.name,
    ],
    dayOfWeek='1,2,3,4,5',  # only work days: from Monday (1) to Friday (5)
    hour=0, minute=45,  # at 00:45
    codebases={"": {
        "repository": setup.clipos_manifest_git_url,
        "branch": "master",
    }},
)

repo_sync_nightly_sched = schedulers.Nightly(
    name='repo-sync-nightly-update',
    builderNames=[
        repo_sync_builder.name,
    ],
    dayOfWeek='1,2,3,4,5',  # only work days: from Monday (1) to Friday (5)
    hour=0, minute=0,  # at 00:00
    codebases={"": {
        "repository": setup.clipos_manifest_git_url,
        "branch": "master",
    }},
)

clipos_build_weekly_sched = schedulers.Nightly(
    name='clipos-master-weekly-build',
    builderNames=[
        *(builder.name for builder in clipos_fromscratch_builders),
    ],
    dayOfWeek='6',  # on Saturdays
    hour=12, minute=0,  # at noon
    codebases={"": {
        "repository": setup.clipos_manifest_git_url,
        "branch": "master",
    }},
)

# Buildbot worker Dockerized environment build schedulers:
docker_buildenv_image_rebuild_weekly_sched = schedulers.Nightly(
    name='docker-workers-weekly-rebuild',
    builderNames=[
        # Rebuild all the Dockerized CLIP OS build environments on weekends:
        *(builder.name for builder in docker_buildenv_image_builders),
    ],
    dayOfWeek='6',  # on Saturdays
    hour=9, minute=0,  # at 09:00
    codebases={"": {
        "repository": setup.config_git_clone_url,
        "branch": setup.config_git_revision,
    }},
)

# FIXME, TODO: Scheduler that tracks the branch evolution from the
# change_source declarations below:
#tobedone_sched = schedulers.SingleBranchScheduler(
#    name='all',
#    change_filter=util.ChangeFilter(branch='master'),
#    treeStableTimer=None,
#    builderNames=[
#       # TODO
#    ],
#)

# Force rebuild Docker images
docker_buildenv_image_rebuild_force_sched = schedulers.ForceScheduler(
    name='force-docker-buildenv-image',
    buttonName="Force a rebuild of this Dockerized build environment now",
    label="Rebuild now a Docker build environement image",
    builderNames=[
        *(builder.name for builder in docker_buildenv_image_builders),
    ],
    codebases=oneCodebase(
        project=None,
        repository=setup.config_git_clone_url,
        branch=setup.config_git_revision,
        revision=None,
    ),
)

# Scheduler to force a resynchronizaion from scratch of the CLIP OS source
# tree:
repo_sync_force_sched = schedulers.ForceScheduler(
    name='force-repo-sync-clipos',
    buttonName="Force a synchronization from scratch of the source tree",
    label="Synchronization from scratch",
    builderNames=[
        # Only one builder is eligible to this scheduler:
        repo_sync_builder.name,
    ],
    codebases=oneCodebase(
        project=None,
        repository=setup.clipos_manifest_git_url,
        branch="master",
        revision=None,
    ),
)

# Scheduler for the CLIP OS on-demand custom builds:
clipos_custom_build_force_sched = schedulers.ForceScheduler(
    name='clipos-custom-build',
    buttonName="Start a custom build",
    label="Custom build",
    builderNames=[
        # All the builders that build a CLIP OS image:
        *(builder.name for builder in c['builders']
          if 'clipos' in builder.tags),
    ],
    codebases = [
        util.CodebaseParameter(
            codebase='',
            label="CLIP OS source manifest",
            project='clipos',
            repository=util.StringParameter(
                name="repository",
                label="Manifest repository URL",
                default=setup.clipos_manifest_git_url,
                size=100,
            ),
            branch=util.StringParameter(
                name="branch",
                label="Manifest branch to use",
                default="master",
                size=50,
            ),
            revision=None,
        ),
    ],
    properties=[util.NestedParameter(
        name="",  # parameter namespacing is cumbersome to manage
        layout="tabs",
        fields=[

            util.NestedParameter(
                name="",  # parameter namespacing is cumbersome to manage
                label="Source tree checkout",
                layout="vertical",
                fields=[
                    util.BooleanParameter(
                        name="use_local_manifest",
                        label="Use the repo local manifest below",
                        default=False,
                    ),
                    util.TextParameter(
                        name="local_manifest_xml",
                        label="Local manifest to apply changes to the source tree",
                        default=r"""
<manifest>
  <!-- This is an example of a local-manifest file: tweak it to your needs. -->

  <remote name="dummyremote" fetch="https://github.com/dummy" />

  <remove-project name="src_external_uselesscomponent" />

  <project path="products/dummyos" name="products_dummyos" remote="dummyremote" revision="refs/changes/42/1342" />
</manifest>
                        """.strip(),
                        cols=80, rows=6,
                    ),
                ],
            ),

            util.NestedParameter(
                name="",  # parameter namespacing is cumbersome to manage
                label="Workspace settings",
                layout="vertical",
                fields=[
                    util.BooleanParameter(
                        name="cleanup_workspace",
                        label="Clean up the workspace beforehand",
                        default=True,
                    ),
                    util.BooleanParameter(
                        name="force_source_tree_artifacts_fetch",
                        label="Force the fetch of the source tree quick-sync artifacts",
                        default=False,
                    ),
                ],
            ),

            util.NestedParameter(
                name="",  # parameter namespacing is cumbersome to manage
                label="CLIP OS build process options",
                layout="vertical",
                fields=[
                    util.BooleanParameter(
                        name="reuse_sdks_artifact",
                        label="Reuse SDKs artifacts instead of bootstrapping SDKs from scratch",
                        default=True,
                    ),
                    util.ChoiceStringParameter(
                        name="buildername_providing_sdks_artifact",
                        label="Builder name from which retrieving SDKs artifact (latest artifacts will be used)",
                        choices=[
                            # All the builders that build a CLIP OS image from
                            # scratch:
                            *(builder.name for builder in c['builders']
                              if ('clipos' in builder.tags and
                                  'from-scratch' in builder.tags))
                        ],
                        default=clipos_fromscratch_on_reference_builder.name,
                    ),
                ],
            ),

        ],
    )],
)

c['schedulers'] = [
    # Intra-day schedulers:
    clipos_incremental_build_intraday_sched,

    # Nightly schedulers:
    repo_sync_nightly_sched,
    clipos_build_nightly_sched,

    # Weekly schedulers:
    clipos_build_weekly_sched,
    docker_buildenv_image_rebuild_weekly_sched,

    # Forced schedulers:
    repo_sync_force_sched,
    docker_buildenv_image_rebuild_force_sched,
    clipos_custom_build_force_sched,
]



#
# CHANGESOURCES
#
# The 'change_source' setting tells the buildmaster how it should find out
# about source code changes.
#

c['change_source'] = []

# TODO, FIXME: Declare a proper change_source poller:
#if setup.config_git_clone_url:
#    c['change_source'].append(
#        changes.GitPoller(
#            repourl=setup.config_git_clone_url,
#            workdir='gitpoller-workdir',
#            branch=setup.config_git_revision,
#            pollInterval=600,     # every 10 minutes
#        )
#    )



#
# JANITORS
#

# Configure a janitor which will delete all build logs to avoid clogging up the
# database.
c['configurators'] = [
    util.JanitorConfigurator(
        logHorizon=datetime.timedelta(weeks=12), # older than roughly 3 months
        dayOfWeek=0,  # on Sundays
        hour=12, minute=0,  # at noon
    ),
]



#
# BUILDBOT SERVICES
#
# 'services' is a list of BuildbotService items like reporter targets. The
# status of each build will be pushed to these targets. buildbot/reporters/*.py
# has a variety to choose from, like IRC bots.
#

c['services'] = []


# vim: set ft=python ts=4 sts=4 sw=4 tw=79 et:
