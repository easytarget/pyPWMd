from pyPWMd import pypwm_client
from time import sleep
from sys import exit, argv
from atexit import register

'''
    Python Servo demo script, does swipes left and right using a PWM timer
    requires:
        pypwm_server() running, as root,  on the default socket.
        A servo attached to a GPIO pin.
        A free PWM timer mapped to the GPIO pin
        - via the Device Tree or an overlay.

    see: https://github.com/easytarget/pyPWMd

    'chip' and 'timer' are integers, giving the index of
     the gpio pwm chip and timer respectively
'''
chip = 0
timer = 0

def clean_exit(opened):
    # If we opened the timer, close it again on exit.
    pwm.disable(chip, timer)
    if opened:
        print('Closing chip {}, timer {}'.format(chip,timer))
        pwm.close(chip, timer)

# Generate a client object
pwm = pypwm_client()

if pwm.connected == False:
    print('No PWM server, exiting..')
    exit()

# Open the timer if necesscary, register a close event.
if pwm.states()[str(chip)][timer] is None:
    print('Opening chip {}, timer {}'.format(chip,timer))
    pwm.open(chip, timer)
    register(clean_exit, True)
else:
    print('Using chip {}, timer {}'.format(chip,timer))
    register(clean_exit, False)

# Main loop runs forever and fades timer up/down.
steps = [0.5,0,0.5,1]
while True:
    for position in steps:
        pwm.servo(chip, timer, position)
        print('.',end='')
        sleep(1 if len(argv) == 1 else float(argv[1]))
    print()
