version: '3'

services:
  {%- for service in services %}
  {{ service.name }}:
      {%- if service.dependencies %}
      depends_on:
      {%- for dep in service.dependencies %}
        - {{ dep }}
      {% endfor %}
      {%- endif %}
    {%- if service.env_vars %}
    environment:
    {%- for name, value in service.env_vars.items() %}
      {{ name }}: {{ value }}
    {%- endfor %}
    {%- endif %}
    {%- if service.command %}
    command: {{ service.command }}
    {%- endif %}
    image: {{ service.image }}
    {{- service.network_mode and "network_mode:"}} {{ service.network_mode }}
    {%- if service.ports %}
    ports:
    {%- for source, dest in service.ports.items() %}
      - {{ source }}: {{ dest }}
    {%- endfor %}
    {%- endif %}
    {%- if service.volumes %}
    volumes:
    {%- for source, dest in service.volumes.items() %}
      - {{ source }}: {{ dest }}
    {%- endfor %}
    {%- endif %}
    {%- endfor %}
