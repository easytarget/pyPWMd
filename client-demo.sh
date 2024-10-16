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
timer=0

# Open the timer
pwmtimerctl open $chip $timer

echo "Press ctrl-c to exit."
# A simple fader
while true ; do
    for power in 0.1 0.3 0.6 1 0.6 0.3 0.1 0 ; do
        echo -n "."
        pwmtimerctl pwm $chip $timer $power
        sleep 0.5
    done
    echo
done
