#!/bin/sh
# Wait for fake-dut.py to publish the DUT serial pty before ser2net opens it.
# ser2net opens its connector device at load, so without this gate it can start
# before /run/dut-serial exists and fail to bring up its listener. Returns after
# the symlink appears, or after ~5s so a genuinely absent device still proceeds.
n=0
while [ ! -e /run/dut-serial ] && [ "$n" -lt 50 ]; do
  n=$((n + 1))
  sleep 0.1
done
