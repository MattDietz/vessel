import os
import sys

import click
import jinja2
import toml

VESSEL_ROOT = os.path.expanduser("~/.vessel")
VESSEL_CONFIG = "{}/config.toml".format(VESSEL_ROOT)
DEFAULT_SSH_KEY = os.path.expanduser("~/.ssh")

# This implicitly supports any other language. We just check for
# $LANG_base_*
DEFAULT_CONFIG = {
    "python": {
        "base_image": "",
        "base_dockerfile": ""
    },
    "golang": {
        "base_image": "",
        "base_dockerfile": ""
    },
    "default_backend": "docker-compose",
    "ssh_key_path": DEFAULT_SSH_KEY if os.path.exists(DEFAULT_SSH_KEY) else ""
}

DEFAULT_PROJECT_CONFIG = {
    "image": "",
    "custom_build": False,
    "volumes": [],
    "ports": [],
    "language": "",
    "entrypoint": "",
    "mount_ssh_keys": False,
    "default_backend": "",
    "environment": {
        "build": {},
        "host": {},
        "container": {}
    },
}

jinja_env = jinja2.Environment(
    loader=jinja2.PackageLoader('vessel', 'templates'),
    autoescape=jinja2.select_autoescape(['tpl'])
)


def _project_path(project):
    return "{}/{}".format(VESSEL_ROOT, project)


def _check_initialized():
    if not os.path.exists(VESSEL_ROOT) or not os.path.exists(VESSEL_CONFIG):
        click.echo("Vessel is not initialized, please run `vessel init` first")
        sys.exit(1)


class CLIRoot(object):
    def __init__(self, debug=False):
        self._debug = debug

    @property
    def debug(self):
        return self._debug


@click.group()
@click.option("--debug/--no-debug", default=False)
@click.pass_context
def vessel(ctx, debug):
    ctx.obj = CLIRoot(debug)


# Commands I have been known to run:
# docker run --rm -it -v $HOME/.mgdev/argus:/root/.virtualenvs -v $1:/workspace -v $HOME/.ssh:/root/.ssh argus-dev:$TAG bash

@vessel.command()
@click.pass_context
def init(ctx):
    if not os.path.exists(VESSEL_ROOT):
        if ctx.obj.debug:
            click.echo("Creating the directory structure "
                       "under {}".format(VESSEL_ROOT))
        os.mkdir(VESSEL_ROOT)
    else:
        if ctx.obj.debug:
            click.echo("Vessel path already exists: {}".format(VESSEL_ROOT))

    if not os.path.exists(VESSEL_CONFIG):
        if ctx.obj.debug:
            click.echo("Creating config under {}".format(VESSEL_CONFIG))
        with open(VESSEL_CONFIG, 'w') as f:
            f.write(toml.dumps(DEFAULT_CONFIG))
    else:
        if ctx.obj.debug:
            click.echo("Vessel config already "
                       "exists: {}".format(VESSEL_CONFIG))


@vessel.command()
@click.argument("project")
@click.option("-l", "--language", default=None)
@click.pass_context
def create(ctx, project, language):
    _check_initialized()
    proj_path = _project_path(project)
    if os.path.exists(proj_path):
        click.echo("{} already exists".format(proj_path))
        sys.exit(1)
    os.mkdir(proj_path)

    # TODO This needs to copy the language specific template from the config
    tpl = jinja_env.get_template("basedockerfile.tpl")
    with open("{}/Dockerfile".format(proj_path), 'w') as f:
        f.write(tpl.render())

    proj_config = DEFAULT_PROJECT_CONFIG.copy()

    # TODO Load vrssel config before the command runs
    proj_config.update({
        "language": language,
        "default_backend": DEFAULT_CONFIG["default_backend"]
    })
    with open("{}/config.toml".format(proj_path), 'w') as f:
        f.write(toml.dumps(proj_config))

    # TODO This could move into a language specific driver later
    if isinstance(language, str) and language.lower() == "python":
        os.mkdir("{}/venv".format(proj_path))


@vessel.command()
@click.argument("project")
@click.pass_context
def config(ctx, project):
    pass


@vessel.command()
@click.pass_context
def export(ctx, project):
    pass


@vessel.command()
@click.argument("project")
@click.pass_context
def run(ctx, project):
    generate_compose()


class Service(object):
    def __init__(self):
        self.name = ""
        self.env_vars = {}
        self.dependencies = []
        self.image = ""
        self.network_mode = ""
        self.volumes = {}


def generate_compose():
    services = []
    service = Service()
    service.name = "argus"
    service.image = "debian"
    service.env_vars["ARGUS_WORKSPACE"] = "./argus"
    service.volumes["${HOME}/.vessel/argus/venv"] = "/root/.virtualenvs"
    services.append(service)
    template = jinja_env.get_template("docker-compose.tpl")
    click.echo(template.render(services=services))
