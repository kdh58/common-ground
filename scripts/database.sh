#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077

usage() {
    echo "Usage: $0 backup [FILE] | restore FILE --yes" >&2
    exit 2
}

case "${1:-}" in
    backup)
        [[ $# -le 2 ]] || usage
        destination=${2:-backups/common-ground-$(date -u +%Y%m%dT%H%M%SZ).db}
        [[ ! -e "$destination" ]] || { echo "Backup already exists: $destination" >&2; exit 1; }
        mkdir -p "$(dirname "$destination")"
        temporary=$(mktemp "${destination}.tmp.XXXXXX")
        trap 'rm -f "$temporary"' EXIT
        docker compose exec -T web python -m app.database_tools backup > "$temporary"
        # A hard link publishes the complete file without overwriting an existing backup.
        ln "$temporary" "$destination"
        echo "Backup saved to $destination"
        ;;
    restore)
        [[ $# -eq 3 && "$3" == --yes ]] || usage
        [[ -s "$2" ]] || { echo "Backup is missing or empty: $2" >&2; exit 1; }
        running=$(docker compose ps --status running -q web)
        restart_web() {
            if [[ -n "$running" ]]; then docker compose start web; fi
        }
        trap restart_web EXIT
        docker compose stop web
        docker compose run --rm --no-deps -T web python -m app.database_tools restore < "$2"
        ;;
    *) usage ;;
esac
