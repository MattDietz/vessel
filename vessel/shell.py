import json
import os
import shlex
import subprocess
import sys

import click
import jinja2
import toml

VESSEL_ROOT = os.path.expanduser("~/.vessel")
VESSEL_CONFIG = "{}/config.toml".format(VESSEL_ROOT)
DEFAULT_SSH_KEY = os.path.expanduser("~/.ssh")
CONFIG_FILE = "config.toml"
COMPOSE_FILE = "docker-compose.yaml"

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
    "supress_warnings": False,
    "default_backend": "docker-compose",
    "set_project_path_to_cwd": True,
    "ssh_key_path": DEFAULT_SSH_KEY if os.path.exists(DEFAULT_SSH_KEY) else ""
}


# TODO Templatize this with assloads of comments
DEFAULT_PROJECT_CONFIG = {
    "name": "",
    "image": "",
    "custom_build": False,
    "volumes": {},
    "ports": {},
    "language": "",
    "network_mode": "",
    "entrypoint": "",
    "command": "",
    "mount_ssh_keys": False,
    "default_backend": "",
    "dependencies": [],
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


class Service(object):
    REQUIRED = ["name", "image"]

    def __init__(self, **kwargs):
        for key in self.REQUIRED:
            if key not in kwargs:
                raise Exception("Missing required config key '{}'".format(key))
        self.command = kwargs.get("command")
        self.custom_build = kwargs.get("custom_build")
        self.default_backend = kwargs.get("default_backend")
        self.dependencies = kwargs.get("dependencies")
        self.entrypoint = kwargs.get("entrypoint")
        self.env_vars = kwargs.get("env_vars")
        self.image = kwargs.get("image")
        self.mount_ssh_keys = kwargs.get("mount_ssh_keys")
        self.name = kwargs.get("name")
        self.network_mode = kwargs.get("network_mode")
        self.ports = kwargs.get("ports")
        self.volumes = kwargs.get("volumes")

        if "environment" in kwargs:
            self.host_env_vars = kwargs["environment"]["host"]
            self.build_env_vars = kwargs["environment"]["build"]
            self.container_env_vars = kwargs["environment"]["container"]

    @classmethod
    def escape_host_envvars(cls, envvar):
        prev = None
        found_var = False
        escaped = False
        var_start = -1
        strbuffer = []
        if not isinstance(envvar, str):
            return envvar

        for i, c in enumerate(envvar):
            if found_var:
                c_val = ord(c)
                if (c_val >= 48 and c_val <= 57) or \
                        (c_val >= 65 and c_val <= 90) or \
                        (c_val >= 97 and c_val <= 122) or \
                        (c_val == 95):
                    pass
                else:
                    # Found the end of the var
                    var = envvar[var_start+1:i]
                    strbuffer.extend("{{{}}}".format(var))
                    var_start = -1
                    found_var = False

            if not found_var:
                strbuffer.append(c)

            if c == '$':
                if escaped:
                    escaped = False
                    found_var = False
                else:
                    found_var = True
                    var_start = i
            elif c == "\\":
                if escaped:
                    escaped = False
                else:
                    escaped = True

        # We got to the end of the string
        if found_var:
            var = envvar[var_start+1:]
            strbuffer.extend("{{{}}}".format(var))

        return "".join(strbuffer)


def _project_path(project):
    return "{}/{}".format(VESSEL_ROOT, project)


def _project_config_path(project):
    return "{}/{}".format(_project_path(project), CONFIG_FILE)


def _project_exists(project):
    return os.path.exists(_project_path(project))


def _project_compose_path(project):
    return "{}/{}".format(_project_path(project), COMPOSE_FILE)


def _enforce_host_vars(cfg):
    # TODO Maybe have special known vars. PROJECT_PATH if unset could
    #      be set to CWD
    for k, v in cfg.get("environment", {}).get("host", {}).items():
        if k not in os.environ:
            if v != "":
                os.environ.setdefault(k, v)
            else:
                click.echo("'{}' must be set in your environment before "
                           "the project can be run".format(k))
                sys.exit(1)


def _set_workdir_var():
    os.environ.setdefault("WORKDIR", os.getcwd())


def _check_initialized():
    if not os.path.exists(VESSEL_ROOT) or not os.path.exists(VESSEL_CONFIG):
        click.echo("Vessel is not initialized, please run `vessel init` first")
        sys.exit(1)


def _enforce_editor():
    if ("VISUAL" not in os.environ and "EDITOR" not in os.environ):
        click.echo("$VISUAL or $EDITOR must be set to use this command")
        sys.exit(1)
    if "EDITOR" in os.environ:
        return os.environ["EDITOR"]
    elif "VISUAL" in os.environ:
        return os.environ["VISUAL"]


def _generate_compose(projects):
    try:
        svc_cfg = [Service(**p) for p in projects]
    except Exception as e:
        sys.exit(e)
    template = jinja_env.get_template("docker-compose.tpl")
    return template.render(services=svc_cfg)


def _pretty_json(blob):
    return json.dumps(blob, sort_keys=True, separators=(", ", ": "), indent=4)


def _pretty_toml(blob, outer=""):
    for k, v in blob.items():
        if isinstance(v, dict):
            k_formatted = k
            if outer:
                k_formatted = "{}.{}".format(outer, k)
                click.echo("[{}]".format(k_formatted))
            _pretty_toml(v, outer=k_formatted)
        else:
            v_formatted = v
            if isinstance(v, str):
                v_formatted = '"{}"'.format(v)
            click.echo("{} = {}".format(k, v_formatted))


def _load_config(project=None):
    if project:
        with open(_project_config_path(project), 'r') as f:
            return toml.load(f)
    with open(VESSEL_CONFIG, 'r') as f:
        return toml.load(f)


def _discover_projects(root_project):
    services = {}
    cfg = _load_config(root_project)
    services[cfg["name"]] = cfg
    for project in cfg.get("dependencies", []):
        sub_services = _discover_projects(project)
        services.update(sub_services)
    return services


class CLIRoot(object):
    def __init__(self, debug=False):
        self._debug = debug
        self._config = _load_config()

    @property
    def debug(self):
        return self._debug

    @property
    def config(self):
        return self._config


@click.group()
@click.option("--debug/--no-debug", default=False)
@click.pass_context
def vessel(ctx, debug):
    ctx.obj = CLIRoot(debug)
    if ("VISUAL" not in os.environ and
        "EDITOR" not in os.environ and
        not ctx.obj.config.get("suppress_warnings", False)):
        click.echo("WARNING: You need to set your $VISUAL or $EDITOR "
                   "environment variables to use config editing commands")


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
        "name": project,
        "language": language,
        "default_backend": DEFAULT_CONFIG["default_backend"]
    })

    proj_config["volumes"] = {
        "{}/data".format(proj_path): "",
        "$WORKDIR": "/CONTAINER_MOUNT_PATH/{}".format(project)
    }

    if language and language.strip().lower() == "python":
        proj_config["volumes"] = {
            "$HOME/.vessel/{}/venv".format(project): "/root/.virtualenvs"
        }
        proj_config["environment"]["host"]["PROJECT_PATH"] = "PathToPackage"

    with open("{}/config.toml".format(proj_path), 'w') as f:
        f.write(toml.dumps(proj_config))


@vessel.command()
@click.pass_context
def list(ctx):
    _check_initialized()
    for root, dirs, files in os.walk(VESSEL_ROOT):
        if root == VESSEL_ROOT:
            continue
        if CONFIG_FILE in files:
            click.echo(os.path.split(root)[-1])


@vessel.command()
@click.argument("project")
@click.pass_context
def show(ctx, project):
    # TODO Probably emove this later. Just for dev.
    _check_initialized()
    if not _project_exists(project):
        click.echo("No project named '{}' exists. "
                   "You should create one!".format(project))
        sys.exit(1)
    click.echo(_pretty_toml(_load_config(project)))


@vessel.command()
@click.argument("project")
@click.pass_context
def edit(ctx, project):
    _check_initialized()
    edit_cmd = _enforce_editor()
    if not _project_exists(project):
        click.echo("No project named '{}' exists. "
                   "You should create one!".format(project))
        sys.exit(1)
    cmd = shlex.split("{} {}".format(edit_cmd, _project_config_path(project)))
    subprocess.Popen(cmd).wait()


@vessel.command()
@click.pass_context
def config(ctx):
    _check_initialized()
    edit_cmd = _enforce_editor()
    cmd = shlex.split("{} {}".format(edit_cmd, VESSEL_CONFIG))
    subprocess.Popen(cmd).wait()


@vessel.command()
@click.argument("project")
@click.pass_context
def up(ctx, project):
    _check_initialized()
    if not _project_exists(project):
        click.echo("No project named '{}' exists. "
                   "You should create one!".format(project))
        sys.exit(1)
    _set_workdir_var()

    # Dis gon git recursive
    cfg = _load_config(project)
    _enforce_host_vars(cfg)
    compose_path = _project_compose_path(project)
    projects = _discover_projects(project).values()
    with open(compose_path, 'w') as f:
        f.write(_generate_compose(projects))

    cmd = shlex.split("docker-compose -f {} up -d".format(compose_path))
    subprocess.Popen(cmd)


@vessel.command()
@click.argument("project")
@click.argument("command")
@click.pass_context
def run(ctx, project, command=None):
    _check_initialized()
    if not _project_exists(project):
        click.echo("No project named '{}' exists. "
                   "You should create one!".format(project))
        sys.exit(1)
    _set_workdir_var()

    # Dis gon git recursive
    cfg = _load_config(project)
    _enforce_host_vars(cfg)
    compose_path = _project_compose_path(project)
    projects = _discover_projects(project).values()
    with open(compose_path, 'w') as f:
        f.write(_generate_compose(projects))

    cmd = shlex.split("docker-compose -f {} run {}".format(compose_path,
                                                           command))
    subprocess.Popen(cmd)


@vessel.command()
@click.argument("project")
@click.pass_context
def export(ctx, project):
    _check_initialized()
    if not _project_exists(project):
        click.echo("No project named '{}' exists. "
                   "You should create one!".format(project))
        sys.exit(1)
    _set_workdir_var()

    # Dis gon git recursive
    cfg = _load_config(project)
    _enforce_host_vars(cfg)
    compose_path = _project_compose_path(project)
    projects = _discover_projects(project).values()
    compose = _generate_compose(projects)
    with open(compose_path, 'w') as f:
        f.write(compose)
    click.echo(compose)
    

@vessel.command()
@click.argument("project")
@click.pass_context
def logs(ctx, project):
    _check_initialized()
    if not _project_exists(project):
        click.echo("No project named '{}' exists. "
                   "You should create one!".format(project))
        sys.exit(1)

    # Dis gon git recursive
    compose_path = _project_compose_path(project)
    cmd = shlex.split("docker-compose -f {} logs".format(compose_path))
    subprocess.Popen(cmd)


@vessel.command()
@click.argument("project")
@click.pass_context
def kill(ctx, project):
    _check_initialized()
    if not _project_exists(project):
        click.echo("No project named '{}' exists. "
                   "You should create one!".format(project))
        sys.exit(1)

    # Dis gon git recursive
    compose_path = _project_compose_path(project)
    cmd = shlex.split("docker-compose -f {} kill".format(compose_path))
    subprocess.Popen(cmd)
