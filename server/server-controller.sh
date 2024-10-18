#!/bin/bash

STATUS_LOG="/var/log/server-controller.log"

update_status() {
  local new_status=$1
  printf "%s : %s" "$new_status" "$(date)"
  printf "%s" "$new_status" > "$STATUS_LOG"

}

action_for_stage0() {
  # Update mirrors and upgrade all
  cat <<EOF >/etc/apt/sources.list.d/official-package-repositories.list
deb http://mirror.team-cymru.com/mint-packages wilma main upstream import backport 

deb https://mirror.team-cymru.org/ubuntu noble main restricted universe multiverse
deb https://mirror.team-cymru.org/ubuntu noble-updates main restricted universe multiverse
deb https://mirror.team-cymru.org/ubuntu noble-backports main restricted universe multiverse

deb http://security.ubuntu.com/ubuntu/ noble-security main restricted universe multiverse
EOF

  apt upgrade -y

  update_status "stage1"

  # Reboot
  shutdown -r now
}

if [[ -f $STATUS ]]; then
  CURRENT_STATUS="$(cat $STATUS)"
else
  CURRENT_STATUS="stage0"
fi

case "$CURRENT_STATUS" in
stage0)
  action_for_stage0
  ;;
*)
  printf "Something went wrong: %s" "$CURRENT_STATUS"
  ;;
esac

