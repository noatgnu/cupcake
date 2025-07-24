#!/usr/bin/env bash
# CUPCAKE Pi-gen Docker Build Script
# Based on official pi-gen build-docker.sh but using Bookworm base image

set -eu

DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
BUILD_OPTS="$*"

# Allow user to override docker command
DOCKER=${DOCKER:-docker}

# Ensure that default docker command is not set up in rootless mode
if \
  ! ${DOCKER} ps    >/dev/null 2>&1 || \
    ${DOCKER} info 2>/dev/null | grep -q rootless \
; then
	DOCKER="sudo ${DOCKER}"
fi
if ! ${DOCKER} ps >/dev/null; then
	echo "error connecting to docker:"
	${DOCKER} ps
	exit 1
fi

# Find pi-gen directory
PI_GEN_DIR=""
if [ -d "${DIR}/pi-gen" ]; then
	PI_GEN_DIR="${DIR}/pi-gen"
elif [ -d "${DIR}/../pi-gen" ]; then
	PI_GEN_DIR="${DIR}/../pi-gen"
else
	echo "Cannot find pi-gen directory"
	exit 1
fi

CONFIG_FILE=""
if [ -f "${PI_GEN_DIR}/config" ]; then
	CONFIG_FILE="${PI_GEN_DIR}/config"
fi

while getopts "c:" flag
do
	case "${flag}" in
		c)
			CONFIG_FILE="${OPTARG}"
			;;
		*)
			;;
	esac
done

# Ensure that the configuration file is an absolute path
if test -x /usr/bin/realpath; then
	CONFIG_FILE=$(realpath -s "$CONFIG_FILE" || realpath "$CONFIG_FILE")
fi

# Ensure that the configuration file is present
if test -z "${CONFIG_FILE}"; then
	echo "Configuration file need to be present in '${PI_GEN_DIR}/config' or path passed as parameter"
	exit 1
else
	# shellcheck disable=SC1090
	source ${CONFIG_FILE}
fi

CONTAINER_NAME=${CONTAINER_NAME:-cupcake_pigen_work}
CONTINUE=${CONTINUE:-0}
PRESERVE_CONTAINER=${PRESERVE_CONTAINER:-0}
PIGEN_DOCKER_OPTS=${PIGEN_DOCKER_OPTS:-""}

if [ -z "${IMG_NAME}" ]; then
	echo "IMG_NAME not set in 'config'" 1>&2
	exit 1
fi

# Ensure the Git Hash is recorded before entering the docker container
GIT_HASH=${GIT_HASH:-"$(cd "${PI_GEN_DIR}" && git rev-parse HEAD || echo 'unknown')"}

CONTAINER_EXISTS=$(${DOCKER} ps -a --filter name="${CONTAINER_NAME}" -q)
CONTAINER_RUNNING=$(${DOCKER} ps --filter name="${CONTAINER_NAME}" -q)
if [ "${CONTAINER_RUNNING}" != "" ]; then
	echo "The build is already running in container ${CONTAINER_NAME}. Aborting."
	exit 1
fi
if [ "${CONTAINER_EXISTS}" != "" ] && [ "${CONTINUE}" != "1" ]; then
	echo "Container ${CONTAINER_NAME} already exists and you did not specify CONTINUE=1. Aborting."
	echo "You can delete the existing container like this:"
	echo "  ${DOCKER} rm -v ${CONTAINER_NAME}"
	exit 1
fi

# Modify original build-options to allow config file to be mounted in the docker container
BUILD_OPTS="$(echo "${BUILD_OPTS:-}" | sed -E 's@\-c\s?([^ ]+)@-c /config@')"

# Build our custom Bookworm-based pi-gen Docker image
echo "Building CUPCAKE pi-gen Docker image (Bookworm-based)..."
${DOCKER} build --build-arg BASE_IMAGE=debian:bookworm -f "${DIR}/Dockerfile.cupcake-pigen" -t cupcake-pi-gen "${PI_GEN_DIR}"

if [ "${CONTAINER_EXISTS}" != "" ]; then
  DOCKER_CMDLINE_NAME="${CONTAINER_NAME}_cont"
  DOCKER_CMDLINE_PRE="--rm"
  DOCKER_CMDLINE_POST="--volumes-from=${CONTAINER_NAME}"
else
  DOCKER_CMDLINE_NAME="${CONTAINER_NAME}"
  DOCKER_CMDLINE_PRE="-td"
  DOCKER_CMDLINE_POST=""
fi

# Ensure binfmt_misc is mounted for QEMU emulation
if [[ "$OSTYPE" == "linux"* ]]; then
  if ! mountpoint -q -- /proc/sys/fs/binfmt_misc; then
    if ! sudo mount binfmt_misc -t binfmt_misc /proc/sys/fs/binfmt_misc; then
        echo "mounting binfmt_misc failed"
        exit 1
    fi
    echo "binfmt_misc mounted"
  fi
  
  # Register qemu-arm for binfmt_misc if needed
  qemu_arm=$(which qemu-arm-static || echo "/usr/bin/qemu-arm-static")
  if [ -f "$qemu_arm" ]; then
    if ! grep -q "^interpreter ${qemu_arm}" /proc/sys/fs/binfmt_misc/qemu-arm* 2>/dev/null; then
      # Register qemu-arm for binfmt_misc
      reg="echo ':qemu-arm-rpi:M::"\
"\x7fELF\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x28\x00:"\
"\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:"\
"${qemu_arm}:F' > /proc/sys/fs/binfmt_misc/register"
      echo "Registering qemu-arm for binfmt_misc..."
      sudo bash -c "${reg}" 2>/dev/null || true
    fi
  fi
fi

trap 'echo "got CTRL+C... please wait 5s" && ${DOCKER} stop -t 5 ${DOCKER_CMDLINE_NAME}' SIGINT SIGTERM

echo "Starting CUPCAKE pi-gen build in Docker container..."
echo "Build options: ${BUILD_OPTS}"
echo "Container name: ${DOCKER_CMDLINE_NAME}"
echo "Config file: ${CONFIG_FILE}"

# Run Docker container and capture exit code properly
${DOCKER} run \
  $DOCKER_CMDLINE_PRE \
  --name "${DOCKER_CMDLINE_NAME}" \
  --privileged \
  ${PIGEN_DOCKER_OPTS} \
  --volume "${CONFIG_FILE}":/config:ro \
  -e "GIT_HASH=${GIT_HASH}" \
  $DOCKER_CMDLINE_POST \
  cupcake-pi-gen \
  bash -e -o pipefail -c "
    echo 'Container started, setting up qemu...'
    dpkg-reconfigure qemu-user-static
    echo 'qemu-user-static configured'
    
    # binfmt_misc is sometimes not mounted with debian bookworm image
    (mount binfmt_misc -t binfmt_misc /proc/sys/fs/binfmt_misc || true)
    echo 'binfmt_misc setup complete'
    
    echo 'Checking pi-gen directory...'
    ls -la /pi-gen/
    
    echo 'Starting pi-gen build...'
    cd /pi-gen && ./build.sh ${BUILD_OPTS}
    
    echo 'Build completed, copying logs...'
    rsync -av work/*/build.log deploy/ || echo 'No build logs to copy'
  "

BUILD_EXIT_CODE=$?
echo "Docker container exit code: ${BUILD_EXIT_CODE}"

# Always copy results and logs, even if build failed
echo "copying results from deploy/"
${DOCKER} cp "${CONTAINER_NAME}":/pi-gen/deploy - | tar -xf - || echo "Failed to copy deploy directory"

echo "copying log from container ${CONTAINER_NAME} to deploy/"
${DOCKER} logs --timestamps "${CONTAINER_NAME}" &>deploy/build-docker.log

echo "Deploy directory contents:"
ls -lah deploy

# cleanup
if [ "${PRESERVE_CONTAINER}" != "1" ]; then
	${DOCKER} rm -v "${CONTAINER_NAME}" || ${DOCKER} rm -f "${CONTAINER_NAME}"
fi

if [ "${BUILD_EXIT_CODE}" -ne 0 ]; then
	echo "Build failed with exit code ${BUILD_EXIT_CODE}"
	exit ${BUILD_EXIT_CODE}
fi

echo "Done! Your image(s) should be in deploy/"