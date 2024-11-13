#!/bin/bash

MY_DIR="${BASH_SOURCE%/*}"

STATUS_LOG="/var/log/client-setup.log"

if [[ ! -d "$MY_DIR" ]]; then 
  MY_DIR="$PWD"
fi

COMMON_DIR="$MY_DIR/../common/"

# shellcheck source=../common/common.sh
source "$COMMON_DIR/common.sh"