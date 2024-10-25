#!/bin/sh

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

echo "deb [arch=amd64,arm64,armhf signed-by=/etc/apt/keyrings/packages.microsoft.gpg] https://packages.microsoft.com/repos/code stable main" |sudo tee /etc/apt/sources.list.d/vscode.list > /dev/null

rm -f packages.microsoft.gpg

apt update

apt install -y code

# Install IntelliJ IDEA

add-apt-repository -y ppa:mmk2410/intellij-idea

apt update

apt install intellij-idea-community

# Show date and seconds in the clock

dconf write /org/cinnamon/desktop/interface/clock-show-date true
dconf write /org/gnome/desktop/interface/clock-show-date true

dconf write /org/cinnamon/desktop/interface/clock-show-seconds true
dconf write /org/gnome/desktop/interface/clock-show-seconds true

dconf write /org/cinnamon/desktop/interface/clock-use-24h false
dconf write /org/gnome/desktop/interface/clock-format "'12h'"

# Add Dvorak layout

dconf write /org/gnome/libgnomekbd/keyboard/layouts "['us', 'us\tdvorak-alt-intl']"

dconf write /org/cinnamon/desktop/interface/keyboard-layout-prefer-variant-names true

dconf write /org/gnome/libgnomekbd/keyboard/options "['grp\tgrp:win_space_toggle', 'terminate\tterminate:ctrl_alt_bksp', 'ctrl\tctrl:swap_lalt_lctl', 'Compose key\tcompose:ralt']"

# Add Dvorak-Qwerty

git clone https://github.com/tbocek/dvorak.git
cd dvorak
make make install


