#!/usr/bin/python3
'''
  PWM server daemon
'''

from time import ctime
from sys import argv, exit
from os import path, remove, makedirs, chown, chmod, getuid, getgid, getpid
from glob import glob
from re import findall
from multiprocessing.connection import Listener, Client
from multiprocessing import AuthenticationError
import atexit

# Some housekeeping
name = path.basename(__file__)
version = '1.0'

# Define the socket
_sockdir = '/run/pwm'
socket = _sockdir + '/pyPWMd.socket'
# By default use version string as socket auth token, prevents API fails.
auth = bytes(version.encode('utf-8'))

# pwm API specifies nanoseconds as the base period unit.
basefreq = 1000000000

class pypwm_server:
    '''
        PWM node control daemon (server)
        Needs root..
    '''

    def __init__(self, logfile=None, verbose=False):
        self.logfile = logfile
        self._verbose = verbose
        self.sock = socket
        self.running = False
        self._sysbase  = '/sys/class/pwm'
        self._chipbase = 'pwmchip'

        # sensible defaults for pwm and servo
        self.pfreq = 1000   # pwm default, (float, Hz)
        self.sint = 0.02    # servo default pulse interval (float, seconds)
        self.smin = 0.0006  # servo default min pulse (float, seconds)
        self.smax = 0.0023  # servo default max pulse (float, seconds)

        # initialise and check logfile? disable file logging if n/a
        self._log('')
        self._log('PWM server v{} init'.format(version))
        if logfile is not None:
            self._log('Logging to: {}{}'.format(logfile,
                ' (verbose)' if verbose else ''))

        # Do initial scan for devices
        self._log('Scanning {} for pwm timers'.format(self._sysbase))
        chips = self._chipscan()
        if len(chips) == 0:
            self._log('Warning: No PWM devices available!')
        else:
            self._log('PWM devices:')
            for chip in chips.keys():
                self._log('- {} with {} timers'.format(chip, chips[chip]))

    def _log(self, string):
        out = log = ''
        for line in string.strip().split('\n'):
            out += '{}: {}\n'.format(name, line)
            log += '{} :: {}\n'.format(ctime(), line)
        print(out.strip(), flush=True)
        if self.logfile is not None:
            with open(self.logfile,'a') as l:
                l.write(log)
        return string

    def _chipscan(self):
        #returns a numerically sorted dict with <path>:<number of pwms>
        base = '{}/{}'.format(self._sysbase,self._chipbase)
        chiplist = glob('{}*'.format(base))
        chiplist = sorted(chiplist, key=lambda x:float(findall('(\\d+)',x)[0]))
        chips = {}
        for chip in chiplist:
            with open(chip + '/npwm','r') as npwm:
                chips[chip] = int(npwm.read())
        return chips

    def _getprop(self, node):
        with open(node, 'r') as file:
           value = file.read().strip()
        return value

    def _gettimer(self, node):
        enable = int(self._getprop(node + '/enable'))
        period = int(self._getprop(node + '/period'))
        duty = int(self._getprop(node + '/duty_cycle'))
        polarity = str(self._getprop(node + '/polarity'))
        return enable, period, duty, polarity

    def _info(self,client):
        self._log('info: client {} sent info request'.format(client))
        return version, getpid(), getuid(), getgid(), self._sysbase

    def _states(self):
        pwms = {}
        chips = self._chipscan()
        for chip in chips.keys():
            c = chip[len(self._sysbase + self._chipbase)+1:]
            pwms[c] = {}
            for timer in range(chips[chip]):
                node = '{}/pwm{}'.format(chip, timer)
                pwms[c][timer] = self._gettimer(node) if path.exists(node) else None
        return pwms

    def _get(self, chip, timer):
        node = '{}/{}{}/pwm{}'.format(self._sysbase,
            self._chipbase, chip, timer)
        if not path.exists(node):
            return None
        return tuple(self._gettimer(node))

    def _set(self, chip, timer, enable, period, duty):
        def setprop(n, p, v, r = True):
            # Set an individual node+property with error trap.
            try:
                with open(n + '/' + p, 'w') as f:
                    f.write(str(v))
            except (FileNotFoundError, OSError) as e:
                if r:
                    self._log('error: failed to set {}/{} :: {}'.format(n, p, repr(e)))
                return False
            return True

        # Set properties for a timer
        node = '{}/{}{}/pwm{}'.format(self._sysbase, self._chipbase, chip, timer)
        if not path.exists(node):
            return self._log('error: attempt to set unexported timer {}'.format(node))
        if not enable:
            return setprop(node, 'enable', 0)
        if duty > period:
            return self._log('error: cannot set duty={} greater than period={}'.format(duty, period))
        state = list(self._gettimer(node))
        if state[3] == 'inversed':  # allow for inversion
            duty = period - duty
        if state[1] != period:  # period
            # always set duty=0 before frequency is changed (may fail on initial access)
            setprop(node, 'duty_cycle', 0, False)
            state[2] = 0
            setprop(node, 'period', period)
        if state[2] != duty:  # duty
            setprop(node, 'duty_cycle', duty)
        if state[0] != 1:  # enable
            setprop(node, 'enable', 1)
        # do not log to disk unless requested (fills disk and causes extra load)
        if self._verbose:
            self._log('info: set {} = {}'.format(node, list(self._gettimer(node))))
        return True

    def _open(self, chip, timer):
        node = '{}/{}{}'.format(self._sysbase, self._chipbase, chip)
        if path.exists(node + '/pwm' + str(timer)):
            return True
        try:
            with open(node + '/export', 'w') as export:
                export.write(str(timer))
        except (FileNotFoundError, OSError) as e:
            return self._log('error: cannot access {}/export :: {}'.format(node, repr(e)))
        if not path.exists(node + '/pwm' + str(timer)):
            return self._log('error: failed to create {}/pwm'.format(node))
        else:
            self._log('info: opened: {}/pwm{}'.format(node, timer))
            return True

    def _close(self, chip, timer):
        node = '{}/{}{}'.format(self._sysbase, self._chipbase, chip)
        if not path.exists(node + '/pwm' + str(timer)):
            return True
        try:
            with open(node + '/unexport', 'w') as unexport:
                unexport.write(str(timer))
        except (FileNotFoundError, OSError) as e:
            return self._log('error: cannot access {}/unexport :: {}'.format(node, repr(e)))
        if path.exists(node + '/pwm' + str(timer)):
            return self._log('error: failed to destroy {}/pwm'.format(node))
        else:
            self._log('info: closed: {}/pwm{}'.format(node, timer))
            return True

    def _f2p(self, freq, ratio):
        if freq == 0:  # div by zero.
            return 0, 0
        period = int(basefreq / freq)
        duty = int(period * ratio)
        return period, duty

    def _p2f(self, period, duty):
        if period == 0:  # div by zero.
            return 0, 0
        freq = round(basefreq / period, 3)
        ratio = round(duty / period, 3)
        return freq, ratio

    def _pwm(self, chip, timer, ratio = None):
        if ratio is None:
            state = self._get(chip, timer)
            if state is None or state[0] == 0:
                return None
            else:
                f, r = self._p2f(state[1],state[2])
                return round(1 - r, 3) if state[3] == 'inversed' else r, f
        ratio = float(max(0, min(1, ratio)))
        return self._set(chip, timer, 1, *self._f2p(self.pfreq, ratio))

    def _pwmfreq(self, freq = None):
        if freq is not None:
            self.pfreq = freq
            if self._verbose:
                self._log('info: pwm default frequency set to {}'.format(freq))
        return self.pfreq

    def _servo(self, chip, timer, ratio):
        ratio = float(max(0, min(1, ratio)))
        value = self.smin + ((self.smax - self.smin) * ratio)
        period = int(self.sint * basefreq)
        duty_cycle = int(value * basefreq)
        return self._set(chip, timer, 1, period, duty_cycle)

    def _servoset(self, minpulse=None, maxpulse=None, interval = None):
        smin = self.smin if minpulse is None else float(minpulse)
        smax = self.smax if maxpulse is None else float(maxpulse)
        sint = self.sint if interval is None else float(interval)
        if smax > sint:
            return 'error: maxpulse ({}) cannot be greater than interval ({})'.format(smax, sint)
        if smin > smax:
            return 'error: minpulse ({}) cannot be greater than maxpulse ({})'.format(smin, smax)
        self.smin, self.smax, self.sint = smin, smax, sint
        if self._verbose:
            self._log('info: servo defaults set to {} {} {}'.format(smin, smax, sint))
        return self.smin, self.smax, self.sint

    def _disable(self, chip, timer):
        if self._verbose:
            self._log('info: disabling {} {}'.format(chip, timer))
        return self._set(chip, timer, 0, None, None)

    def server(self):
        # Clean any existing socket on startup (or error)
        if path.exists(socket):
            try:
                remove(socket)
            except Exception as e:
                print('Socket {} already exists and cannot be removed.'.format(socket))
                print(e)
                print('Cannot start, is another instance running?')
                return
        self._log('info: Starting server: pid: {}, uid: {}, gid: {}'.format(
            getpid(), getuid(), getgid()))
        try:
            with Listener(self.sock, authkey=auth) as listener:
                self._log('info: Listening on: ' + listener.address)
                # Now loop forever while listening and responding to socket
                self.running = True  # can be forced false to kill server
                try:
                    while self.running:
                        self._listen(listener)
                except Exception as e:
                    self.running = False
                    self._log('info: server exiting:\n{}'.format(e))
        except FileNotFoundError as e:
            self._log('error: failed to create socket at {}:\n{}'.format(self.sock,e))
        except Exception as e:
            self._log('error: failed to start server:\n{}'.format(e))

    def _listen(self,listener):
        try:
            with listener.accept() as conn:
                try:
                    recieved = conn.recv()
                except EOFError:
                    if self._verbose:
                        self._log('warning: null connection on socket')
                    return
                except Exception as e:
                    if self._verbose:
                        self._log('warning: recieve failure on socket:\n{}'.format(e))
                    return
                cmdline = recieved.strip().split(' ')
                #self._log('Recieved: {}'.format(cmdline))  # debug
                conn.send(self._process(cmdline))
        except AuthenticationError:
            if self._verbose:
                self._log('warning: authentication error on socket')
        except ConnectionResetError:
            if self._verbose:
                self._log('warning: connection reset on socket')
        except Exception as e:
            self._log('error: listner failed on socket:\n{}'.format(e))

    def _process(self, cmdline):
        # 'command':([possible argument lengths],[arguments that are floats])
        cmdset = {  'info':([1],[]), 'states':([0],[]),
                    'open':([2],[]), 'close':([2],[]),
                    'pwm':([2,3],[2]), 'pwmfreq':([0,1],[0]),
                    'servo':([3],[2]), 'servoset':([0,2,3],[0,1,2]),
                    'disable':([2],[]),}
        cmd = cmdline[0]
        args = [] if len(cmdline) == 1 else cmdline[1:]
        #print('{}({})'.format(cmd, '' if len(args) == 0 else ', '.join(args)))  # DEBUG
        if cmd not in cmdset.keys():
            err = 'client error: unknown command \'{}\''.format(cmd)
            return self._log(err) if self._verbose else err
        if len(args) not in cmdset[cmd][0]:
            err = 'client error: bad argument count {} for \'{}\''.format(len(cmdline)-1,cmd)
            return self._log(err) if self._verbose else err
        for i in range(len(args)):
            try:
                if i in cmdset[cmd][1]:
                    args[i] = float(args[i])
                else:
                    # wrapping int(float( allows us to specify values as '1e5' etc.
                    args[i] = int(float(args[i]))
            except:
                err = 'client error: incorrect argument \'{}\' for \'{}\''.format(args[i], cmd)
                return self._log(err) if self._verbose else err
        return getattr(self,'_' + cmd)(*args)

class pypwm_client:
    '''
        PWM node control client
    '''

    def __init__(self, sock=socket, verify=True, verbose=False):
        self._sock = sock
        self.verbose = verbose
        self.connected = None
        if verify:
            info = self.info()
            if info is None:
                return
            elif info[0] != version:
                self._print('{}: warning: version missmatch to server running at {}'
                    .format(__name__, self._sock))

    def _print(self, msg):
        if self.verbose:
            print(msg)
        return msg

    def _send(self, cmdline):
        if not path.exists(self._sock):
            self._print('{}: error: no server at {}'.format(__name__, self._sock))
            self.connected = False
            return None
        try:
            with Client(self._sock, authkey=auth) as conn:
                conn.send(cmdline)
                ret = conn.recv()
                self.connected = True
                return ret
        except AuthenticationError as e:
            self._print('{}: error: authentication failed: {}'
                .format(__name__, e))
        except Exception as e:
            self._print('{}: error: socket communications failed: {}\n{}'
                .format(__name__, self._sock, e))
        self.connected = False
        return None

    def info(self):
        return self._send('info {}'.format(getpid()))

    def states(self):
        states = self._send('states')
        return states

    def open(self, chip, timer):
        return self._send('open {} {}'.format(chip, timer))

    def close(self, chip, timer):
        return self._send('close {} {}'.format(chip, timer))

    def pwm(self, chip, timer, ratio = None):
        return self._send('pwm {} {} {}'.format(chip, timer, '' if ratio is None else ratio))

    def pwmfreq(self, freq = None):
        return self._send('pwmfreq {}'.format('' if freq is None else freq))

    def servo(self, chip, timer, ratio):
        return self._send('servo {} {} {}'.format(chip, timer, ratio))

    def servoset(self, minpulse=None, maxpulse=None, interval = None):
        cur = self._send('servoset')
        if minpulse is None and maxpulse is None and interval is None:
            return cur
        minpulse = cur[0] if minpulse is None else minpulse
        maxpulse = cur[1] if maxpulse is None else maxpulse
        interval = cur[2] if interval is None else interval
        return self._send('servoset {} {} {}'.format(minpulse, maxpulse, interval))

    def disable(self, chip, timer):
        return self._send('disable {} {}'.format(chip, timer))


if __name__ == "__main__":
    '''
        Commandline Client
    '''

    usage = '''Usage: v{0}
    {1} command <options>
    where 'command' is one of:
        server [<logfile>] [--verbose]
        states
        open <chip> <timer>
        close <chip> <timer>
        pwm <chip> <timer> [<pwm-ratio>]
        pwmfreq [<frequency>]
        servo <chip> <timer> <servo-ratio>
        servoset [<min-period> <max-period> [<interval>]]
        disable <chip> <timer>
        info

    <chip> and <timer> are integers.
    - PWM timers are organised by chip, then timer index on the chip.

    'server' starts a server on {2}.
    - needs to run as root, see the main documentation for more.
    - an optional logfile or log directory can be supplied and
      adding the option '--verbose' enables extended logging.

    All other commands are sent to the server.

    'states' lists the available pwm chips, timers, and their status.
    - If a node entry is unexported it is shown as 'None'.
    - Exported entries are a list of the current parameters;
      enabled, period, duty_cycle, polarity. Followed by the timer's
      node path in the /sys/class/pwm/ tree, as per kernel pwm api docs.

    'open' and 'close' export and unexport timer nodes.
    - To access a timer's status and settings the timer node must first
      be exported.
    - Timers continue to run even when unexported.

    'pwm' enables and sets the timer to a pwm ratio.
    - The ratio is a float between 0 and 1 giving the 'on' time ratio.
    - The frequency is taken from the current pwmfreq setting.
    - If called with no ratio specified it will return the current
      (frequency, ratio) read from the pin status.

    'pwmfreq' shows or sets the default PWM frequency in Hz.
    - Default is 1000 (1KHz).
    - If called with no argument it returns the current setting.

    'servo' enables and sets the timer to output servo pulses.
    - The position is a float between 0 (min) and 1 (max) positions.

    'servoset' shows or sets the servo timings and interval.
    - The first two arguments are the minimum and maximum pulse width
      times for the servo in seconds (floats).
    - The third (optional) argument is the interval between pulses in
      seconds (float).
    - Default is 0.6ms and 2.3ms for minimum and maximum pulse width,
      and 20ms for the interval. These are typical figures for small
      hobby servo motors. Check datasheets and test for your motors as needed.
    - If called with no argument it returns the current timings in seconds.

    'disable' immediately disables the timer.
    - This should be used as needed with the servo commands to stop the servo
      after it has moved to position to avoid hunting and jittering.
    - The kernel pwm api does not specify the output when disabled, typically
      it defaults to high-impedance but you should test this.

    'info' returns a tuple with server details.
      ('version', pid, uid, gid, '<syspath>')

    Homepage: https://github.com/easytarget/pyPWMd
    '''.format(version, name, socket).strip()

    def runserver(logfile, verbose):
        '''
          Init and run a server,
        '''
        def cleanup(p):
            try:  # try to ensure the socket is removed...
                remove(socket)
            except:  # ...but not too hard.
                pass
            p._log('Server exiting')

        if logfile is not None:
            if path.isdir(logfile):
                logfile += '/pyPWMd.log'
        print('Starting Python PWM server v{}'.format(version))
        p = pypwm_server(logfile, verbose)
        atexit.register(cleanup,p)
        p.server()

    def runcommand(cmdline):
        '''
          Pass the the command to server
        '''
        if not path.exists(socket):
            return('error: no pwm server at \'{}\''.format(socket), 1)
        try:
            with Client(socket, authkey=auth) as conn:
                conn.send(' '.join(cmdline))
                reply = conn.recv()
        except AuthenticationError as e:
            reply = 'error: authentication failed: {}'.format(e)
        except Exception as e:
            reply = 'error: socket communications failed:\n{}'.format(e)
        if reply is None:
            state = 1
        elif type(reply) == str and 'error' in reply.lower():
            state = 1
        else:
            state = 0
        return reply, state

    # Parse Arguments and take appropriate action
    if len(argv) == 1:
        print('{}: No command specified, try: {} help'.format(name, argv[0]))
        exit(2)

    try:
        l = argv.index('--verbose')
    except ValueError:
        logall = False
    else:
        logall = True
        argv.pop(l)

    # Command is always first argument
    command = argv[1]
    if command == 'info':
        argv.append(str(getpid()))
    if command in ['h', 'help', 'Help', '-h', '--help', 'usage']:
        print(usage)
    elif command == 'server':
        logfile = None if len(argv) < 3 else argv[2]
        runserver(logfile, logall)
    else:
        response, status = runcommand(argv[1:])
        if response != True:
            print(response)
        exit(status)
    exit(0)
