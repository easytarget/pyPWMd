# Python PWM timer control daemon

PWM control in linux is provided by a generic API which is implemented in pwm drivers by device manufacturers. The Device Tree and pinctl are then used to enable PWM timers and map them onto GPIO pins.

The **PWM Timers** are then controlled [via the API](https://www.kernel.org/doc/html/latest/driver-api/pwm.html), and the `/sys/class/pwm` tree.
- Individual GPIO pins are muxed (mapped) to the timers, this is done via device tree overlays.
  - Generally there is a limited set of mappings available. This is highly device dependent, and this guide does not attempt to cover the hardware and software aspects of identifying and mapping the pins.
  - For the MangoPI MQ Pro I have a guide here: https://github.com/easytarget/MQ-Pro-IO
  - A lot of the 'custom device tree' [building and installing](https://github.com/easytarget/MQ-Pro-IO/blob/main/build-trees/README.md) information in that guide is generic for any modern SBC running recent Linux versions. Although you will need to find the correct dt options and syntax for your hardware.
  - On the Raspberry Pi there are standard Device Tree Overlays you can apply provided with Raspi OS, eg: https://raspberrypi.stackexchange.com/a/143644

There is not (yet) a good generic solution for allowing non-root users to access the PWM timer devices, controlling them as the root user is straightforward (see the API doc), but control from a non-root user is trickier.
- On Raspberry PI's this is provided by the `raspi-gpio` package and `RPi.GPIO` python library.
- I have a non-Pi Single Board COmputer based on risc-v, and the Pi packages are not compatible
  - https://github.com/easytarget/MQ-Pro-IO

## A Python based approach to providing Userland control of PWM timers in linux.

WIP.. Here is a simple example: see also the shell and python demos.

```console
~/pyPWMd $ sudo ./pyPWMd.py server &
[1] 5994
~/pyPWMd $ Starting Python PWM server

Mon Sep 30 12:09:43 2024 :: Server init
Mon Sep 30 12:09:43 2024 :: Scanning for pwm timers
Mon Sep 30 12:09:43 2024 :: PWM devices:
Mon Sep 30 12:09:43 2024 :: - /sys/class/pwm/pwmchip0 with 2 timers
Mon Sep 30 12:09:43 2024 :: Listening on: /run/pwm/pyPWMd.sock

~/pyPWMd $ ./pyPWMd.py states
{'0': {0: None, 1: None}}

~/pyPWMd $ ./pyPWMd.py open 0 1
Mon Sep 30 12:12:22 2024 :: opened: /sys/class/pwm/pwmchip0/pwm1

~/pyPWMd $ ./pyPWMd.py states
{'0': {0: None, 1: [0, 0, 0, 0, '/sys/class/pwm/pwmchip0/pwm1']}}

~/pyPWMd $ ./pyPWMd.py set 0 1 1 10000 5000 0
Mon Sep 30 12:13:12 2024 :: set: /sys/class/pwm/pwmchip0/pwm1 = [1, 10000, 5000, 0]

~/pyPWMd $ ./pyPWMd.py states
{'0': {0: None, 1: [1, 10000, 5000, 0, '/sys/class/pwm/pwmchip0/pwm1']}}

~/pyPWMd $ kill 5994
[1]+  Terminated              sudo ./pyPWMd.py server
```
