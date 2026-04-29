FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        coreutils \
        curl \
        dnsutils \
        file \
        findutils \
        git \
        grep \
        iproute2 \
        iputils-ping \
        less \
        nano \
        netcat-openbsd \
        procps \
        psmisc \
        sed \
        tar \
        tmux \
        tree \
        unzip \
        vim-tiny \
        wget \
        zip \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --home-dir /home/root --shell /bin/bash terminal \
    && mkdir -p /home/root \
    && chown -R terminal:terminal /home/root

USER terminal
WORKDIR /home/root

CMD ["/bin/bash", "-l"]
