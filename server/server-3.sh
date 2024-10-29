# Add Dconf defaults

mkdir -p /etc/dconf/profile

cat <<EOF >/etc/dconf/profile/user
user-db:user
system-db:local
EOF

mkdir -p /etc/dconf/db/local.d

cat <<EOF >/etc/dconf/db/local.d/01-datetime
[org/cinnamon/desktop/interface]
clock-show-date=true
clock-show-seconds=true
clock-use-24h=false

[org/gnome/desktop/interface]
clock-show-date=true
clock-show-seconds=true
clock-format='12h'
EOF

cat <<EOF >/etc/dconf/db/local.d/02-keyboard
[org/gnome/libgnomekbd/keyboard]
layouts=['us', 'us\tdvorak-alt-intl']
options=['grp\tgrp:win_space_toggle', 'terminate\tterminate:ctrl_alt_bksp', 'ctrl\tctrl:swap_lalt_lctl', 'Compose key\tcompose:ralt']

[org/cinnamon/desktop/interface]
keyboard-layout-prefer-variant-names=true
EOF

