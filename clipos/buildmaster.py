# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright © 2019 ANSSI. All rights reserved.

"""Buildbot master setup settings abstraction for the CLIP OS Project (or any
of its derivatives) buildbot instances"""

import json
import os
import string
from typing import Optional, List, Dict, Any

import yaml
from buildbot.plugins import util
from buildbot.www.auth import NoAuth  # when served locally for debug purposes

from .commons import line  # utility functions and stuff


class SetupSettings(object):
    """Buildbot master setup settings abstraction

    :param setup_settings_jsonfile: the path to the JSON file
        automatically created by the Docker entrypoint script (if this
        buildmaster is ran from a Docker container environment)

    """

    def __init__(self,
                 setup_settings_jsonfile: Optional[str] = None,
                ) -> None:
        # Load the private setup settings file into a private dict:
        self.__settings = None
        if setup_settings_jsonfile:
            try:
                with open(setup_settings_jsonfile, 'r') as fp:
                    self.__settings = json.load(fp)
            except FileNotFoundError:
                # XXX: is it sane to fail silently for this?
                self.__settings = None

        # Load the private settings addendum (if provided):
        self.private_settings_addendum = None
        if (self._private_settings_addendum_dir and
                self._private_settings_addendum_yamlfile):
            self.private_settings_addendum = PrivateSettingsAddendum(
                directory=self._private_settings_addendum_dir,
                yamlfile=self._private_settings_addendum_yamlfile
            )

        # Load the secrets (if provided):
        self.secrets = None
        if self._secrets_dir and self._secrets_yamlfile:
            self.secrets = Secrets(
                directory=self._secrets_dir,
                yamlfile=self._secrets_yamlfile
            )

    def buildmaster_config_base(self) -> Dict[str, Any]:
        """Generate a base for the Buildmaster configuration settings as `dict`
        (i.e. the ``BuildmasterConfig`` `dict` that is read by the Buildbot
        twistd application) with all the settings properly defined."""

        # The buildbot instance name title
        title = "CLIP OS" if self.__settings else "DEBUGGING ONLY"
        title_url = "https://clip-os.org/"

        # Authentication settings
        if not self.__settings:
            auth = NoAuth()
            authz = util.Authz()
        else:
            if not self.secrets:
                admin_usernames = []
                auth_backend = 'user-password-dict'
                auth_backend_parameters = {}
            else:
                admin_usernames = self.secrets.admin_usernames
                auth_backend = self.secrets.auth_backend
                auth_backend_parameters = self.secrets.auth_backend_parameters

            if auth_backend == 'user-password-dict':
                auth = util.UserPasswordAuth(auth_backend_parameters)
            elif auth_backend == 'github':
                auth = util.GitHubAuth(
                    clientId=auth_backend_parameters['clientId'],
                    clientSecret=auth_backend_parameters['clientSecret'],
                    getTeamsMembership=False,  # useless for us
                )
            else:
                raise NotImplementedError(
                    "Unknown auth backend {!r} from secrets".format(
                        auth_backend))

            authz = util.Authz(
                allowRules = [
                    # Admins can do anything.
                    util.AnyEndpointMatcher(role="admins", defaultDeny=False),
                    # Future-proof control endpoints.
                    util.AnyControlEndpointMatcher(role="admins"),
                ],
                roleMatchers = [
                    # Defined administration from their usernames
                    util.RolesFromUsername(
                        roles=['admins'],
                        usernames=admin_usernames,
                    )
                ],
            )

        return {
            # Presentation settings
            'title': title,
            'titleURL': title_url,

            # Database settings
            'db': {
                'db_url': self.db_url,
            },

            # Web UI settings
            'buildbotURL': self.buildbot_url,
            'www': {
                # The port to listen to (a HTTP reverse-proxy should be
                # configured behind this port):
                'port': self.www_port,
                # Do not use an alternative logfile for HTTP logging, use
                # twistd logging output (the fallback) rather than a separate
                # file because the twistd logging output is known to be
                # properly collected.
                'logfileName': None,
                # Do not use Gravatars:
                'avatar_methods': [],

                # Web UI plugins potential settings:
                'plugins': {
                    'waterfall_view': {},
                    'console_view': {},
                    'grid_view': {},
                },

                # Authentication settings for the web UI and REST API:
                'auth': auth,
                'authz': authz,
            },

            # Buildmaster/workers network related settings
            'protocols': {
                # Settings for Twisted's Perspective Broker protocol
                'pb': {
                    # The port to use to communicate with the Buildbot workers
                    'port': self.pb_port,
                },
            },

            # Disable Buildbot usage tracking for the moment:
            # See: http://docs.buildbot.net/latest/manual/cfg-global.html#buildbotnetusagedata
            'buildbotNetUsageData': None,
        }

    @property
    def pb_port(self) -> int:
        """The TCP port on which the Buildbot master instance will listen using
        Twistd PB (Perspective Broker) protocol."""

        if self.__settings:
            return int(self.__settings["BUILDBOT_MASTER_PB_PORT"])
        else:
            return 9989

    @property
    def config_git_clone_url(self) -> str:
        """The Buildbot configuration Git repository"""

        if self.__settings:
            return self.__settings["BUILDBOT_CONFIG_GIT_CLONE_URL"]
        else:
            return "file://{}".format(os.path.dirname(os.path.realpath(__file__)))

    @property
    def config_git_revision(self) -> str:
        """The revision/Git branch to use for the Buildbot configuration Git
        repository to watch for changes."""

        if self.__settings:
            return self.__settings["BUILDBOT_CONFIG_GIT_REVISION"]
        else:
            return "master"

    @property
    def buildbot_url(self) -> str:
        """The public URL on which Buildbot will be exposed for the Web UI."""

        if self.__settings:
            return self.__settings["BUILDBOT_URL"]
        else:
            return "http://localhost:8010/"

    @property
    def www_port(self) -> int:
        """The public URL on which Buildbot will be exposed for the Web UI."""

        if self.__settings:
            return int(self.__settings["BUILDBOT_WWW_PORT"])
        else:
            return 8010

    @property
    def db_url(self) -> str:
        """The database URL for Buildbot master instance."""

        if self.__settings:
            postgres_user = self.__settings["BUILDBOT_POSTGRES_USER"]
            postgres_password = self.__settings["BUILDBOT_POSTGRES_PASSWORD"]
            postgres_host = self.__settings["BUILDBOT_POSTGRES_HOST"]
            postgres_db = self.__settings["BUILDBOT_POSTGRES_DB"]
            return 'postgresql+psycopg2://{user}:{password}@{host}/{db}'.format(
                user=postgres_user,
                password=postgres_password,
                host=postgres_host,
                db=postgres_db,
            )
        else:
            return "sqlite:///state.sqlite"

    @property
    def artifacts_dir(self) -> str:
        """The directory where to store the build artifacts in the Buildbot
        master instance context."""

        if self.__settings:
            return self.__settings["BUILDBOT_ARTIFACTS_DIR"]
        else:
            return "artifacts"

    @property
    def docker_host_uri(self) -> str:
        """The URL to the host Docker daemon socket"""

        if self.__settings:
            return self.__settings.get("BUILDBOT_DOCKER_HOST_URI",
                                       "unix:///var/run/docker.sock")
        else:
            # It is assumed that in the current case the buildmaster runs on
            # the Docker host. There is no need to specify any special Docker
            # network. Classical UNIX socket for the Docker daemon is assumed.
            return "unix:///var/run/docker.sock"

    @property
    def docker_worker_containers_network_mode(self) -> str:
        """The networking mode to use for the Docker containers that will be
        created by this master Buildbot instance as DockerLatentWorker."""

        if self.__settings:
            return self.__settings.get(
                "BUILDBOT_WORKER_DOCKER_CONTAINERS_NETWORK_MODE", '')
        else:
            return ""   # TODO: should we use "host" in that case?

    @property
    def clipos_manifest_git_url(self) -> str:
        """The URL to the CLIP OS project manifest Git repository URL. This is
        provided by the private assets and defaults to the public one on GitHub
        if not defined it there."""

        if (self.private_settings_addendum and
                self.private_settings_addendum.clipos_manifest_git_url):
            return self.private_settings_addendum.clipos_manifest_git_url
        else:
            # defaults to the public repository
            return "https://review.clip-os.org/clipos/manifest"

    @property
    def _private_settings_addendum_dir(self) -> Optional[str]:
        """The path to the private settings addendum directory (if this path is
        specified as relative, it will be computed from the Buildbot master
        configuration root path)"""

        if self.__settings:
            return self.__settings.get("BUILDBOT_PRIVATE_SETTINGS_ADDENDUM_DIR")

    @property
    def _private_settings_addendum_yamlfile(self) -> Optional[str]:
        """The path to the private settings addendum YAML file describing
        additional settings (if this path is specified as relative, it will be
        computed from the Buildbot master configuration root path)"""

        if self.__settings:
            return self.__settings.get("BUILDBOT_PRIVATE_SETTINGS_ADDENDUM_YAMLFILE")

    @property
    def _secrets_dir(self) -> Optional[str]:
        """The path to the secrets directory (if this path is specified as
        relative, it will be computed from the Buildbot master configuration
        root path)"""

        if self.__settings:
            return self.__settings.get("BUILDBOT_SECRETS_DIR")

    @property
    def _secrets_yamlfile(self) -> Optional[str]:
        """The path to the secrets YAML file (if this path is specified as
        relative, it will be computed from the Buildbot master configuration
        root path)"""

        if self.__settings:
            return self.__settings.get("BUILDBOT_SECRETS_YAMLFILE")


class PrivateSettingsAddendum(object):
    """Class for the private settings addendum to the Buildbot master instance
    setup settings.

    :param directory: the path to the directory where are stored the private
        settings assets file (i.e. the YAML file that describes the private
        additional setup settings) to this Buildbot master instance
    :param yamlfile: the path to the YAML file that describes the private
        additional setup settings to this Buildbot master instance

    """

    def __init__(self, directory: str, yamlfile: str) -> None:
        self.directory = directory
        with open(os.path.join(self.directory, yamlfile), 'r') as fp:
            self.__settings = yaml.safe_load(fp)

    @property
    def clipos_manifest_git_url(self) -> Optional[str]:
        """The URL to the CLIP OS project manifest Git repository URL. This is
        provided by the private assets and defaults to the public one on GitHub
        if not defined it there."""

        return self.__settings.get("clipos_manifest_git_url")

    @property
    def alternative_git_lfs_endpoint_url_template(self) -> Optional[string.Template]:
        """The potentially-provided alternative Git LFS endpoint URL template
        string to use in place of the Git LFS endpoint advertised by the
        repository (via a ``.lfsconfig`` typically) or inferred by ``git-lfs``
        from the remote URL.

        This is provided by the private assets and defaults to `None`.

        """

        template_string = self.__settings.get(
            "alternative_git_lfs_endpoint_url_template_string")
        if template_string:
            # Normalize this into a string.Template
            return string.Template(template_string)

    @property
    def additional_git_https_cacerts(self) -> Dict[str, str]:
        """Potential additional CA Certificates for HTTPS Git remotes. This is
        provided by the private assets."""

        cacerts_dict: Dict[str, str] = self.__settings.get(
            "git_https_cacerts", dict())
        # Extend the paths with the base path to the private setup setting
        # addendum dir:
        cacerts_dict = {
            url: os.path.join(self.directory, str(filepath.lstrip('/')))
            for url, filepath in cacerts_dict.items()
        }
        return cacerts_dict

class Secrets(object):
    """Class for the secrets handled by the Buildbot master instance

    :param directory: the path to the directory where are stored the private
        settings assets file (i.e. the YAML file that describes the private
        additional setup settings) to this Buildbot master instance
    :param yamlfile: the path to the YAML file that describes the private
        additional setup settings to this Buildbot master instance

    """

    def __init__(self, directory: str, yamlfile: str) -> None:
        self.directory = directory
        with open(os.path.join(self.directory, yamlfile), 'r') as fp:
            self.__settings = yaml.safe_load(fp)

    @property
    def auth_backend(self) -> str:
        """The backend to use for authentication."""

        return self.__settings['auth']['backend']

    @property
    def auth_backend_parameters(self) -> Any:
        """The parameters for the chosen authentication backend."""

        return self.__settings['auth']['parameters'][self.auth_backend]

    @property
    def admin_usernames(self) -> Any:
        """The administrator usernames list"""

        return self.__settings['admins']


# vim: set ft=python ts=4 sts=4 sw=4 et tw=79:
