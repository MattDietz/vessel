# TODO
# Vessel could manage multiple docker-compose envs that connect to the same network
# A useful example would be:
# Run all A deps
# Now I want to add in B + deps (because A will consume it)
# Finally, bring up a go container mounting the A path inside so I can run import
# The utility is in having to remember less shit to type and variables to include
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
    "default_volumes": {
        DEFAULT_SSH_KEY: "/root/.ssh"
    }
}


# TODO Templatize this with assloads of comments
DEFAULT_PROJECT_CONFIG = {
    "name": "",
    "image": "",
    "custom_build": False,
    "volumes": {},
    "hostdir": "",
    "workdir": "",
    "ports": {},
    "language": "",
    "use_cwd": False,
    "network_mode": "",
    "entrypoint": "",
    "command": "",
    "mount_ssh_keys": False,
    "default_backend": "",
    "dependencies": [],
    "other_projects": [],
    "healthcheck": {
        "test": "",
        "interval": "1m30s",
        "timeout": "30s",
        "retries": 3,
        "start_period": "0s",
    },
    "caps": [],
    "environment": {
        "host": {},
        "container": {}
    },
}

jinja_env = jinja2.Environment(
    loader=jinja2.PackageLoader('vessel', 'templates'),
    autoescape=jinja2.select_autoescape(['tpl'])
)


class Project(object):
    REQUIRED = ["name", "image"]

    def __init__(self, **kwargs):
        for key in self.REQUIRED:
            if key not in kwargs:
                raise Exception("Missing required config key '{}'".format(key))
        self.command = kwargs.get("command")
        if self.command:
            self.command = self.command.split(" ")
        self.custom_build = kwargs.get("custom_build")
        self.workdir = kwargs.get("workdir")
        self.hostdir = kwargs.get("hostdir");
        self.default_backend = kwargs.get("default_backend")
        self.dependencies = kwargs.get("dependencies")
        self.entrypoint = kwargs.get("entrypoint")
        self.env_vars = kwargs.get("env_vars")
        self.image = kwargs.get("image")
        self.mount_ssh_keys = kwargs.get("mount_ssh_keys")
        self.name = kwargs.get("name")
        self.network_mode = kwargs.get("network_mode")
        self.ports = kwargs.get("ports")
        self._volumes = kwargs.get("volumes")
        self.caps = kwargs.get("caps", [])

        if "environment" in kwargs:
            self.host_env_vars = kwargs["environment"]["host"]
            self.container_env_vars = kwargs["environment"]["container"]

        if "healthcheck" in kwargs:
            cfg = kwargs["healthcheck"]
            if len(cfg["test"]) == 0:
                raise Exception("Missing test for healthcheck,"
                                ", cannot continue")
            if not cfg["test"][0] == "CMD":
                cfg["test"].insert(0, "CMD")

            defaults = DEFAULT_PROJECT_CONFIG["healthcheck"]
            self.healthcheck = cfg
            for key, val in defaults.items():
                self.healthcheck[key] = cfg.get(key, val)

    @property
    def volumes(self):
        # for "delegated" volumes see
        # https://engageinteractive.co.uk/blog/making-docker-faster-on-mac
        vol = self._volumes.copy()
        if self.hostdir and self.workdir:
            vol[self.hostdir] = self.workdir
        return {k: "{}:delegated".format(v) for k, v in vol.items()}

    @classmethod
    def escape_host_envvars(cls, envvar):
        """
        Turns $ENV_VAR into ${ENV_VAR} for docker-compose to consume
        """
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


def _check_initialized():
    if not os.path.exists(VESSEL_ROOT) or not os.path.exists(VESSEL_CONFIG):
        click.echo("Vessel is not initialized, please run `vessel init` first")
        sys.exit(1)


def _compose_command(compose_path, command, workdir=None, extras=None):
    cmd = []
    cmd.append("docker-compose -f {}".format(compose_path))
    cmd.append(command)
    if workdir:
        cmd.append("-w {}".format(workdir))
    if extras:
        cmd.extend(extras)
    return " ".join(cmd)


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
        proj_cfg = [Project(**p) for _, p in projects.items()]
    except Exception as e:
        sys.exit(e)
    template = jinja_env.get_template("docker-compose.tpl")
    return template.render(projects=proj_cfg)


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
    projects = {}
    cfg = _load_config(root_project)
    projects[cfg["name"]] = cfg
    for key in ["dependencies", "other_projects"]:
        for project in cfg.get(key, []):
            sub_projects = _discover_projects(project)
            projects.update(sub_projects)
    return projects


def _collect_hostvars(ctx, projects):
    # NOTE Variable priority order
    #      Environment > Config
    # TODO Walk the configs and look for things that look like envvars
    #      as per escape_host_envvars above, then error out if any
    #      are missing
    var_cache = {}
    var_conflict = {}
    var_overrides = {}
    for _, project in projects.items():
        for k, v in project.get("environment", {}).get("host", {}).items():
            if k in var_cache and var_cache[k] != v:
                var_conflict.setdefault(k, [])
                var_conflict[k].append(project)
            else:
                var_cache[k] = str(v)
                if k in os.environ:
                    var_cache[k] = os.environ[k]
                    var_overrides.setdefault(k, [])
                    var_overrides[k].append(project)

    errors = False
    if ctx.obj.debug:
        for v, proj in var_overrides.items():
            click.echo("'{}' is already set in the environment and overrides "
                       "settings defined in: {}".format(", ".format(proj)))

    for k, proj in var_conflict.items():
        if len(proj) > 1:
            click.echo("Environment variable conflict! '{}' is defined "
                        "by the following: ".format(k, ", ".join(proj)))
            errors = True

    if errors:
        sys.exit(1)

    var_cache["VESSEL_ROOT"] = VESSEL_ROOT
    if ctx.obj.debug:
        click.echo("Environment:")
        for k, v in var_cache.items():
            click.echo("{}={}".format(k, v))
        click.echo()
    return var_cache


def _pre_run(ctx, project_name, project_configs):
    _check_initialized()
    if not _project_exists(project_name):
        click.echo("No project named '{}' exists. "
                   "You should create one!".format(project))
        sys.exit(1)

    envvars = _collect_hostvars(ctx, project_configs)
    envvars.update(os.environ.copy())

    for _name, cfg in project_configs.items():
        if cfg.get("workdir") and cfg.get("hostdir"):
            cfg["volumes"][cfg["hostdir"]] = cfg["workdir"]

    # TODO This doesn't gather all the possible env vars, dumbass
    return envvars, project_configs[project_name]


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

    vessel_config = _load_config()
    proj_config = DEFAULT_PROJECT_CONFIG.copy()

    # TODO Load vrssel config before the command runs
    proj_config.update({
        "name": project,
        "language": language,
        "hostdir": os.getcwd(),
        "workdir": "/{}".format(project),
        "default_backend": DEFAULT_CONFIG["default_backend"]
    })

    proj_config["volumes"] = {
        "{}/data".format(proj_path): "",
    }
    proj_config.update(**vessel_config["default_volumes"])

    if language and language.strip().lower() == "python":
        proj_config["volumes"] = {
            "{}/venv".format(_project_path(project)): "/root/.virtualenvs"
        }

    with open("{}/config.toml".format(proj_path), 'w') as f:
        f.write(toml.dumps(proj_config))


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
    projects = _discover_projects(project)
    envvars, cfg = _pre_run(ctx, project, projects)

    compose_path = _project_compose_path(project)
    with open(compose_path, 'w') as f:
        f.write(_generate_compose(projects))

    cmd = _compose_command(compose_path, "up --force-recreate -d")
    if ctx.obj.debug:
        click.echo(cmd)
    cmd = shlex.split(cmd)
    subprocess.Popen(cmd, env=envvars).wait()


@vessel.command()
@click.argument("project", nargs=1)
@click.argument("command", nargs=-1)
@click.option("-s", "--service", default=None)
@click.option("-w", "--workdir", default=None)
@click.pass_context
def run(ctx, project, command, service, workdir):
    projects = _discover_projects(project)
    service = service or project
    workdir = workdir or projects[service].get("workdir")

    envvars, cfg = _pre_run(ctx, project, projects)

    compose_path = _project_compose_path(project)
    with open(compose_path, 'w') as f:
        f.write(_generate_compose(projects))

    extras = [service]
    extras.extend(command)
    cmd = _compose_command(compose_path, "run",
                           workdir=workdir, extras=extras)
    if ctx.obj.debug:
        click.echo(cmd)
    cmd = shlex.split(cmd)
    subprocess.Popen(cmd, stdin=sys.stdout, stdout=sys.stdin,
                     env=envvars).wait()


@vessel.command()
@click.argument("project", nargs=1)
@click.argument("command", nargs=-1)
@click.option("-s", "--service", default=None)
@click.pass_context
def exec(ctx, project, command, service):
    projects = _discover_projects(project)
    cfg = _pre_run(ctx, project, projects)

    compose_path = _project_compose_path(project)
    with open(compose_path, 'w') as f:
        f.write(_generate_compose(projects))

    service = service or project
    cmd = ["docker-compose -f {} exec".format(compose_path)]

    cmd.append(service)

    if command:
        cmd.extend(command)

    cmd = " ".join(cmd)

    if ctx.obj.debug:
        click.echo(cmd)
    cmd = shlex.split(cmd)
    subprocess.Popen(cmd, stdin=sys.stdout, stdout=sys.stdin).wait()


@vessel.command()
@click.argument("project")
@click.pass_context
def export(ctx, project):
    projects = _discover_projects(project)
    cfg = _pre_run(ctx, project, projects)

    compose_path = _project_compose_path(project)
    compose = _generate_compose(projects)
    with open(compose_path, 'w') as f:
        f.write(compose)
    click.echo(compose)


@vessel.command()
@click.argument("project")
@click.pass_context
def logs(ctx, project):
    if not _project_exists(project):
        click.echo("No project named '{}' exists. "
                   "You should create one!".format(project))
        sys.exit(1)

    compose_path = _project_compose_path(project)
    cmd = shlex.split("docker-compose -f {} logs -f".format(compose_path))
    subprocess.Popen(cmd).wait()


@vessel.command()
@click.argument("project")
@click.pass_context
def kill(ctx, project):
    projects = _discover_projects(project)
    _pre_run(ctx, project, projects)
    compose_path = _project_compose_path(project)
    cmd = "docker-compose -f {} kill".format(compose_path)
    if ctx.obj.debug:
        click.echo(cmd)
    cmd = shlex.split(cmd)
    subprocess.Popen(cmd)
