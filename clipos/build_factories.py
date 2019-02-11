# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright © 2019 ANSSI. All rights reserved.

"""Build factory classes for the CLIP OS Project buildbot instance"""

import os
import re
import shlex
import string
import textwrap

from typing import Optional, List, Dict, Any, Callable, Union, Tuple

import buildbot
import buildbot.process.factory

# Convenience shorter names:
from buildbot.plugins import steps, util
from buildbot.process.buildstep import BuildStep
from buildbot.process.properties import Property

import clipos
import clipos.buildmaster
import clipos.steps
import clipos.workers

from .commons import line  # utility functions and stuff


def _get_artifact_path(base_path: str,
                       buildername_property_name: str,
                       *path_items: str):
    """Returns a Renderable function that returns the path to the artifact name
    from the builder name (contained into the `buildername_property_name`
    property) and a list of path items to be appended to that path."""

    @util.renderer
    def renderable(props):
        sanitized_buildername = re.sub(
            r'[^a-zA-Z0-9\.\-\_\:]+', "_",
            props.getProperty(buildername_property_name, ""))
        return os.path.join(base_path, sanitized_buildername, *path_items)
    return renderable


class BuildDockerImage(buildbot.process.factory.BuildFactory):
    """Build a CLIP OS build environment Docker image.

    :param buildbot_worker_version: the Buildbot worker version to pass to the
        Docker build command (which will be used in the Dockerfile) to install
        the expected buildbot-worker version (this Dockerfile is expected to
        set the buildbot-worker as its Docker entrypoint) inside the latent
        worker as a Buildbot agent.

    """

    def __init__(self, flavor: str,
                 buildmaster_setup: clipos.buildmaster.SetupSettings,
                 buildbot_worker_version: Optional[str] = None):
        # Initialize Build factory from parent class:
        super().__init__()

        # Fetch the current configuration repository (which also holds the
        # Dockerfiles for the build workers environments):
        self.addStep(steps.Git(
            name="git",
            description="fetch/synchronize the CLIP OS buildbot Git repository",
            repourl=util.Property("repository"),
            branch=util.Property("branch"),
            mode="full",  # there's no need to keep previous build artifacts
            method="clobber",  # obliterate everything beforehand
        ))

        # Launch Docker build with the expected Dockerfile:
        location_to_dockerfile = os.path.join(self.workdir,
            clipos.workers.DockerLatentWorker.FLAVORS[flavor]['docker_build_context'])
        docker_image_tag = (
            clipos.workers.DockerLatentWorker.docker_image_tag(flavor))

        # use current version if not specified in the props
        if not buildbot_worker_version:
            buildbot_worker_version = str(buildbot.version)

        self.addStep(steps.ShellCommand(
            name="docker build",
            description="build the Dockerized CLIP OS build environment image",
            command=[
                "docker", "build",
                "--no-cache",  # do not use cache to ensure up-to-date images
                "--rm",  # remove intermediate containers
                "--tag", docker_image_tag,
                "--build-arg",
                "BUILDBOT_WORKER_VERSION={}".format(buildbot_worker_version),
                "."  # docker build requires the path to its context
            ],
            workdir=location_to_dockerfile,
            env={
                "DOCKER_HOST": buildmaster_setup.docker_host_uri,
            },
        ))


class ClipOsSourceTreeBuildFactoryBase(buildbot.process.factory.BuildFactory):
    """Build factory base class that provides the methods to manage a CLIP OS
    source tree with both ``repo``, Git LFS filters hacks and the source tree
    artifacts production or reuse to speed up the builds."""

    # The repo group that gathers all the repo projects that make use of Git
    # LFS objects in their tree. See the manifest file for the CLIP OS project
    # for further details:
    REPO_GROUP_FOR_GIT_LFS_BACKED_PROJECTS = "lfs"

    REPO_DIR_ARCHIVE_ARTIFACT_FILENAME = "repo-dir.tar"
    GIT_LFS_SUBDIRECTORIES_ARCHIVE_ARTIFACT_FILENAME = "git-lfs-dirs.tar"

    def __init__(self, *,
                 buildmaster_setup: clipos.buildmaster.SetupSettings):
        # Initialize Build factory from parent class:
        super().__init__()

        self.buildmaster_setup = buildmaster_setup  # Buildbot setup settings

    def cleanupWorkspaceIfRequested(self, keep_artifacts=False):
        """Cleanup the workspace if this is requested via the build property
        "cleanup_workspace"."""

        def assert_cleanup(step: BuildStep) -> bool:
            return step.getProperty("cleanup_workspace")

        self.addStep(steps.ShellCommand(
            name="cleanup workspace",
            description="cleanup workspace",
            haltOnFailure=True,
            doStepIf=assert_cleanup,
            command=["/usr/bin/env", "bash", "-c", textwrap.dedent(
                r"""
                set -e -u -o pipefail

                if [[ "${keep_artifacts:-}" -ne 0 ]]; then
                    echo "Cleanup workspace but keep repo quick-sync artifacts..."
                    sudo find . -mindepth 1 \
                        \! \( -path "./${repodir_archive_filename}" -or \
                              -path "./${gitlfsdirs_archive_filename}" \) \
                        -delete
                else
                    echo "Cleanup workspace completely..."
                    sudo find . -delete
                fi

                # List contents after cleanup (to ease CI debugging)
                ls -la
                """).strip()],
            env={
                "keep_artifacts": "1" if keep_artifacts else "0",
                "repodir_archive_filename": self.REPO_DIR_ARCHIVE_ARTIFACT_FILENAME,
                "gitlfsdirs_archive_filename": self.GIT_LFS_SUBDIRECTORIES_ARCHIVE_ARTIFACT_FILENAME,
            },
        ))

    def syncSources(self, use_repo_quicksync_artifacts: bool = False):
        """Fetch repo manifest for a CLIP OS source tree and synchronize the
        complete source tree from scratch.

        Retrieve the pre-fetched source tree objects (i.e. the ".repo"
        directory and the Git LFS objects) from a builder that have produced
        those artifacts and synchronize the CLIP OS source tree from them. Thus
        it will only fetch the delta from those artifacts contents and the
        actual source tree status.

        .. warning::

           It is still up to the user to provide a builder name that have
           produced the pre-fetched source objects artifacts from the same
           manifest source as the current one.

        """

        additional_git_https_cacerts_provided = bool(
            self.buildmaster_setup.private_settings_addendum and
            self.buildmaster_setup.private_settings_addendum.additional_git_https_cacerts
        )
        alternative_git_lfs_endpoint_url_template_provided = bool(
            self.buildmaster_setup.private_settings_addendum and
            self.buildmaster_setup.private_settings_addendum.alternative_git_lfs_endpoint_url_template
        )

        if additional_git_https_cacerts_provided:
            # Declare the CA certificates in the worker environment before
            # proceeding
            self._addCaCertsForHttpsGitRemotes()

        # Special environment variable set for the "repo sync" command ONLY:
        repo_sync_env = dict()

        if not use_repo_quicksync_artifacts:
            # We are sync'ing from the network and not from the extraction
            # result of a quicksync artifact archive set. Therefore, we can
            # directly use the Git LFS endpoint advertised by the repositories,
            # except if the private settings addendum tells us to fetch the Git
            # LFS objects from another endpoint.

            if alternative_git_lfs_endpoint_url_template_provided:
                # Ensure the Git LFS filters are disabled to prevent from
                # downloading the Git LFS objects from the advertised URL in
                # the repositories (via the file .lfsconfig or simply from the
                # URL inferred by Git LFS with the remote URL) as we will
                # trigger the download manually further down with the
                # alternative Git LFS endpoint URL provided:
                self._uninstallGitLfsFiltersGlobally()
                repo_sync_env.update({
                    "GIT_LFS_SKIP_DOWNLOAD_ERRORS": "1",
                })
            else:
                # Just make sure the Git LFS filters are installed (safety)
                self._installGitLfsFiltersGlobally()

        else:
            # We are sync'ing from the extraction result of a quicksync
            # artifact archive set. Therefore we need to retrieve those
            # artifacts and extract them.

            # Ensure the Git LFS filters are disabled to prevent from
            # downloading the Git LFS objects automatically as we are going to
            # provide some of them in all the concerned project repositories
            # (below ".git/lfs")
            self._uninstallGitLfsFiltersGlobally()
            repo_sync_env.update({
                "GIT_LFS_SKIP_DOWNLOAD_ERRORS": "1",
            })
            self._downloadSourceTreeQuicksyncArtifacts()
            self._extractRepoSourceTreeArtifact()

        # Ok for the big ol' "repo init ... && repo sync"
        self._doRepoSync(env=repo_sync_env)

        if not use_repo_quicksync_artifacts:
            if alternative_git_lfs_endpoint_url_template_provided:
                # Before overriding the Git LFS endpoint or even pull the Git LFS
                # objects we need to reinstall the Git LFS filters in the
                # repositories as we have disabled them globally before
                self._installGitLfsFiltersInAllRepositories()
                self._overrideWithAlternativeGitLfsEndpoint()
                self._pullGitLfsObjects()
            else:
                pass  # nothing to do in this case

        else:
            self._extractGitLfsArtifact()
            # Make sure the Git LFS filters are enabled now
            self._installGitLfsFiltersInAllRepositories()
            if alternative_git_lfs_endpoint_url_template_provided:
                self._overrideWithAlternativeGitLfsEndpoint()
            self._pullGitLfsObjects()

        self._applyRepoLocalManifest()

    def produceAndUploadSourceTreeQuicksyncArtifacts(self):
        """Produce and upload to the buildmaster the source tree pre-fetched
        artifacts for reuse by other builders."""

        self._produceSourceTreeQuicksyncArtifacts()
        self._uploadSourceTreeQuicksyncArtifacts()

    def _doRepoSync(self, env: Optional[Dict[str, str]] = None):
        """Do repo init and sync via the API provided by Buildbot that neatly
        abstract the use of repo command line (which can be picky to use)."""

        self.addStep(steps.Repo(
            name="repo init and sync",
            description="synchronize the CLIP OS source tree with repo",
            haltOnFailure=True,
            manifestURL=util.Property("repository"),
            manifestBranch=util.Property("branch"),
            jobs=4,
            depth=0,  # Never shallow sync!
            syncAllBranches=True,  # All branches must be present for some features.
            env=env,
        ))

    def _applyRepoLocalManifest(self):
        """Apply a ``local-manifest.xml`` file in the current repo source tree
        context if instructed by the build properties."""

        def assert_local_manifest_application(step: BuildStep) -> bool:
            return bool(step.getProperty("use_local_manifest") and
                        step.getProperty("local_manifest_xml"))

        self.addStep(steps.ShellCommand(
            name="apply local-manifest",
            description=line("""apply local-manifest if specified and provided
                             by the build properties"""),
            haltOnFailure=True,
            doStepIf=assert_local_manifest_application,
            command=["/usr/bin/env", "bash", "-c", textwrap.dedent(
                r"""
                set -e -u -o pipefail

                if [[ "${use_local_manifest:-}" -ne 0 ]]; then
                    mkdir .repo/local_manifests
                    echo "${local_manifest_xml:-}" \
                        > ".repo/local_manifests/local_manifest.xml"

                    repo sync -j4
                fi
                """).strip()],
            env={
                "use_local_manifest": util.Interpolate("%(prop:use_local_manifest:#?|1|0)s"),
                "local_manifest_xml": util.Interpolate("%(prop:local_manifest_xml)s"),
            },
        ))

    def _addCaCertsForHttpsGitRemotes(self):
        """Download in the workers the expected CA certificate files and set
        them accordingly in the current user Git configuration file.

        .. warning::

           As ``git-lfs`` has reimplemented its own procedure to parse the
           ".gitconfig" file, you need to pay attention to the features
           supported by the ``git-lfs`` binary in addition to the ones
           supported by ``git``.

           For instance, as of November 2018, ``git-lfs`` does neither support
           wildcards in the URLs patterns in the ``http`` sections of the Git
           configuration file nor file paths to CA certificates beginning by
           ``~`` (to indicate the home directory) contrary to ``git``.

        """

        if not self.buildmaster_setup.private_settings_addendum.additional_git_https_cacerts:
            raise ValueError(line(
                """Could not declare custom CA certificates for Git HTTPS
                remotes if the Buildbot setup does not provide any."""))

        for url, cacert_filepath in (self.buildmaster_setup.private_settings_addendum
                                                 .additional_git_https_cacerts
                                                 .items()):
            sanitizedurl = re.sub(r'[^a-zA-Z0-9\.\-\_\:]+', "_", url)
            cacert_filename_in_worker = "cacert-{}.pem".format(sanitizedurl)

            self.addStep(steps.FileDownload(
                name="get custom cacert",
                description="download custom CA certificate for HTTPS git remotes",
                haltOnFailure=True,
                mastersrc=cacert_filepath,
                workerdest="~/.git-cacerts/{}".format(cacert_filename_in_worker),
            ))

            self.addStep(steps.ShellCommand(
                name="setup custom cacert for git",
                description="set up the fetched CA certificate for HTTPS git remotes",
                haltOnFailure=True,
                command=textwrap.dedent(
                    r"""
                    git config --global "http.${url}.sslCAInfo" \
                        "${HOME}/.git-cacerts/${cacert_filename_in_worker}"
                    """).strip(),
                env={
                    "url": url,
                    "cacert_filename_in_worker": cacert_filename_in_worker,
                },
            ))

    def _installGitLfsFiltersGlobally(self):
        """Install the Git LFS filters globally"""

        self.addStep(steps.ShellCommand(
            name="install git-lfs filters",
            description="install the Git LFS filters globally",
            haltOnFailure=True,
            command=["git", "lfs", "install", "--skip-repo", "--force"],
        ))

    def _uninstallGitLfsFiltersGlobally(self):
        """Uninstall the Git LFS filters globally"""

        self.addStep(steps.ShellCommand(
            name="uninstall git-lfs filters",
            description="uninstall the Git LFS filters globally to prevent automatic fetch",
            haltOnFailure=True,
            command=textwrap.dedent(
                r"""
                # Uninstall Git LFS filters at global level (i.e. for the user)
                git lfs uninstall

                # Try to uninstall the Git LFS filter system-wide
                sudo git lfs uninstall --system || true
                """).strip(),
        ))

    def _installGitLfsFiltersInAllRepositories(self):
        """Install the Git LFS filters in all the repositories. This method is
        only useful if you have uninstalled the Git LFS globally prior to
        synchronizing the complete source tree. In such case, you need to
        reinstall the Git LFS filters before declaring a Git LFS endpoint or
        pull the Git LFS objects."""

        self.addStep(steps.ShellCommand(
            name="install git-lfs filters in all projects",
            description="install the Git LFS filters retrospectively in all projects",
            haltOnFailure=True,
            command=["repo", "forall", "-c", "git", "lfs", "install"],
        ))

    def _overrideWithAlternativeGitLfsEndpoint(self):
        """Set the altenative Git LFS endpoint URL into the concerned
        repositories (i.e. the repo projects part of the
        `self.REPO_GROUP_FOR_GIT_LFS_BACKED_PROJECTS` repo group).

        .. note::
           Make sure to have used `_installGitLfsFiltersInAllRepositories`
           beforehand.

        """

        if not self.buildmaster_setup.private_settings_addendum.alternative_git_lfs_endpoint_url_template:
            raise ValueError(line(
                """Could not override Git LFS endpoint with the alternative one
                if the Buildbot master setup does not provide any."""))

        url_for_repo_forall = (
            self.buildmaster_setup.private_settings_addendum
                        .alternative_git_lfs_endpoint_url_template
                        .substitute(repository_name="${REPO_PROJECT}"))

        self.addStep(steps.ShellCommand(
            name="setup git-lfs endpoint",

            description=line("""override the Git LFS endpoint with the
                             alternative endpoint URL provided"""),
            haltOnFailure=True,
            command=["repo", "forall",
                     "-g", self.REPO_GROUP_FOR_GIT_LFS_BACKED_PROJECTS,
                     "-c",
                     util.Interpolate(
                         'git config lfs.url "%(kw:url_for_repo_forall)s"',
                         url_for_repo_forall=url_for_repo_forall)],
        ))

    def _pullGitLfsObjects(self):
        """Pull the Git LFS objects in all the Git LFS-backed repositories"""

        self.addStep(steps.ShellCommand(
            name="pull git-lfs objects",
            description="fetch and checkout the Git LFS objects",
            haltOnFailure=True,
            command=["repo", "forall",
                     "-g", self.REPO_GROUP_FOR_GIT_LFS_BACKED_PROJECTS,
                     "-c",
                     "git", "lfs", "pull"],
        ))

    def _produceSourceTreeQuicksyncArtifacts(self):
        """Produce the repo and Git LFS source tree archive artifacts to be
        used by other builders"""

        self.addStep(steps.ShellCommand(
            name="archive repo directory",
            description=line('''archive the ".repo" directory to serve as an
                             artifact for quicker synchronizations'''),
            haltOnFailure=True,
            command=["tar", "-cvf", self.REPO_DIR_ARCHIVE_ARTIFACT_FILENAME,
                     ".repo"],
        ))

        # HACK: We need to resort to this if we want to archive also the Git
        # LFS objects as repo does not encompass them as a symlink under
        # ".repo/projects" as of today (Nov. 2018).
        self.addStep(steps.ShellCommand(
            name="archive git lfs directories",
            description=line("""archive the ".git/lfs" directories to serve as
                             an artifact for quicker synchronizations"""),
            haltOnFailure=True,
            command=["/usr/bin/env", "bash", "-c", textwrap.dedent(
                r"""
                set -e -u -o pipefail

                # Retrieve all the .git/lfs valid paths
                readarray -t potential_git_lfs_paths <<< \
                    "$(repo forall -c 'echo "${REPO_PATH}/.git/lfs"')"
                git_lfs_paths=()
                for path in "${potential_git_lfs_paths[@]}"; do
                    if [[ -d "${path}" ]]; then
                        git_lfs_paths+=("${path}")
                    fi
                done

                # Archive them
                tar -cvf "${ARTIFACT_FILENAME:?}" "${git_lfs_paths[@]}"
                """).strip()],
            env={
                "ARTIFACT_FILENAME": self.GIT_LFS_SUBDIRECTORIES_ARCHIVE_ARTIFACT_FILENAME,
            },
        ))

    def _uploadSourceTreeQuicksyncArtifacts(self):
        """Upload the source tree artifacts to the buildmaster"""

        artifacts_url_for_buildername = None
        if self.buildmaster_setup.artifacts_base_url:
            artifacts_url_for_buildername = _get_artifact_path(
                self.buildmaster_setup.artifacts_base_url, "buildername")
        self.addStep(steps.MultipleFileUpload(
            name="save repo quick-sync artifacts on buildmaster",
            description=line(
                """save the ".repo" directory archive and ".git/lfs"
                directories archive as artifacts on the buildmaster"""),
            haltOnFailure=True,
            workersrcs=[
                self.REPO_DIR_ARCHIVE_ARTIFACT_FILENAME,
                self.GIT_LFS_SUBDIRECTORIES_ARCHIVE_ARTIFACT_FILENAME,
            ],
            masterdest=_get_artifact_path(self.buildmaster_setup.artifacts_dir,
                                          "buildername"),
            mode=0o644,
            url=artifacts_url_for_buildername,
        ))

    def _downloadSourceTreeQuicksyncArtifacts(self):
        """Download the source tree artifacts from the buildmaster and from the
        builder directory output into the builder workspace."""

        self.addStep(steps.SetPropertyFromCommand(
            name="assert which artifact download is required",
            property="which_repo_quicksync_artifact_to_download",
            command=["/usr/bin/env", "bash", "-c", textwrap.dedent(
                r"""
                set -e -u -o pipefail
                to_download=()  # which artifact will be downloaded
                if [[ ! -f "${REPO_DIR_ARCHIVE_ARTIFACT_FILENAME}" ]]; then
                    to_download+=("repo-dir")
                fi
                if [[ ! -f "${GIT_LFS_SUBDIRECTORIES_ARCHIVE_ARTIFACT_FILENAME}" ]]; then
                    to_download+=("git-lfs-dirs")
                fi
                echo "${to_download[@]}"
                """).strip()],
            haltOnFailure=False,
            env={
                "REPO_DIR_ARCHIVE_ARTIFACT_FILENAME": self.REPO_DIR_ARCHIVE_ARTIFACT_FILENAME,
                "GIT_LFS_SUBDIRECTORIES_ARCHIVE_ARTIFACT_FILENAME": self.GIT_LFS_SUBDIRECTORIES_ARCHIVE_ARTIFACT_FILENAME,
            },
        ))

        def is_artifact_download_required(artifact_type):
            def checker(step: BuildStep) -> bool:
                return (
                    (artifact_type in
                     step.getProperty("which_repo_quicksync_artifact_to_download").split()
                    ) or
                    step.getProperty("force_source_tree_artifacts_fetch"))
            return checker

        self.addStep(steps.FileDownload(
            name="retrieve repo directory artifact",
            description='retrieve the ".repo" directory archive from the buildmaster',
            haltOnFailure=True,
            doStepIf=is_artifact_download_required("repo-dir"),
            mastersrc=_get_artifact_path(self.buildmaster_setup.artifacts_dir,
                                         'buildername_providing_repo_quicksync_artifacts',
                                         self.REPO_DIR_ARCHIVE_ARTIFACT_FILENAME),
            workerdest=self.REPO_DIR_ARCHIVE_ARTIFACT_FILENAME,
        ))

        self.addStep(steps.FileDownload(
            name="retrieve git-lfs directories artifact",
            description='retrieve the ".git/lfs" directories archive from the buildmaster',
            haltOnFailure=True,
            doStepIf=is_artifact_download_required("git-lfs-dirs"),
            mastersrc=_get_artifact_path(self.buildmaster_setup.artifacts_dir,
                                         'buildername_providing_repo_quicksync_artifacts',
                                         self.GIT_LFS_SUBDIRECTORIES_ARCHIVE_ARTIFACT_FILENAME),
            workerdest=self.GIT_LFS_SUBDIRECTORIES_ARCHIVE_ARTIFACT_FILENAME,
        ))

    def _extractRepoSourceTreeArtifact(self):
        """Extract the ".repo" archive artifact in the current working tree of
        the builder."""

        self.addStep(steps.ShellCommand(
            name="extract repo directory",
            description=line("""extract the ".repo" directory archive artifact
                             in the current working tree"""),
            haltOnFailure=True,
            command=["tar", "-xvf", self.REPO_DIR_ARCHIVE_ARTIFACT_FILENAME],
        ))

    def _extractGitLfsArtifact(self):
        """Extract the ".git/lfs" directories archive artifact in the current
        working tree of the builder."""

        self.addStep(steps.ShellCommand(
            name="extract git-lfs directories",
            description=line("""extract the ".git/lfs" directories archive
                             artifact in the current working tree"""),
            haltOnFailure=True,
            command=["tar", "-xvf",
                     self.GIT_LFS_SUBDIRECTORIES_ARCHIVE_ARTIFACT_FILENAME],
        ))


class RepoSyncFromScratchAndArchive(ClipOsSourceTreeBuildFactoryBase):
    """Fetch and synchronize the CLIP OS source tree with repo and creates a
    tarball from the contents of the ``.repo`` directory containing all the Git
    objects of all the Git repositories composing the CLIP OS source tree."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.cleanupWorkspaceIfRequested(keep_artifacts=False)

        self.syncSources(use_repo_quicksync_artifacts=False)  # i.e. from scratch

        self.produceAndUploadSourceTreeQuicksyncArtifacts()


class ClipOsToolkitEnvironmentBuildFactoryBase(ClipOsSourceTreeBuildFactoryBase):
    """Build factory base for build factory that need to make use of the CLIP
    OS toolkit (e.g. when building CLIP OS images)."""

    SDKS_ARTIFACT_FILENAME = "sdks.tar"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def cleanCosmkDirectories(self, *,
                              build_dir: bool = True,
                              cache_dir: bool = True,
                              runtime_dir: bool = True):
        dirs = []
        if build_dir:
            dirs.append("out")
        if cache_dir:
            dirs.append("cache")
        if runtime_dir:
            dirs.append("run")
        if not dirs:
            return
        self.addStep(steps.ShellCommand(
            name="remove selected cosmk-managed dirs",
            haltOnFailure=True,
            command=r"sudo rm -rf {}".format(" ".join(map(shlex.quote, dirs))),
        ))

    def downloadExtractSdksOrBootstrapUploadSdks(self):
        """Try to retrieve the SDKs artifact from the builder artifacts (whose
        name is specified in the property
        ``buildername_providing_sdks_artifact``) or bootstrap the SDKs."""

        self.downloadAndExtractSdksArtifact(consider_sdks_artifact_provider_property=True)
        self.bootstrapSdks(consider_sdks_artifact_provider_property=True)
        self.produceAndUploadSdksArtifact(consider_sdks_artifact_provider_property=True)

    def downloadAndExtractSdksArtifact(self,
                                       consider_sdks_artifact_provider_property: bool = False):
        """The argument `consider_sdks_artifact_provider_property` should only
        be used by downloadExtractSdksOrBootstrapUploadSdks function."""

        if not consider_sdks_artifact_provider_property:
            stepsCondition = True
        else:
            stepsCondition = lambda s: s.getProperty("buildername_providing_sdks_artifact")

        self.addStep(steps.FileDownload(
            name="retrieve sdk artifacts",
            description=line(
                """retrieve the SDKs artifact from the appropriate buildername
                artifacts output on buildmaster"""),
            haltOnFailure=True,
            doStepIf=stepsCondition,
            mastersrc=_get_artifact_path(self.buildmaster_setup.artifacts_dir,
                                         "buildername_providing_sdks_artifact",
                                         self.SDKS_ARTIFACT_FILENAME),
            workerdest=self.SDKS_ARTIFACT_FILENAME,
        ))
        self.addStep(steps.ShellCommand(
            name="extract sdk artifact archive",
            description=line("""extract the SDK artifact archive in the current
                             working tree"""),
            haltOnFailure=True,
            doStepIf=stepsCondition,
            command=["tar", "-xvf", self.SDKS_ARTIFACT_FILENAME],
        ))

    def bootstrapSdks(self,
                      consider_sdks_artifact_provider_property: bool = False):
        """The argument `consider_sdks_artifact_provider_property` should only
        be used by downloadExtractSdksOrBootstrapUploadSdks function."""

        if not consider_sdks_artifact_provider_property:
            stepsCondition = True
        else:
            stepsCondition = lambda s: not s.getProperty("buildername_providing_sdks_artifact")

        all_steps_cmds = [
            ("cosmk", "bootstrap", "clipos/sdk"),
            ("cosmk", "bootstrap", "clipos/sdk_debian"),
        ]
        for step_cmd in all_steps_cmds:
            self.addStep(clipos.steps.ToolkitEnvironmentShellCommand(
                # Cut out the step name as it must be lower than 50 chars:
                name=str(" ".join(step_cmd))[:50],
                haltOnFailure=True,
                doStepIf=stepsCondition,
                command=step_cmd,
            ))

    def produceAndUploadSdksArtifact(self,
                                     consider_sdks_artifact_provider_property: bool = False):
        """The argument `consider_sdks_artifact_provider_property` should only
        be used by downloadExtractSdksOrBootstrapUploadSdks function."""

        if not consider_sdks_artifact_provider_property:
            stepsCondition = True
        else:
            stepsCondition = lambda s: not s.getProperty("buildername_providing_sdks_artifact")

        self.addStep(steps.ShellCommand(
            name="archive sdk artifact archive",
            description=line("""extract the SDK artifact archive in the current
                             working tree"""),
            haltOnFailure=True,
            doStepIf=stepsCondition,
            command=["/usr/bin/env", "bash", "-c", textwrap.dedent(
                r"""
                set -e -u -o pipefail

                # Create the archive
                > "${artifact_filename}"
                find cache -type d -regex 'cache/clipos/[^/]+/sdk[^/]*' \
                    -exec tar -rvf "${artifact_filename}" {} \;
                """).strip()],
            env={
                "artifact_filename": self.SDKS_ARTIFACT_FILENAME,
            },
        ))

        artifacts_url_for_buildername = None
        if self.buildmaster_setup.artifacts_base_url:
            artifacts_url_for_buildername = _get_artifact_path(
                self.buildmaster_setup.artifacts_base_url, "buildername")
        self.addStep(steps.MultipleFileUpload(
            name="save sdk artifact on buildmaster",
            description="save the SDK artifact archive on the buildmaster",
            haltOnFailure=True,
            doStepIf=stepsCondition,
            workersrcs=[
                self.SDKS_ARTIFACT_FILENAME,
            ],
            masterdest=_get_artifact_path(self.buildmaster_setup.artifacts_dir,
                                          "buildername"),
            mode=0o644,
            url=artifacts_url_for_buildername,
        ))

    def buildAll(self):
        all_steps_cmds = [
            ("cosmk", "build", "clipos/core"),
            ("cosmk", "image", "clipos/core"),
            ("cosmk", "configure", "clipos/core"),
            ("cosmk", "bundle", "clipos/core"),

            ("cosmk", "build", "clipos/efiboot"),
            ("cosmk", "image", "clipos/efiboot"),
            ("cosmk", "configure", "clipos/efiboot"),
            ("cosmk", "bundle", "clipos/efiboot"),

            ("cosmk", "bundle", "clipos/qemu"),
        ]

        for step_cmd in all_steps_cmds:
            self.addStep(clipos.steps.ToolkitEnvironmentShellCommand(
                # Cut out the step name as it must be lower than 50 chars:
                name=str(" ".join(step_cmd))[:50],
                haltOnFailure=True,
                command=step_cmd,
            ))


class ClipOsProductBuildBuildFactory(ClipOsToolkitEnvironmentBuildFactoryBase):
    """Build factory to build CLIP OS product"""

    def __init__(self, reuse_sdks_artifacts: bool = False,
                 **kwargs):
        super().__init__(**kwargs)

        self.cleanupWorkspaceIfRequested(keep_artifacts=True)

        self.syncSources(use_repo_quicksync_artifacts=True)

        self.cleanCosmkDirectories()

        self.downloadExtractSdksOrBootstrapUploadSdks()

        self.buildAll()


# vim: set ft=python ts=4 sts=4 sw=4 et tw=79:
