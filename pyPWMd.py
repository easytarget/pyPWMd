#!/usr/bin/python3
'''
  PWM server daemon
'''

from time import ctime
from sys import argv, exit
from os import path, remove, makedirs, chown, chmod, getuid, getgid, getpid
from glob import glob
from multiprocessing.connection import Listener, Client
from multiprocessing import AuthenticationError
from json import dumps, loads
import atexit

# Some housekeeping
name = path.basename(__file__)
version = '0.2'

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
        self._polarities = ['normal', 'inversed']

        # initialise and check logfile? disable file logging if n/a
        self._log('')
        self._log('PWM server v{} starting'.format(version))
        if logfile is not None:
            self._log('Logging to: {}{}'.format(logfile,
                ' (verbose)' if verbose else ''))
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
        #returns a dict with <path>:<number of pwms>
        base = '{}/{}'.format(self._sysbase,self._chipbase)
        chips = {}
        for chip in glob('{}*'.format(base)):
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
        polarity = self._polarities.index(self._getprop(node + '/polarity'))
        return enable, period, duty, polarity

    def _info(self,client):
        self._log('client {} sent info request'.format(client))
        return [version, getpid(), getuid(), getgid(), self._sysbase]

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

    def _set(self, chip, timer, enable, period, duty, polarity):
        # Set properties for a timer

        def setprop(n, p, v):
            # Set an individual node+property with error trap.
            try:
                with open(n + '/' + p, 'w') as f:
                    f.write(str(v))
            except (FileNotFoundError, OSError) as e:
                self._log('error: failed to set {}/{} :: {}'.format(n, p, repr(e)))

        node = '{}/{}{}/pwm{}'.format(self._sysbase, self._chipbase, chip, timer)
        if not path.exists(node):
            return self._log('error: attempt to set unexported timer {}'.format(node))
        state = list(self._gettimer(node))
        if period is not None:
            if duty > period:
                return self._log('error: cannot set duty={} greater than period={}'.format(duty, period))
            if state[1] != period:
                if state[1] > 0:
                    # if period already has a value, set duty=0 before it is changed
                    setprop(node, 'duty_cycle', 0)
                    state[2] = 0
                setprop(node, 'period', period)
            if state[2] != duty:
                setprop(node, 'duty_cycle', duty)
        if polarity is not None:
            if state[3] != polarity:
                setprop(node, 'polarity', self._polarities[polarity])
        if enable is not None:
            if state[0] != enable:
                setprop(node, 'enable', enable)
        # do not log to disk unless requested (fills disk and causes extra load)
        if self._verbose:
            self._log('set: {} = {} '.format(node, list(self._gettimer(node))))
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
            self._log('opened: {}/pwm{}'.format(node, timer))
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
            self._log('closed: {}/pwm{}'.format(node, timer))
            return True

    def _f2p(self, freq, power):
        period = int(basefreq / freq)
        duty = int(period * power)
        return period, duty

    def _p2f(self, period, duty):
        freq = round(basefreq / period, 3)
        power = round(duty / period, 3)
        return freq, power

    def server(self):
        self._log('Starting server: pid: {}, uid: {}, gid: {}'.format(
            getpid(), getuid(), getgid()))
        try:
            with Listener(self.sock, authkey=auth) as listener:
                self._log('Listening on: ' + listener.address)
                # Now loop forever while listening and responding to socket
                self.running = True
                try:
                    while self.running:
                        self.running = self._listen(listener)
                except Exception as e:
                    self._log('exiting:\n{}'.format(e))
                    self.running = False
        except Exception as e:
            self._log('error: failed to start server\n{}'.format(e))

    def _listen(self,listener):
        try:
            with listener.accept() as conn:
                try:
                    recieved = conn.recv()
                except EOFError:
                    if self._verbose:
                        self._log('warning: null connection on socket')
                    return True
                except Exception as e:
                    if self._verbose:
                        self._log('warning: recieve failure on socket: {}'.format(e))
                    return True
                cmdline = recieved.strip().split(' ')
                #self._log('Recieved: {}'.format(cmdline))  # debug
                conn.send(self._process(cmdline))
            return True
        except AuthenticationError as e:
            if self._verbose:
                self._log('warning: authentication error on socket: {}'.format(e))
            return True
        except Exception as e:
            self._log('error: listner failed on socket\n{}'.format(e))
            return False

    def _process(self, cmdline):
        cmdset = {'info':1, 'states':0, 'open':2, 'close':2,
                    'get':2, 'set':6, 'f2p':2, 'p2f':2}
        floatsok = ['f2p', 'p2f']
        cmd = cmdline[0]
        args = [] if len(cmdline) == 1 else cmdline[1:]
        #print('{}({})'.format(cmd, '' if len(args) == 0 else ', '.join(args)))  # DEBUG
        for i in range(len(args)):
            try:
                if cmd in floatsok:
                    args[i] = float(args[i])
                else:
                    args[i] = int(args[i])
            except:
                err = 'client error: incorrect argument \'{}\' for \'{}\''.format(args[i], cmd)
                return self._log(err) if self._verbose else err
        if cmd not in cmdset.keys():
            err = 'client error: unknown command \'{}\''.format(cmd)
            return self._log(err) if self._verbose else err
        if len(args) != cmdset[cmd]:
            err = 'client error: incorrect argument count {} for \'{}\''.format(len(cmdline),cmd)
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

    def _pwmify(self, timer):
        p = timer[1]
        d = timer[2]
        return (timer[0], (p, d), timer[3])

    def info(self):
        return self._send('info {}'.format(getpid()))

    def states(self):
        states = self._send('states')
        if type(states) != dict:
            return states
        for chip in states.keys():
            for timer in states[chip].keys():
                if states[chip][timer] is not None:
                    states[chip][timer] = self._pwmify(states[chip][timer])
        return states

    def open(self, chip, timer):
        return self._send('open {} {}'.format(chip, timer))

    def close(self, chip, timer):
        return self._send('close {} {}'.format(chip, timer))

    def get(self, chip, timer):
        ret = self._send('get {} {}'.format(chip, timer))
        if type(ret) == tuple:
            ret = self._pwmify(ret)
        return ret

    def set(self, chip, timer, enable=None, pwm=None, polarity=None):
        if pwm is None:
            period = duty = None
        else:
            try:
                period, duty = pwm
            except Exception as e:
                return self._print('{}: error: pwm tuple ({}) incorrect: {}'.format(__name__, pwm, e))
        return self._send('set {} {} {} {} {} {}'
            .format(chip, timer, enable, period, duty, polarity))

    def f2p(self, freq, power):
        return self._send('f2p {} {}'.format(freq, power))

    def p2f(self, period, duty):
        return self._send('p2f {} {}'.format(period, duty))

if __name__ == "__main__":

    usage = '''Usage: v{0}
    {1} command <options> [--verbose]
    where 'command' is one of:
        server [<logfile>]
        states
        open <chip> <timer>
        close <chip> <timer>
        set <chip> <timer> <enable> <period> <duty_cycle> <polarity>
        get <chip> <timer>

    'server' starts a server on {2}.
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

        # Clean any existing socket on startup (or error)
        if path.exists(socket):
            try:
                remove(socket)
            except Exception as e:
                print('Socket {} already exists and cannot be removed.'.format(socket))
                print(e)
                print('Is another instance running?')
                exit(1)
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
                # timeout here.. ?
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

    '''
        Main Code
    '''
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
