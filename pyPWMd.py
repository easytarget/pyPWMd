#!/usr/bin/python3
'''
  PWM server daemon
'''

from time import ctime
from sys import argv, exit
from os import path, remove, makedirs, chown, chmod, getuid, getgid, getpid, kill
from signal import SIGSTOP
from glob import glob
from multiprocessing.connection import Listener, Client
from json import dumps, loads

# Some housekeeping
name = path.basename(__file__)
version = '0.1'

# Define the socket
_sockdir = '/run/pwm'
_sockowner = (1000,1000)  # UID/GID
_sockperm = 0o770  # Note.. octal
socket = _sockdir + '/pyPWMd.sock'
# By default use version string as auth token, prevents API fails.
auth = bytes(version.encode('utf-8'))

# pwm API specifies nanoseconds as the base period unit.
basefreq = 1000000000

class pypwm_server:
    '''
        PWM node control daemon (server)
        Needs root..
    '''

    def __init__(self, logfile=None, verbose=False):
        self._logfile = logfile
        self.verbose = verbose
        self._sysbase  = '/sys/class/pwm'
        self._chipbase = 'pwmchip'
        self._polarities = ['normal', 'inversed']

        self._log('\nServer v{} init'.format(version))
        self._log('Scanning for pwm timers')
        chips = self._chipscan()
        if len(chips) == 0:
            self._log('No PWM devices available in {}!'.format(self._sysbase))
        else:
            self._log('PWM devices:')
            for chip in chips.keys():
                self._log('- {} with {} timers'.format(chip, chips[chip]))

    def _log(self, string):
        string += '\n'
        out = '\n' if string[0] == '\n' else ''
        for line in string.strip().split('\n'):
            out += '{} :: {}'.format(ctime(), line)
        if self._logfile is not None:
            with open(self._logfile,'a') as file:
                file.write(out + '\n')
        else:
            print(out)

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

    def info(self):
        self._log('client sent info request')
        return [version, getpid(), getuid(), getgid(), self._sysbase]

    def states(self):
        pwms = {}
        chips = self._chipscan()
        for chip in chips.keys():
            c = chip[len(self._sysbase + self._chipbase)+1:]
            pwms[c] = {}
            for timer in range(chips[chip]):
                node = '{}/pwm{}'.format(chip, timer)
                if path.exists(node):
                    pwms[c][timer] = list(self._gettimer(node))
                    pwms[c][timer].append(node)
                else:
                    pwms[c][timer] = None
        return pwms

    def get(self, chip, timer):
        node = '{}/{}{}/pwm{}'.format(self._sysbase,
            self._chipbase, chip, timer)
        if not path.exists(node):
            return None
        return self._gettimer(node)

    def set(self, chip, timer, enable, period, duty, polarity):
        # Set properties for a timer

        def setprop(n, p, v):
            # Set an individual node+property with error trap.
            try:
                with open(n + '/' + p, 'w') as f:
                    f.write(str(v))
            except (FileNotFoundError, OSError) as e:
                self._log('Cannot set {}/{} :: {}'.format(n, p, repr(e)))

        node = '{}/{}{}/pwm{}'.format(self._sysbase, self._chipbase, chip, timer)
        if not path.exists(node):
            self._log('error: attempt to set unexported timer {}'.format(node))
            return 'error: attempt to set unexported timer {}'.format(node)
        state = list(self._gettimer(node))
        if period is not None:
            if duty > period:
                self._log('error: cannot set duty={} greater than period={}'.format(duty, period))
                return 'error: cannot set duty={} greater than period={}'.format(duty, period)
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
        if self.verbose:
            self._log('set: {} = {} '.format(node, list(self._gettimer(node))))
        return True

    def open(self, chip, timer):
        node = '{}/{}{}'.format(self._sysbase, self._chipbase, chip)
        if path.exists(node + '/pwm' + str(timer)):
            return True
        try:
            with open(node + '/export', 'w') as export:
                export.write(str(timer))
        except (FileNotFoundError, OSError) as e:
            self._log('Cannot access {}/export :: {}'.format(node, repr(e)))
            return 'Cannot access {}/export :: {}'.format(node, repr(e))
        if not path.exists(node + '/pwm' + str(timer)):
            return 'Failed to create {}/pwm'.format(node)
        else:
            self._log('opened: {}/pwm{}'.format(node, timer))
            return True

    def close(self, chip, timer):
        node = '{}/{}{}'.format(self._sysbase, self._chipbase, chip)
        if not path.exists(node + '/pwm' + str(timer)):
            return True
        try:
            with open(node + '/unexport', 'w') as unexport:
                unexport.write(str(timer))
        except (FileNotFoundError, OSError) as e:
            self._log('Cannot access {}/unexport :: {}'.format(node, repr(e)))
            return 'Cannot access {}/unexport :: {}'.format(node, repr(e))
        if path.exists(node + '/pwm' + str(timer)):
            return 'Failed to destroy {}/pwm'.format(node)
        else:
            self._log('closed: {}/pwm{}'.format(node, timer))
            return True

    def f2p(self, freq, power):
        # convert a frequency(Hz) and power(fraction) to
        #  a period and duty_cycle in nanoseconds
        period = int(basefreq / freq)
        duty = int(period * power)
        return period, duty

    def p2f(self, period, duty):
        # convert a period and duty_cycle in nanoseconds to
        #  a frequency(Hz) and power(fraction)
        freq = round(basefreq / period, 3)
        power = round(duty / period, 3)
        return freq, power

    def server(self, sock=socket, owner=None, perm=None):
        with Listener(sock, authkey=auth) as listener:
            self._log('Listening on: ' + listener.address)
            if owner is not None:
                try:
                    chown(sock, *owner)
                except Exception as e:
                    self._log("warning: could not set socket owner: {}".format(e))
            if perm is not None:
                try:
                    chmod(sock, perm)
                except Exception as e:
                    self._log("warning: could not set socket permissions: {}".format(e))
            # Now loop forever listening and responding to socket
            while True:
                self._listen(listener)

    def _listen(self,listener):
        try:
            with listener.accept() as conn:
                try:
                    recieved = conn.recv()
                except EOFError:
                    recieved = ''
                    self._log('warning: null connection on socket: {}'.format(recieved))
                    return   # empty connection, ignore
                cmdline = recieved.strip().split(' ')
                #self._log('Recieved: {}'.format(cmdline))  # debug
                conn.send(self._process(cmdline))
        except Exception as e:
            self._log('warning: error on socket\n{}'.format(e))

    def _process(self, cmdline):
        cmdset = {'info':0, 'states':0, 'open':2, 'close':2,
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
                self._log('error: incorrect argument \'{}\' for \'{}\''.format(args[i], cmd))
                return 'error: imcorrect argument: \'{}\' for \'{}\''.format(args[i], cmd)
        if cmd not in cmdset.keys():
            self._log('error: unknown command \'{}\''.format(cmd))
            return 'error: unknown command \'{}\''.format(cmd)
        if len(args) != cmdset[cmd]:
            self._log('error: incorrect argument count {} for \'{}\''.format(len(cmdline),cmd))
            return 'error: incorrect argument count {} for \'{}\''.format(len(cmdline), cmd)
        return getattr(self,cmd)(*args)

class pypwm_client:
    '''
        PWM node control client
    '''

    def __init__(self, sock=socket, verify=True, verbose=False):
        self._sock = sock
        self.verbose = verbose
        self.connected = True
        if verify:
            info = self.info()
            if info is None:
                self.connected = False
            elif info[0] != version:
                self._print('{}: warning: version missmatch to server running at {}'
                    .format(i__name__, self._sock))

    def _print(self, msg):
        if self.verbose:
            print(msg)

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
        except Exception as e:
            self._print('{}: error taking to server at {}\n{}'
                .format(__name__, self._sock, e))
            self.connected = False
            return None

    def info(self):
        return self._send('info')

    def states(self):
        return self._send('states')

    def open(self, chip, timer):
        return self._send('open {} {}'.format(chip, timer))

    def close(self, chip, timer):
        return self._send('close {} {}'.format(chip, timer))

    def get(self, chip, timer):
        return self._send('get {} {}'.format(chip, timer))

    def set(self, chip, timer, enable=None, pwm=None, polarity=None):
        if pwm is None:
            period = duty = None
        else:
            try:
                period, duty = pwm
            except Exception as e:
                self._print('{}: error: pwm tuple ({}) is incorrect: {}'
                    .format(__name__, pwm, e))
                return None
        return self._send('set {} {} {} {} {} {}'
            .format(chip, timer, enable, period, duty, polarity))

    def f2p(self, freq, power):
        return self._send('f2p {} {}'.format(freq, power))

    def p2f(self, period, duty):
        return self._send('p2f {} {}'.format(period, duty))

if __name__ == "__main__":

    usage = '''Usage: v{0}
    {1} command <options>  [--logfile file] [--verbose]
    where 'command' is one of:
        server
        states
        open <chip> <timer>
        close <chip> <timer>
        set <chip> <timer> <enable> <period> <duty_cycle> <polarity>
        get <chip> <timer>

    'server' starts a server on {2}.
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

    The --logfile option supresses the console log and sends it to the named
    file instead. --verbose, enables logging of 'set' events.

    Homepage: https://github.com/easytarget/pyPWMd
    '''.format(version, name, socket).strip()

    def runserver():
        '''
          Init and run a server,
        '''
        # Ensure we have a socket directory in /run
        if not path.isdir(_sockdir):
            try:
                makedirs(_sockdir)
            except Exception as e:
                print('Cannot create socket directory: {}.'.format(_sockdir))
                print(e)
                print('Running as uid:gid {}:{}'.format(getuid(),getgid()))
                exit(1)

        # Clean any existing socket (or error)
        if path.exists(socket):
            try:
                remove(socket)
            except Exception as e:
                print('Socket {} already exists and cannot be removed.'.format(socket))
                print(e)
                print('Is another instance running?')
                exit(1)

        print('Starting Python PWM server v{}'.format(version))
        if logfile is not None:
            print('Logging to: {}'.format(logfile))

        p = pypwm_server(logfile, verbose)
        p.server(owner=_sockowner, perm=_sockperm)
        print('Server Exited')

    def runcommand(cmdline):
        '''
          Pass the the command to server
        '''
        with Client(socket, authkey=auth) as conn:
            conn.send(' '.join(cmdline))
            # timeout here.. ?
            reply = conn.recv()
        if reply is None:
            state = 1
            reply = ''
        elif type(reply) == str and 'error' in reply.lower():
            state = 1
        else:
            state = 0
        return reply, state

    '''
        Main Code
    '''
    # Parse Arguments and take appropriate action
    try:
        l = argv.index('--logfile')
    except ValueError:
        logfile = None
    else:
        try:
            logfile = argv[l + 1]
        except Exception:
            print('{}: You must supply a filename for the --logfile option.'.format(name))
            exit(2)
        argv.pop(l + 1)
        argv.pop(l)

    try:
        l = argv.index('--verbose')
    except ValueError:
        verbose = False
    else:
        verbose = True
        argv.pop(l)

    if len(argv) == 1:
        print('{}: No command specified, try: {} help'.format(name, argv[0]))
        exit(2)

    # Command is always first argument
    command = argv[1]
    if command == 'server':
        runserver()
    elif command in ['h', 'help', 'Help', '-h', '--help', 'usage']:
        print(usage)
    else:
        response, status = runcommand(argv[1:])
        if response != True:
            print(response)
        exit(status)
    exit(0)
