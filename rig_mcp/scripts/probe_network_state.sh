#!/usr/bin/env bash
# Report each network interface's link state as "<path>:<operstate>".
grep -H . /sys/class/net/*/operstate 2>/dev/null
