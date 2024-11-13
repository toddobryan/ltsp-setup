#!/bin/bash

MY_DIR="${BASH_SOURCE%/*}"

STATUS_LOG="/var/log/server-setup.log"

if [[ ! -d "$MY_DIR" ]]; then 
  MY_DIR="$PWD"
fi

COMMON_DIR="$MY_DIR/../common/"

# shellcheck source=../common/common.sh
source "$COMMON_DIR/common.sh"

install_packages() {
  # Update and upgrade after kernel upgrade
  apt update
  apt upgrade -y

  install_standard_apps
  install_chrome
  install_vscode
  install_intellij
  install_server_ltsp

  add_dvorak_qwerty_keymap

  # Next Stage
  update_status "modify_dconf"

  # Reboot
  shutdown -r now
}

if [[ -f $STATUS_LOG ]]; then
  CURRENT_STATUS="$(cat $STATUS_LOG)"
else
  CURRENT_STATUS="update_mirrors"
fi

printf "Current Status is: %s" $CURRENT_STATUS
sleep 3

case "$CURRENT_STATUS" in
  update_mirrors)
    printf "Running update_mirrors_and_set_to_autorun..."
    update_mirrors_and_set_to_autorun
    ;;
  install_pkgs)
    printf "Running install_packages..."
    install_packages
    ;;
  modify_dconf)
    printf "Running modify_dconf..."
    modify_dconf
    ;;
  done)
    printf "Cleaning up..."
    clean_up
    printf "All stages complete: %s" "$CURRENT_STATUS"
    shutdown -r now
    ;;
  *)
    printf "ERROR. No matched case."
    clean_up
esac

