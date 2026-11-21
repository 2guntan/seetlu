# Same Postgres major version as the database (pg_basebackup, pg_ctl for the restore drill) + AWS CLI for S3.
FROM timescale/timescaledb:2.17.2-pg16
RUN apk add --no-cache bash aws-cli coreutils
COPY lib.sh backup-loop.sh backup-now.sh restore-drill.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/*.sh
ENTRYPOINT []
CMD ["backup-loop.sh"]
