#!/usr/bin/env bash
# List the serial character devices present on the Pi.
ls -1 /dev/ttyUSB* /dev/ttyACM* /dev/ttyAMA* /dev/serial0 2>/dev/null
