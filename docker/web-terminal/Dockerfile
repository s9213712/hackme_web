FROM alpine:3.20

RUN adduser -D -h /home/root -s /bin/sh terminal \
    && apk add --no-cache bash busybox-extras coreutils findutils grep less nano vim \
    && mkdir -p /home/root \
    && chown -R terminal:terminal /home/root

USER terminal
WORKDIR /home/root

CMD ["/bin/sh"]
