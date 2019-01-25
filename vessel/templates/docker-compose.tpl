version: '3'

services:
  {%- for service in services %}
  {{ service.name }}:
    {%- if service.dependencies %}
    depends_on:
    {%- for dep in service.dependencies %}
      - {{ dep }}
    {%- endfor %}
    {%- endif %}
    {%- if service.container_env_vars %}
    environment:
    {%- for name, value in service.container_env_vars.items() %}
      {{ name }}: "{{ service.escape_host_envvars(value) }}"
    {%- endfor %}
    {%- endif %}
    {%- if service.command %}
    command: {{ service.command }}
    {%- elif service.entrypoint %}
    entrypoint: {{ service.entrypoint }}
    {%- endif %}
    image: {{ service.image }}
    {%- if service.network_mode %}
    network_mode: "{{ service.network_mode }}"
    {%- endif %}

    {%- if service.ports %}
    ports:
    {%- for source, dest in service.ports.items() %}
      - "{{ source }}:{{ dest }}"
    {%- endfor %}
    {%- endif %}
    {%- if service.volumes %}
    volumes:
    {%- for source, dest in service.volumes.items() %}
    {%- if source != "" and dest != "" %}
      - {{ service.escape_host_envvars(source) }}:{{ service.escape_host_envvars(dest) }}
    {%- endif %}
    {%- endfor %}
    {%- endif %}
    {%- endfor %}
