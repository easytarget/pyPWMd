from pyPWMd import pypwm_client
from time import sleep
from sys import exit, argv
from atexit import register

'''
    Python PWM demo script, does a simple fader on a PWM timer
    requires:
        pypwm_server() running, as root,  on the default socket.
        A led (or whatever) attached to a GPIO pin.
        A free PWM timer mapped to the GPIO pin
        - via the Device Tree or an overlay.

    see: https://github.com/easytarget/pyPWMd

    'chip' and 'timer' are integers, giving the index of
     the gpio pwm chip and timer respectively
'''
chip = 0
timer = 0

# If we opened the timer, close it again on exit.
def clean_exit():
    pwm.close(chip, timer)

# Generate a client object
pwm = pypwm_client(verbose=True)

if pwm.connected == False:
    print('No PWM server, exiting..')
    exit()

# Open the timer if necesscary, register a close event.
if pwm.states()[str(chip)][timer] is None:
    pwm.open(chip, timer)
    register(clean_exit)

# Main loop runs forever and fades timer up/down.
power = 0
step = 0.1
while True:
    pwm.set(chip, timer, 1, pwm.f2p(5000, power), 0)
    power = round(min(max(power + step, 0),1),3)
    step = -step if power in [0,1] else step
    print('{}'.format('.' if power != 0 else '.\n'), end='', flush=True)
    sleep(0.2 if len(argv) == 1 else float(argv[1]))
