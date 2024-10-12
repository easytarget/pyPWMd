# Python PWM Timer Control Daemon

Hardware based **P**ulse **W**idth **M**odulation ([PWM](https://learn.sparkfun.com/tutorials/pulse-width-modulation/all)) is a common feature of modern Single Board Computers.

The chipsets on these boards can produce very precice PWM signals using onboard timers, typically there are a number of timers which are then assigned to specific GPIO lines. Many have a GPIO connector based on the 'standard' set by the Raspberry Pi.

Sometimes PWM timers are used internally on the board to drive status LED's, LCD panel illumination and other board features. But they can also be used to control external devices such as LED strips, Servos and Heaters via the gpio connector pins.

## Hardware PWM in linux

PWM control in linux is provided by a generic API which is implemented in kernel drivers by device manufacturers. The Device Tree and pinctl are then used to enable PWM timers and map them onto GPIO pins.

The PWM Timers are controlled [via the API](https://www.kernel.org/doc/html/latest/driver-api/pwm.html), and the `/sys/class/pwm` tree.
- Individual GPIO pins are muxed (mapped) to the timers, this is done via device tree overlays.
- Generally there is a limited set of mappings available.

This is highly device dependent, and this guide does not attempt to cover the hardware and software aspects of identifying and mapping the pins.
  - For the MangoPI MQ Pro I have a guide here: https://github.com/easytarget/MQ-Pro-IO
  - A lot of the 'custom device tree' [building and installing](https://github.com/easytarget/MQ-Pro-IO/blob/main/build-trees/README.md) information in that guide is generic for any modern SBC running recent Linux versions.
  - On the Raspberry Pi there are standard Device Tree Overlays you can apply provided with Raspi OS, eg: https://raspberrypi.stackexchange.com/a/143644

### The Issue: By default *only* the root user can control the PWM timers.

There is not (yet) a good generic solution for allowing userland (non-root) access to the PWM timer devices; controlling them as the root user is straightforward (see the API doc), but ordinary users have no permission to access the tree.
- On Raspberry PI's this is provided by the `raspi-gpio` package and `RPi.GPIO` python library.
- I have two non-Pi Single Board Computers based on risc-v. These have PWM lines and drivers available, but the Pi packages are specific to the Pi hardware and not compatible with my boards
- A 'generic' and device neutral approach is needed

## A Python based generic approach to providing Userland control of PWM timers in linux.

**pyPWMd** is a tool that can run a daemon process as root which controls the timers via the `/sys/class/pwm` tree and provides a simple socket based interface to the timers.

It also provides two clients for the daemon; a commandline interface and a python class.

I have tested this on my MangoPI MQ-Pro (Allwinner D1 risc-v) and a Raspberry Pi 3A. It will work on any system that correctly implements the Linux PWM API.

## Requirements
- python3 (3.7+)
- A recent and updated linux distro
- Timers enabled and mapped to a gpio pin via a device tree or overlay

## Timer control
The PWM timers are arranged by chip number, then timer number.

By default timers do not have a control node open. Before you can read or write timer properties the node must be opened (eg created at `/sys/class/pwm/pwmchip<chip#>/pwm<timer#>`). When control is no longer needed the node can be closed again.

Once a node is open you can read and set properties; for each timer there are four (integer) values:
* **enable** : Enable/disable the PWM signal (read/write).
  * 0 = disabled, 1 - enabled
* **period** : The total period of the PWM signal (read/write).
  * Value is in nanoseconds and is the sum of the active and inactive time of the PWM.
* **duty_cycle** : The active time of the PWM signal (read/write).
  * Value is in nanoseconds and must be less than or equal to the period.
* **polarity** : Changes the polarity of the PWM signal (read/write).
  * Value is an integer. 0 for “normal” or 1 for “inversed”.

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
  * Returns the *version*, *pid*, *uid*, *gid* and *sysfs root path* of the server

## Installing

### Standalone server for testing or one-off use
Start: The following example is from a Raspberry Pi 3A with 2 pwm timers.
```console
$ git clone https://github.com/easytarget/pyPWMd.git
$ cd pyPWMd
$ sudo mkdir -p /run/pwm && sudo chmod 755 /run/pwm
$ sudo ./pyPWMd.py server --verbose &
[1] 431460
Starting Python PWM server v0.1
Mon Sep 30 12:09:43 2024 :: Server init
Mon Sep 30 12:09:43 2024 :: Scanning for pwm timers
Mon Sep 30 12:09:43 2024 :: PWM devices:
Mon Sep 30 12:09:43 2024 :: - /sys/class/pwm/pwmchip0 with 2 timers
Mon Sep 30 12:09:43 2024 :: Listening on: /run/pwm/pyPWMd.socket
$ sudo chmod 777 /run/pwm/pyPWMd.socket
$ alias pwmtimerctl=`pwd`/pyPWMd.py
```
This will put the server into a background process, the `--verbose` optin will show a lot of useful debugging info and this can get intrusive. Omit it as needed.

Once the server is running you can use `pwmtimerctl` on the commandline, or `import pyPWMd` in python to work with the client. See below.

Stop: Once you are done with the server; terminate it by killing the PID
```console
$ pwmtimerctl info
['0.1', 431460, 0, 0, '/sys/class/pwm']
$ kill 431460
[1]+  Terminated              sudo ./pyPWMd.py server
# (could also do kill %1 since the server is backgrounded as #1)
$ sudo rmdir /run/pwm
$ unalias pwmtimerctl
```

### Systemd service (Daemon)
The `pyPWMd.service` file will create a pwm server instance at `/run/pwm/pyPWMd.socket` accessible to all users in the group `pwm`.

Create a 'pwm' system group for users:
```console
$ sudo groupadd -K GID_MIN=100 -K GID_MAX=499 pwm
$ getent group pwm
pwm:x:115:
```
Add the required users to the `pwm` group
```console
$ sudo usermod -a -G pwm <username>
$ id <username>
uid=1000(<username>) gid=1000(<usergroup>) groups=1000(<usergroup>),...,115(pwm)
```
After being added the users need to log out then back in for the new group to be available to them.

Clone the pyPWMd repo to the root home directory, link the `.service` file into `/etc/systemd/service/`, register the service with systemd then enable+start the service:
```console
$ sudo git clone https://github.com/easytarget/pyPWMd.git /usr/local/lib/pyPWMd
$ sudo ln -s /usr/local/lib/pyPWMd/pyPWMd.service /etc/systemd/system/
$ sudo systemctl daemon-reload
$ sudo systemctl enable --now pyPWMd.service
```
The service should now be running at `/run/pwm/pyPWMd.socket`: Check with `$ sudo systemctl status pyPWMd.service`, logfiles will be generated in `/var/log/pwm/`.

### Commandline Client: `pwmtimerctl`
Link `pyPWMd.py` as `/usr/local/bin/pwmtimerctl`
```console
$ sudo ln -s /usr/local/lib/pyPWMd/pyPWMd.py /usr/local/bin/pwmtimerctl
```
Test!
* Make sure you have a **new** user login shell, *with the user in the `pwm` group!*
```console
$ pwmtimerctl info
```

### A little note on security..
The daemon process runs as the root user, and is written by 'some bloke on the internet' in python. Be sure you trust it before using it..
- You can look at the code, of course. It only reads/writes to files in the /sys/class/pwm folder.
- Python is considered quite secure, and this tool only uses libraries from the python standard library (no random libraries from PiPy etc..)
- It uses a standard python [multiprocessing comms socket](https://docs.python.org/3/library/multiprocessing.html#module-multiprocessing.connection) for communication
  - By default a local unix filesystem socket is used, permissions can be set on this to allow access via groups.
  - There is an authentication mechanism on the socket, by default the api version string is used as the token. This could be modified to provide additional control.

## Use

### Commandline client
A simple example from a Raspberry Pi (2 pwm timers):
* Also see the the shell demo [client-demo.sh](./client-demo.sh).

Start a server If needed (see above)

Then control the PWM timers with:
```console
$ pwmtimerctl states
{'0': {0: None, 1: None}}
$ pwmtimerctl open 0 1
Mon Sep 30 12:12:22 2024 :: opened: /sys/class/pwm/pwmchip0/pwm1
$ pwmtimerctl states
{'0': {0: None, 1: (0, (0, 0), 0)}}
$ pwmtimerctl f2p 100000 0.5
(10000, 5000)
$ pwmtimerctl set 0 1 1 10000 5000 0
Mon Sep 30 12:13:12 2024 :: set: /sys/class/pwm/pwmchip0/pwm1 = [1, 10000, 5000, 0]
$ pwmtimerctl states
{'0': {0: None, 1: (1, (10000, 5000), 0)}}
```
Run `pwmtimerctl help` to see the full command set and syntax.

## Python Client
You need to import the library, then create a `pypwm_client()` object. This will provide:
```console
methods:
-------
pypwm_client.open(chip, timer):
      Returns 'True' if the node was successfully opened, or already open
      or an error string on failure

pypwm_client.close(chip, timer):
      Returns 'True' if the close was successful or node already closed
      or an error string on failure

pypwm_client.get(chip, timer):
      Returns the timer properties as a tuple, or an error string

pypwm_client.set(chip, timer, enable=None, pwm=None, polarity=None):
      'enable' is a bool, 0 or 1
      'pwm' is a tuple:
          pwm(period, duty_cycle)
      'polarity' is 0 for 'normal' or 1 for 'inversed'.
      The values are optional:
      - If omitted the current value will be used
      - This can cause errors, eg if 'enable' is set while 'pwm' is
        still at it's default, unitialised, (0,0) setting
      Returns 'True' on success, an error string on failure

pypwm_client.states():
      Reads the /sys/class/pwm/ tree and returns the state map as a dict

pypwm_client.f2p(freq, power):
      'freq' is an integer
      'power' is a float (0-1) giving the PWM 'on' time percentage
      Returns a tuple (period, duty):
        'period' and 'duty' are integers

pypwm_client.p2f(period, duty):
      'period' and 'duty' are integers
      Returns a tuple (freq, power)
        'freq' is an integer and 'power' is a float (max 3 decimals)

pypwm_client.info():
      Returns a list with server details

Properties:
-----------
pypwm_client.connected
      A bool, giving the last known client-server connection status
```

### python client install
Create a softlink to the library in your project folder (or clone the whole repo there)
```console
$ ln -s /usr/local/lib/pyPWMd/pyPWMd.py .
```

### python client example
Here is an example of using the library on my MQ-Pro (8 pwm timers):
* Also see the demo [client-demo.py](./client-demo.py).
```python
Python 3.12.3 (main, Sep 11 2024, 14:17:37) [GCC 13.2.0] on linux
Type "help", "copyright", "credits" or "license" for more information.
>>> import pyPWMd
>>> p = pyPWMd.pypwm_client()
>>> p.states()
{'0': {0: None, 1: None, 2: None, 3: None, 4: None, 5: None, 6: None, 7: None}}
>>> p.open(0,2)
True
>>> p.get(0,2)
(0, (1000, 1000), 0)
>>> p.set(0, 2, 0, p.f2p(5000, 0.5), 0)
True
>>> p.states()
{'0': {0: None, 1: None, 2: (0, (200000, 100000), 0), 3: None, 4: None, 5: None, 6: None, 7: None}}
>>> p.close(0,2)
True
```

## Upgrading
todo.. easy. just cd.. then git pull, then restart service

-----------------------------
# Commandline help reference
```console
$ ./pyPWMd.py help
Usage: v1.0
    pyPWMd.py command <options> [--verbose]
    where 'command' is one of:
        server [<logfile>]
        states
        open <chip> <timer>
        close <chip> <timer>
        set <chip> <timer> <enable> <period> <duty_cycle> <polarity>
        get <chip> <timer>

    'server' starts a server on /run/pwm/pyPWMd.socket.
    - needs to run as root, see the main documentation for more
    - an optional logfile or log directory can be supplied

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
    - Exported entries are a list of the parameters (see 'get', below)
      followed by the timer's node path in the /sys/class/pwm/ tree

    'get' returns 'None' if the timer is not exported, otherwise it will
    return four numeric values: <enable> <period> <duty_cycle> <polarity>

    'set' will change an exported nodes settings with the supplied values.
    - enable and polarity are boolean values, 0 or 1
    - Attempting to set the enable or polarity states will fail unless
      a valid period (non zero) is supplied or was previously set
    - The duty_cycle cannot exceed the period
    - Set operations are logged to the console, but not to disk logfiles

    'f2p' converts two arguments, a frequency + power_ratio to a
    period + duty_cycle as used by the 'set' command above.
    - Frequency is an interger, in Hz
    - Power_ratio is ao float, 0-1, giving the % 'on time' for the signal.
    - Returns the period and duty_cycle in nanoseconds

    'p2f' is the reverse of 'f2p' above, giving a frequency + power_ratio
    from the period + duty_cycle values returned by the 'get' or 'states' commands.
    - Period and duration arguments are integers in nanoseconds.
    - Returns the frequency in Hz and power_ratio as a float between 0 and 1

    Options (currently only applies to server):
    --verbose enables logging of 'set' events

    Homepage: https://github.com/easytarget/pyPWMd
```
