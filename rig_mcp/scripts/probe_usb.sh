#!/usr/bin/env bash
# Report each USB device's product string as "<path>:<product>".
grep -H . /sys/bus/usb/devices/*/product 2>/dev/null
