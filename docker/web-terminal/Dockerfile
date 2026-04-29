FROM ubuntu:24.04

LABEL org.opencontainers.image.title="Hackme Web Terminal Ubuntu"
LABEL org.opencontainers.image.description="Official Ubuntu LTS userspace for isolated Hackme Web Terminal sessions"
LABEL org.opencontainers.image.version="24.04"

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        apt-utils \
        bash \
        bash-completion \
        ca-certificates \
        coreutils \
        curl \
        debianutils \
        dnsutils \
        diffutils \
        file \
        findutils \
        gawk \
        git \
        gnupg \
        grep \
        gzip \
        hostname \
        iproute2 \
        iputils-ping \
        less \
        locales \
        lsb-release \
        man-db \
        manpages \
        nano \
        ncurses-base \
        ncurses-bin \
        ncurses-term \
        netcat-openbsd \
        openssh-client \
        procps \
        psmisc \
        rsync \
        sed \
        strace \
        tar \
        tmux \
        tree \
        ubuntu-standard \
        unzip \
        util-linux \
        vim-tiny \
        wget \
        xz-utils \
        zip \
    && rm -rf /var/lib/apt/lists/* \
    && locale-gen C.UTF-8 || true \
    && useradd --create-home --home-dir /home/root --shell /bin/bash terminal \
    && mkdir -p /home/root \
    && chown -R terminal:terminal /home/root

USER terminal
WORKDIR /home/root

CMD ["/bin/bash", "-l"]
