version: '3'

services:
  {%- for project in projects %}
  {{ project.name }}:
    {%- if project.dependencies %}
    depends_on:
    {%- for dep in project.dependencies %}
      - {{ dep }}
    {%- endfor %}
    {%- endif %}
    {%- if project.container_env_vars %}
    environment:
    {%- for name, value in project.container_env_vars.items() %}
      {{ name }}: "{{ project.escape_host_envvars(value) }}"
    {%- endfor %}
    {%- endif %}
    {%- if project.command %}
    command: {{ project.command }}
    {%- elif project.entrypoint %}
    entrypoint: {{ project.entrypoint }}
    {%- endif %}
    image: {{ project.image }}
    {%- if project.network_mode %}
    network_mode: "{{ project.network_mode }}"
    {%- endif %}

    {%- if project.ports %}
    ports:
    {%- for source, dest in project.ports.items() %}
      - "{{ source }}:{{ dest }}"
    {%- endfor %}
    {%- endif %}
    {%- if project.volumes %}
    volumes:
    {%- for source, dest in project.volumes.items() %}
    {%- if source != "" and dest != "" %}
      - {{ project.escape_host_envvars(source) }}:{{ project.escape_host_envvars(dest) }}
    {%- endif %}
    {%- endfor %}
    {%- endif %}
    {%- endfor %}
