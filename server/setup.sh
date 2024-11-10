#!/bin/bash

STATUS_LOG="/var/log/server-setup.log"

update_status() {
  local new_status=$1
  printf "%s : %s" "$new_status" "$(date)"
  printf "%s" "$new_status" > "$STATUS_LOG"
}

update_mirrors_and_set_to_autorun() {
  # Update mirrors and upgrade all
  cat <<- EOF | awk 'NR==1 && match($0, /^ +/){n=RLENGTH} {print substr($0, n+1)}' >/etc/apt/sources.list.d/official-package-repositories.list
    deb http://mirror.team-cymru.com/mint-packages wilma main upstream import backport 

    deb https://mirror.team-cymru.org/ubuntu noble main restricted universe multiverse
    deb https://mirror.team-cymru.org/ubuntu noble-updates main restricted universe multiverse
    deb https://mirror.team-cymru.org/ubuntu noble-backports main restricted universe multiverse

    deb http://security.ubuntu.com/ubuntu/ noble-security main restricted universe multiverse
EOF

  apt update

  apt upgrade -y

  set_admin_to_autologin
  allow_sysadmin_to_run_script_as_root
  add_script_to_reboot_cron

  update_status "install_pkgs"

  # Reboot
  shutdown -r now
}

set_admin_to_autologin() {
  mkdir /etc/systemd/system/getty@tty1.service.d/

  cat <<- EOF | awk 'NR==1 && match($0, /^ +/){n=RLENGTH} {print substr($0, n+1)}' >/etc/systemd/system/getty@tty1.service.d/override.conf
    [Service]
    ExecStart=
    ExecStart=-/sbin/agetty --noissue --autologin sysadmin %I $TERM
    Type=idle
EOF
}

allow_sysadmin_to_run_script_as_root() {
  cat <<- EOF | awk 'NR==1 && match($0, /^ +/){n=RLENGTH} {print substr($0, n+1)}' >/etc/sudoers.d/setup-script-perms
    sysadmin ALL=NOPASSWD:/home/sysadmin/ltsp-setup/server/setup.sh
EOF
}

add_script_to_reboot_cron() {
  cat <<- EOF | awk 'NR==1 && match($0, /^ +/){n=RLENGTH} {print substr($0, n+1)}' >/etc/cron.d/run-setup-script
    @reboot sysadmin sudo /home/sysadmin/ltsp-setup/server/setup.sh
EOF
}

install_plt() {
  # Install DrRacket

  wget https://download.racket-lang.org/releases/8.14/installers/racket-8.14-x86_64-linux-cs.sh

  sh racket-8.14-x86_64-linux-cs.sh --unix-style --create-dir --dest-dir /usr/

  rm racket-8.14-x86_64-linux-cs.sh

  rm /usr/
}

install_ltsp() {
    # Install LTSP Packages

  add-apt-repository universe

  apt update -y

  apt install --install-recommends -y ltsp dnsmasq nfs-kernel-server openssh-server squashfs-tools ethtool net-tools epoptes

  git clone https://github.com/ltsp/binaries.git

  mkdir -p /srv/tftp/ltsp
  
  cp ./ltsp/binaries/binaries/* /srv/tftp/ltsp/
}

install_pkgs() {
  # Update and upgrade after kernel upgrade
  apt update

  apt upgrade -y

  # Install Java
  apt install -y openjdk-17-jdk

  # Install Chrome

  wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb

  apt install -y ./google-chrome-stable_current_amd64.deb

  rm google-chrome-stable_current_amd64.deb

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

  # Add Dvorak-Qwerty

  git clone https://github.com/tbocek/dvorak.git

  cd ./dvorak || exit
  
  make 
  
  make install

  # Next Stage

  update_status "modify_dconf"

  # Reboot
  
  shutdown -r now
}

modify_dconf() {
  # Create dconf local profile
  mkdir -p /etc/dconf/profile

  cat <<- EOF | awk 'NR==1 && match($0, /^ +/){n=RLENGTH} {print substr($0, n+1)}' >/etc/dconf/profile/user
    user-db:user
    system-db:local
EOF

  mkdir -p /etc/dconf/db/local.d

  cat <<- EOF | awk 'NR==1 && match($0, /^ +/){n=RLENGTH} {print substr($0, n+1)}' >/etc/dconf/db/local.d/01-datetime
    [org/cinnamon/desktop/interface]
    clock-show-date=true
    clock-show-seconds=true
    clock-use-24h=false

    [org/gnome/desktop/interface]
    clock-show-date=true
    clock-show-seconds=true
    clock-format='12h'
EOF

  cat <<- EOF | awk 'NR==1 && match($0, /^ +/){n=RLENGTH} {print substr($0, n+1)}' >/etc/dconf/db/local.d/02-keyboard
    [org/gnome/libgnomekbd/keyboard]
    layouts=['us', 'us\tdvorak-alt-intl']
    options=['grp\tgrp:win_space_toggle', 'terminate\tterminate:ctrl_alt_bksp', 'ctrl\tctrl:swap_lalt_lctl', 'Compose key\tcompose:ralt']

    [org/cinnamon/desktop/interface]
    keyboard-layout-show-flags=false
    keyboard-layout-prefer-variant-names=true
EOF

  dconf update

  # Done
  update_status "done"

  # Reboot
  shutdown -r now
}

clean_up() {
  rm /etc/sudoers.d/setup-script-perms
  rm /etc/systemd/system/getty@tty1.service.d/override.conf
  rm /etc/cron.d/run-setup-script
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
    printf "Running stage2..."
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

