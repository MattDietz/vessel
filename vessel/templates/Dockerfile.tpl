FROM ubuntu:xenial-20180808

RUN apt-get update && \
    apt-get install -y unattended-upgrades apt-utils locales tzdata && \
    unattended-upgrades --debug && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists*

RUN locale-gen en_US.UTF-8 && \
    update-locale LANG=en_US.UTF-8
ENV LC_ALL en_US.UTF-8
ENV LANG en_US.UTF-8
ENV WORKSPACE argus

RUN apt-get update && \
    apt-get install -qy \
        autoconf \
        build-essential \
        curl \
        gfortran \
        git \
        iputils-ping \
        libcurl3 \
        libev4 \
        libffi6 \
        liblapack3 \
        libpq5 \
        libatlas3-base \
        libatlas-base-dev \
        libcurl4-gnutls-dev \
        libev-dev \
        libffi-dev \
        liblapack-dev \
        libldap2-dev \
        libmemcached-dev \
        libmysqlclient20 \
        libmysqlclient-dev \
        libopenblas-dev \
        libpq-dev \
        libxml2 \
        libxml2-dev \
        libxmlsec1 \
        libxmlsec1-openssl \
        libxmlsec1-dev \
        libxslt1.1 \
        libxslt1-dev \
        python \
        python-pip \
        python-dev \
        whois \
        vim

RUN pip install setuptools wheel --upgrade && \
    pip install --ignore-installed virtualenv six virtualenvwrapper tox pbr nose && \
    apt-get clean && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* && \
    echo 'source /usr/local/bin/virtualenvwrapper.sh' >> /root/.bashrc && \
    mkvirtualenv argus

WORKDIR /work
VOLUME /root/.virtualenvs

RUN mkdir -p /work/argus
ADD ./entrypoint.sh /work
ADD ./argus /work/argus
ADD ./tests /work/tests
ADD ./src /work/src
ADD requirements.txt /work
ADD setup.py /work

RUN mkdir /root/.ssh/
ADD ./id_rsa /root/.ssh/id_rsa
ADD ./id_rsa.pub /root/.ssh/id_rsa.pub
RUN ssh-keyscan -t rsa github.com >> /root/.ssh/known_hosts

# RUN workon argus && \
#     pip install --ignore-installed -r requirements.txt
# 
# RUN rm -rf /root/.ssh/
