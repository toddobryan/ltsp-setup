#!/bin/sh
# ltsp-setup: put a two-monitor client's monitors in their real left-to-right
# order. Cabling differs from desk to desk, so this goes by each monitor's
# EDID hash, looked up in the table from data/lab-monitors.tsv, not by
# connector. A monitor missing from the table falls back on its partner; with
# neither known, the two go side by side in connector order, which at least
# beats X's default of mirroring them.
#
# Run as root by LightDM's display-setup-script, and as the student by
# ltsp-monitor-layout.desktop. It must always exit 0: LightDM refuses to start
# the greeter if a display-setup-script fails.

sys=${LTSP_MONITOR_SYS:-/sys}
table=${LTSP_MONITOR_TABLE:-/etc/ltsp-monitor-layout.tsv}

log() {
    logger -t ltsp-monitor-layout "$*" 2>/dev/null || :
}

# Prints "left" or "right" for a hash in the table, and nothing otherwise.
side() {
    awk -F '\t' -v hash="$1" '
        $2 == hash { print "left"; exit }
        $3 == hash { print "right"; exit }
    ' "$table" 2>/dev/null
}

# sysfs says HDMI-A-1 where xrandr says HDMI-1.
xrandr_name() {
    printf '%s\n' "$1" | sed 's/-A-/-/'
}

count=0
for dir in "$sys"/class/drm/card*-*; do
    [ "$(cat "$dir/status" 2>/dev/null)" = connected ] || continue
    count=$((count + 1))
    name=${dir##*/}
    name=$(xrandr_name "${name#card*-}")
    hash=$(sha1sum <"$dir/edid" | cut -d ' ' -f 1)
    if [ "$count" -eq 1 ]; then
        first=$name first_side=$(side "$hash")
    else
        second=$name second_side=$(side "$hash")
    fi
done

if [ "$count" -ne 2 ]; then
    log "$count monitor(s) connected, nothing to arrange"
    exit 0
fi

if [ "$first_side" = right ] || [ "$second_side" = left ]; then
    left=$second right=$first
else
    left=$first right=$second
fi
if [ -z "$first_side$second_side" ]; then
    log "neither monitor is in $table, using connector order"
fi

xrandr --output "$left" --auto --primary --pos 0x0 \
    --output "$right" --auto --right-of "$left" ||
    log "xrandr failed for left=$left right=$right"
log "left=$left right=$right"
exit 0
