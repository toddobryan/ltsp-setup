#!/bin/sh
# ltsp-setup: forget this user's saved Xfce display layout before their session
# starts. Homes are on NFS, so a layout saved at one desk follows the student
# to every other desk, whose cabling and monitors differ. Run as root by
# LightDM's session-setup-script, which sets HOME to the user's home. It must
# always exit 0: LightDM ends the session if a session-setup-script fails.

rm -f "$HOME/.config/xfce4/xfconf/xfce-perchannel-xml/displays.xml" 2>/dev/null
exit 0
