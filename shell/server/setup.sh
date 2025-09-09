#!/bin/bash

## server
#ETH0="eno1"
#ETH1="eno2"

# vm
ETH0="enp0s3"
ETH1="enp0s8"
ETH2="enp0s9"

MY_DIR="${BASH_SOURCE%/*}"

STATUS_LOG="/var/log/server-setup.log"

if [[ ! -d "$MY_DIR" ]]; then 
  MY_DIR="$PWD"
fi

COMMON_DIR="$MY_DIR/../common/"

# shellcheck source=../common/common.sh
source "$COMMON_DIR/common.sh"

install_server_ltsp() {
  # Install LTSP Packages
  add-apt-repository universe && \
  apt update -y && \
  apt install --install-recommends -y ltsp dnsmasq nfs-kernel-server openssh-server squashfs-tools ethtool net-tools epoptes && \
  git clone https://github.com/ltsp/binaries.git && \
  mkdir -p /srv/tftp/ltsp && \
  cp ./binaries/binaries/* /srv/tftp/ltsp/ && \
  rm -rf binaries
}

write_hostname() {
  cat <<- EOF | awk 'NR==1 && match($0, /^ +/){n=RLENGTH} {print substr($0, n+1)}' >/etc/hostname
    200-231-server.dupontmanual.org
EOF
}

write_hosts() {
  cat <<- EOF | awk 'NR==1 && match($0, /^ +/){n=RLENGTH} {print substr($0, n+1)}' >/etc/hosts
    127.0.0.1        localhost
    127.0.1.1        200-231-server.dupontmanual.org 200-231-server   
EOF
}

write_netplan() {
  cat <<- EOF | awk 'NR==1 && match($0, /^ +/){n=RLENGTH} {print substr($0, n+1)}' >/etc/netplan/static_and_dhcp.yaml
    network:
      version: 2
      renderer: networkd
      ethernets:
        ${ETH0}:
          dhcp4: true
          wakeonlan: true
          link-local: []
        ${ETH1}:
          renderer: networkd
          addresses:
            - 192.168.67.1/24
          wakeonlan: true
          link-local: []
        ${ETH2}:
          renderer: networkd
          activation-mode: off       
EOF
}

handle_networking() {
  write_hostname
  write_hosts

  rm /etc/netplan/*
  
  write_netplan
  chmod go-r /etc/netplan/static_and_dhcp.yaml

  netplan apply
}

install_packages() {
  # Update and upgrade after kernel upgrade
  apt update
  apt upgrade -y

  install_standard_apps
  install_plt
  install_chrome
  install_vscode
  install_intellij
  install_server_ltsp
  install_ldap_and_kerberos

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
    handle_networking
    update_mirrors_and_set_to_autorun
    ;;
  install_pkgs)
    printf "Running install_packages..."
    install_packages
    systemctl mask systemd-udev-settle.service
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

