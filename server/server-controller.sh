#!/bin/bash

STATUS="/var/log/server-controller.log"

if [[ -f $STATUS ]]; then
  CURRENT_STATUS="$(cat $STATUS)"
else
  CURRENT_STATUS="stage0"
  echo "$CURRENT_STATUS : $(date)"
  echo "$CURRENT_STATUS" > "$STATUS"
fi

stage0() {
  # Update mirrors and upgrade all
  cat <<EOF >/etc/apt/sources.list.d/official-package-repositories.list
deb http://mirror.team-cymru.com/mint-packages wilma main upstream import backport 

deb https://mirror.team-cymru.org/ubuntu noble main restricted universe multiverse
deb https://mirror.team-cymru.org/ubuntu noble-updates main restricted universe multiverse
deb https://mirror.team-cymru.org/ubuntu noble-backports main restricted universe multiverse

deb http://security.ubuntu.com/ubuntu/ noble-security main restricted universe multiverse
EOF

  apt upgrade -y

  

  # Reboot
  shutdown -r now
}
