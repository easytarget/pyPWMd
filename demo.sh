#!/usr/bin/bash
#
# Shell based pyPWMd demo
#     Python PWM demo script, does a simple fader on a PWM timer
#    requires:
#        pypwm_server() running, as root,  on the default socket.
#        A led (or whatever) attached to a GPIO pin.
#        A free PWM timer mapped to the GPIO pin
#        - via the Device Tree or an overlay.
#
#    see: https://github.com/easytarget/pyPWMd
#
#    'chip' and 'timer' are integers, giving the index of
#     the gpio pwm chip and timer respectively
#
chip=0
timer=2

pypwmd=./pyPWMd.py

# Open the timer
$pypwmd open $chip $timer
$pypwmd states

# A simple fader
while true ; do
    for duty in 40 100 400 1000 4000 10000 6000 1200 600 120 60 0 ; do
        echo -n "."
        $pypwmd set $chip $timer 1 10000 $duty 0
        sleep 0.5
    done
    echo
done
