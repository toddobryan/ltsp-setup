#!/bin/bash

STATUS_LOG="/var/log/server-controller.log"

update_status() {
  local new_status=$1
  printf "%s : %s" "$new_status" "$(date)"
  printf "%s" "$new_status" > "$STATUS_LOG"
  read -r X
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

  #set_admin_to_autologin
  #allow_sysadmin_to_run_script_as_root
  #add_script_to_reboot_cron

  update_status "stage1"

  # Reboot
  shutdown -r now
}

set_admin_to_autologin() {
  mkdir /etc/systemd/system/getty@tty1.service.d/

  cat <<EOF  >/etc/systemd/system/getty@tty1.service.d/override.conf
[Service]
ExecStart=
ExecStart=-/sbin/agetty --noissue --autologin sysadmin %I $TERM
Type=idle
EOF
}

allow_sysadmin_to_run_script_as_root() {
  cat <<EOF >/etc/sudoers.d/setup-script-perms
sysadmin ALL=NOPASSWD:/home/sysadmin/ltsp-setup/server/setup.sh
EOF
}

add_script_to_reboot_cron() {
  cat <<EOF >/etc/cron.d/run-setup-script
@reboot sysadmin sudo /home/sysadmin/ltsp-setup/server/setup.sh
EOF
}

action_for_stage1() {
  # Update and upgrade after kernel upgrade
  apt update

  apt upgrade -y

  # Install Java
  apt install -y openjdk-17-jdk

  # Install Chrome

  wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb

  apt install -y ./google-chrome-stable_current_amd64.deb

  rm google-chrome-stable_current_amd64.deb

  # Install DrRacket

  wget https://download.racket-lang.org/releases/8.14/installers/racket-8.14-x86_64-linux-cs.sh

  sh racket-8.14-x86_64-linux-cs.sh --unix-style --create-dir --dest-dir /usr/

  rm racket-8.14-x86_64-linux-cs.sh

  # Install VSCode

  apt update

  apt install -y software-properties-common apt-transport-https

  wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > packages.microsoft.gpg

  install -D -o root -g root -m 644 packages.microsoft.gpg /etc/apt/keyrings/packages.microsoft.gpg

  printf "deb [arch=amd64,arm64,armhf signed-by=/etc/apt/keyrings/packages.microsoft.gpg] https://packages.microsoft.com/repos/code stable main" \
  | sudo tee /etc/apt/sources.list.d/vscode.list > /dev/null

  rm -f packages.microsoft.gpg

  apt update

  apt install -y code

  # Install IntelliJ IDEA

  add-apt-repository -y ppa:mmk2410/intellij-idea

  apt update

  apt install intellij-idea-community

  update_status "stage2"
}

clean_up() {
  #rm /etc/sudoers.d/setup-script-perms
  #rm /etc/systemd/system/getty@tty1.service.d/override.conf
  #rm /etc/cron.d/run-setup-script
  printf "Nothing to clean up..."
}

if [[ -f $STATUS ]]; then
  CURRENT_STATUS="$(cat $STATUS)"
else
  CURRENT_STATUS="stage0"
fi

printf "Current Status is: %s" $CURRENT_STATUS
read -r X

case "$CURRENT_STATUS" in
stage0)
  printf "Running stage0..."
  action_for_stage0
  ;;
stage1)
  printf "Running stage1..."
  action_for_stage1
  ;;
*)
  printf "Cleaning up..."
  clean_up
  printf "All stages complete: %s" "$CURRENT_STATUS"

  ;;
esac

