#!/usr/bin/env bash
# List the sysfs wireless directories, one per wireless interface.
ls -1d /sys/class/net/*/wireless 2>/dev/null
