#!/usr/bin/env bash
# Run as the dedicated VM deploy user. Never source API credentials as shell code.
set -Eeuo pipefail
umask 077

root=/opt/macrodashboard
release=${1:?Usage: deploy.sh RELEASE_DIR IMAGE_DIGEST}
image=${2:?Image digest required}
[[ "$release" =~ ^/opt/macrodashboard/releases/[a-f0-9]{40}-[0-9]+-[0-9]+$ ]] || { echo 'Invalid release directory' >&2; exit 2; }
[[ "$image" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]] || { echo 'Immutable GHCR image required' >&2; exit 2; }
test -f "$release/compose.yaml"
test -f "$root/.env"
test -f "$root/compose.env"

exec 9>"$root/.deploy.lock"
flock -w 600 9

compose() {
  local directory=$1
  shift
  MACRO_IMAGE=$(cat "$directory/image") docker compose \
    --project-name macrodashboard --project-directory "$root" \
    --env-file "$root/compose.env" -f "$directory/compose.yaml" "$@"
}

previous=$(readlink -f "$root/current" || true)
# A release directory is unique to a workflow attempt and records the exact digest.
printf '%s\n' "$image" > "$release/image"
compose "$release" config --quiet
# Download before disturbing the running release.
compose "$release" pull

rollback() {
  local code=$?
  trap - ERR
  echo 'Deployment failed; restoring the previous containers' >&2
  if [[ -n "$previous" && -f "$previous/image" ]]; then
    compose "$previous" up -d --no-build --force-recreate --wait --wait-timeout 180 || \
      echo 'ROLLBACK FAILED: inspect Docker logs on the VM' >&2
  else
    compose "$release" down || true
    echo 'First deployment failed; no previous release exists' >&2
  fi
  exit "$code"
}

trap rollback ERR
if [[ -n "$previous" && -f "$previous/image" ]]; then
  # Stop the only background writer before backup and version replacement.
  compose "$previous" stop updater
  compose "$previous" exec -T web python -m scripts.backup
fi
compose "$release" up -d --no-build --force-recreate --wait --wait-timeout 180
# Docker health checks the server; this additionally executes the Streamlit script
# against empty temporary storage and blocks releases with import/render errors.
compose "$release" exec -T -e MACRO_DATA_DIR=/tmp/macro-release-check web \
  python -m scripts.check_app

ln -sfn "$release" "$root/current.next"
mv -Tf "$root/current.next" "$root/current"
if [[ -n "$previous" && "$previous" != "$release" ]]; then
  ln -sfn "$previous" "$root/previous"
fi
trap - ERR
echo "Deployed $image"
