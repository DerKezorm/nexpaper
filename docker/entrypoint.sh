#!/bin/sh
# Container entrypoint.
#
# nexpaper must not run as root. A data directory mounted from outside carries the rights of the host,
# and those rarely match the user inside the image by chance. So the container briefly fixes the rights
# as root and then drops to the user "nexpaper". PUID and PGID say which host user owns the files.

set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}

# A number, and not root's: PUID=0 is a common way out of rights trouble, and would run nexpaper as root.
for value in "$PUID" "$PGID"; do
    case "$value" in
        ''|*[!0-9]*)
            echo "nexpaper: PUID and PGID must be numbers (got '$PUID' and '$PGID'). Nothing has been started." >&2
            exit 1
            ;;
    esac
done
if [ "$PUID" = "0" ] || [ "$PGID" = "0" ]; then
    echo "nexpaper: PUID and PGID must not be 0: nexpaper does not run as root. Use the ids of the user who owns" >&2
    echo "  your data directory ('id' on the host shows yours). Nothing has been started." >&2
    exit 1
fi

# Port inside the container, default 8000. NEXPAPER_PORT is for host networking, where the container's port
# is the server's port. Docker does not expand variables in the JSON form of CMD, hence here.
if [ "$1" = "uvicorn" ]; then
    case " $* " in
        *" --port "*) ;;
        *) set -- "$@" --port "${NEXPAPER_PORT:-8000}" ;;
    esac
    # Also when the command was changed in the compose file: no "server: uvicorn" header.
    case " $* " in
        *" --no-server-header "*) ;;
        *) set -- "$@" --no-server-header ;;
    esac
fi

# Started without root already ("user:" in the compose file): nothing to fix.
if [ "$(id -u)" != "0" ]; then
    exec "$@"
fi

if [ "$(id -g nexpaper)" != "$PGID" ]; then
    groupmod -o -g "$PGID" nexpaper
fi
if [ "$(id -u nexpaper)" != "$PUID" ]; then
    usermod -o -u "$PUID" nexpaper
fi

mkdir -p /data

# Only touch it when the owner is wrong. A "chown -R" on every start costs time on large directories.
if [ "$(stat -c %u /data)" != "$PUID" ] || [ "$(stat -c %g /data)" != "$PGID" ]; then
    echo "nexpaper: adjusting ownership of the data directory to $PUID:$PGID."
    # A folder mounted below /data (the intake folder of a scanner or a NAS share, /data/eingang) keeps the owners
    # of its files; only the mounted folder itself is adjusted. "-xdev" alone does not see it: two folders mounted
    # from the same disk of the host have the same device number. So the mount points are read from the kernel.
    # (In a function: its "set --" leaves the command to start alone.)
    own_data() {
        set -- -xdev
        for mounted in $(awk '$5 ~ "^/data/" { print $5 }' /proc/self/mountinfo); do
            set -- "$@" -path "$mounted" -prune -o
            chown -h "$PUID:$PGID" "$mounted"
        done
        find /data "$@" -exec chown -h "$PUID:$PGID" {} +
    }
    own_data
fi

# Owner does not mean writable: on a NAS the directory can belong to the right user and still be closed by
# an access list. Then a long Python error would appear mid-start that nobody reads the cause from. So we
# really write here, as the user that does it later.
# Written and removed as that user: root keeps no right to delete another user's file once the compose file
# drops all capabilities but the few the start needs.
if ! gosu nexpaper sh -c 'touch /data/.write-test && rm -f /data/.write-test' 2>/dev/null; then
    echo "nexpaper: the data directory is not writable." >&2
    echo "" >&2
    echo "  nexpaper runs as uid $PUID, gid $PGID and cannot write to the" >&2
    echo "  directory mounted at /data. Nothing has been started." >&2
    echo "" >&2
    echo "  On the host, that directory needs to belong to that user:" >&2
    echo "" >&2
    echo "      sudo chown -R $PUID:$PGID /path/to/your/data" >&2
    echo "      sudo chmod -R u+rwX /path/to/your/data" >&2
    echo "" >&2
    echo "  PUID and PGID are set in your compose file. To find your own," >&2
    echo "  run 'id' on the host and use the uid and gid it reports." >&2
    exit 1
fi

exec gosu nexpaper "$@"
