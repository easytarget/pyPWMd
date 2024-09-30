# Python PWM timer control daemon

PWM control in linux is provided by a generic API which is implemented in pwm drivers by device manufacturers. The Device Tree and pinctl are then used to enable PWM timers and map them onto GPIO pins.

The **PWM Timers** are then controlled [via the API](https://www.kernel.org/doc/html/latest/driver-api/pwm.html), and the `/sys/class/pwm` tree.
- Individual GPIO pins are muxed (mapped) to the timers, this is done via device tree overlays.
  - Generally there is a limited set of mappings available.

This is highly device dependent, and this guide does not attempt to cover the hardware and software aspects of identifying and mapping the pins.
  - For the MangoPI MQ Pro I have a guide here: https://github.com/easytarget/MQ-Pro-IO
  - A lot of the 'custom device tree' [building and installing](https://github.com/easytarget/MQ-Pro-IO/blob/main/build-trees/README.md) information in that guide is generic for any modern SBC running recent Linux versions.
  - On the Raspberry Pi there are standard Device Tree Overlays you can apply provided with Raspi OS, eg: https://raspberrypi.stackexchange.com/a/143644

There is not (yet) a good generic solution for allowing non-root users to access the PWM timer devices, controlling them as the root user is straightforward (see the API doc), but control from a non-root user is trickier.
- On Raspberry PI's this is provided by the `raspi-gpio` package and `RPi.GPIO` python library.
- I have a non-Pi Single Board COmputer based on risc-v, and the Pi packages are not compatible
  - https://github.com/easytarget/MQ-Pro-IO

## A Python based approach to providing Userland control of PWM timers in linux.

**pyPWMd** is a tool that can run a daemon process as root, which controlls the timers via the `/sys/class/pwm` tree and provides a simple socket based interface to the timers.

It also provides two clients for the daemon; a commandline interface and a python class.

### Install
Clone this repo to a folder:
```console
~ $ git clone https://github.com/easytarget/pyPWMd.git
...
~ $ cd pyPWMd
```
#### Requirements
- python3 (3.7+)
- A recent and updated linux distro
- Timers enabled and mapped to a gpio pin

## Use

The PWM timers are arranged by chip number, then timer number.

By default timers do not have a control node open, before you can read or write timer properties the node must be opened (eg created at `/sys/class/pwm/pwmchip<chip#>/pwm<timer#>`). When control is no longer needed the node can be closed again.

Once a node is open you can read and set it's properties; for each timer there are four (integer) values:
* **enable** : Enable/disable the PWM signal (read/write).
  * 0 = disabled, 1 - enabled
* **period** : The total period of the PWM signal (read/write).
  * Value is in nanoseconds and is the sum of the active and inactive time of the PWM.
* **duty_cycle** : The active time of the PWM signal (read/write).
  * Value is in nanoseconds and must be less than or equal to the period.
* **polarity** : Changes the polarity of the PWM signal (read/write).
  * Value is the string “normal” or “inversed”.

The pyPWMd server is a front-end to the (legacy) sysFS interface; the kernel.org PWM API describes this in more detail:
https://www.kernel.org/doc/html/latest/driver-api/pwm.html#using-pwms-with-the-sysfs-interface

There are five basic commands provided by the clients;
* `open <chip> <timer>`
* `close <chip> <timer>`
  * Open and Close timer nodes
* `get <chip> <timer>`
  * Gets the timer properties
* `set <chip> <timer> <enable> <period> <duty_cycle> <polarity>`
  * Sets the properties of the timer
  * Note that *enable* and *polarity* cannot be set unless the *period* is valid (non-zero)
* `states`
  * Lists the *open*/*closed* state of all available PWM timers, if a timer is open it's properties are returned

Additionally they have some helpers
* `f2p` and `p2f`
  * Converts a *frequency* & *power* (pwm ratio) pair of values to *period* and *duty_cycle*
  * And vice versa.
* `info`
  * Returns the version, pid, uid, gid and sysfs root path of the server

### daemon (server) process
```console
~/pyPWMd $ sudo ./pyPWMd.py server
Starting Python PWM server v0.1

Mon Sep 30 12:09:43 2024 :: Server init
Mon Sep 30 12:09:43 2024 :: Scanning for pwm timers
Mon Sep 30 12:09:43 2024 :: PWM devices:
Mon Sep 30 12:09:43 2024 :: - /sys/class/pwm/pwmchip0 with 2 timers
Mon Sep 30 12:09:43 2024 :: Listening on: /run/pwm/pyPWMd.sock
```
This needs to be run as root, in the background. There are many ways of doing this:
- In the example below I simply background the daemon process
  - TODO: see if I can make the process background itself? research needed.
- When testing I tend to run it in a detached [`screen`](https://www.gnu.org/software/screen/manual/screen.html) session, so I can reattach and see logs/errors as needed.
- TODO: document how to run as a systemd service; in principle easy but I'd like to set access via a `pwm` group as part of this.

#### A little note on security..
The daemon process runs as the root user, and is written by 'some bloke on the internet' in python. Be sure you trust it before using it..
- You can look at the code, of course. It only reads/writes to files in the /sys/class/pwm folder.
- Python is considered quite secure, and this tool only uses libraries from the python standard library (no random libraries from PiPy etc..)
- There is a simple authentication mechanism on the socket, the athentication key can be changed from the default to provide access control.
- By default a unix filesystem socket is used, permissions can be set on this to allow access via groups.

This is a standard python [multiprocessing comms socket](https://docs.python.org/3/library/multiprocessing.html#module-multiprocessing.connection), you can change the socket definition and allow access via the network, be careful doing this..

### Commandline client
The *pyPWMd.py* script can be run on the commandline to set and read the timers.

Here is a simple example: see also the shell demo [client-demo.**sh**](./client-demo.sh) and the output from `pyPWMd.py help` (see below).

```console
~/pyPWMd $ sudo ./pyPWMd.py server --verbose &
[1] 5994
~/pyPWMd $ Starting Python PWM server v0.1

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
Run `pyPWMd.py help` to see the full command set and syntax.

## Python client
ToDo

# Reference

## Commandline:
```
Usage: v0.1
    pyPWMd.py command <options>  [--quiet]|[--verbose]
    where 'command' is one of:
        server
        states
        open <chip> <timer>
        close <chip> <timer>
        set <chip> <timer> <enable> <period> <duty_cycle> <polarity>
        get <chip> <timer>

    'server' starts a server on /run/pwm/pyPWMd.sock.
    - needs to run as root, see the main documentation for more.

    All other commands are sent to the server, all arguments are mandatory

    <chip> and <timer> are integers
        - PWM timers are organised by chip, then timer index on the chip
    <enable> is a boolean, 0 or 1, output is undefined when disabled(0)
    <period> is an integer, the total period of pwm cycle (nanoseconds)
    <duty_cycle> is an integer, the pulse time within each cycle (nanoseconds)
    <polarity> defines the initial state (high/low) at start of pulse

    These are:

    'open' and 'close' export and unexport timer nodes.
    - To access a timer's status and settings the timer node must first
      be exported
    - Timers continue to run even when unexported

    'states' lists the available pwm chips, timers, and their status.
    - If a node entry is unexported it is shown as 'None'
    - Exported entries are a list of the parameters (see below) followed
      by the timer's node path in the /sys tree

    'get' returns nothing if the timer is not exported, otherwise it will
    return four numeric values, these are (in sequence):

    'set' will change an exported nodes settings with the supplied values.
    - enable and polarity are boolean values, 0 or 1
    - Attempting to set the enable or polarity states will fail unless
      a valid period (non zero) is supplied or was previously set
    - The duty_cycle cannot exceed the period
    - Set operations are logged to the console, but not to disk logfiles

    Currently you can only supply the pwm 'value' in nanoseconds; ie: the
    overall time for each pulse cycle, and the active time within that pulse.
    - ToDo: provide helper functions to convert 'frequency/fraction' values
      into 'period/duty_cycle' ones, anv vice-versa

    Options (only apply to server):
    --quiet supresses the console log (overrides --verbose)
    --verbose enables logging of 'set' events
```

## Python lib
ToDo
