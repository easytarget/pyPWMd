#!/usr/bin/python3
'''
  PWM server daemon
'''

from time import ctime
from sys import argv, exit
from os import path, remove, makedirs, chown, chmod
from glob import glob
from multiprocessing.connection import Listener, Client

_sockdir = '/run/pwm'
_sockowner = (1000,1000)  # UID/GID
_sockperm = 0o770  # Note.. octal
socket = _sockdir + '/pyPWMd.sock'
myname = path.basename(__file__)

usage = '''{}:
    A Help file..
    ...would help!
'''.format(myname).strip()

class pypwm_server:
    '''
        PWM node control daemon (server)
        Needs root..
    '''

    def __init__(self, logfile = None):
        self._logfile = logfile
        self._sysbase  = '/sys/class/pwm'
        self._chipbase = 'pwmchip'
        self._polarities = ['normal', 'inversed']

        self._log('\nServer init')
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
            with open(self._logfile,'a') as f:
                f.write(out + '\n')
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

    def _getprop(self,n):
        with open(n,'r') as f:
           r = f.read().strip()
        return r

    def _gettimer(self,node):
        enable = int(self._getprop(node + '/enable'))
        period = int(self._getprop(node + '/period'))
        duty = int(self._getprop(node + '/duty_cycle'))
        polarity = self._polarities.index(self._getprop(node + '/polarity'))
        return enable, period, duty, polarity

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

    def set(self, chip, timer, enable=None, pwm=None, polarity=None):
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
            return False
        state = list(self._gettimer(node))
        if pwm is not None:
            period, duty = pwm
            if duty > period:
                self._log('error: cannot set duty:{} greater than period:{}'
                    .format(duty, period))
                return False
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
            return False
        if not path.exists(node + '/pwm' + str(timer)):
            return False
        else:
            self._log('opened: {}'.format(node))
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
            return False
        if path.exists(node + '/pwm' + str(timer)):
            return False
        else:
            self._log('closed: {}'.format(node))
            return True

    def serve(self, socket, owner = None, perm = None):
        with Listener(socket) as listener:
            self._log('Listening on: ' + listener.address)
            if owner is not None:
                try:
                    chown(socket, *owner)
                except Exception as e:
                    self._log("warning: could not set socket owner: {}".format(e))
            if perm is not None:
                try:
                    chmod(socket, perm)
                except Exception as e:
                    self._log("warning: could not set socket permissions: {}".format(e))
            while True:
                with listener.accept() as conn:
                    cmdline = conn.recv()
                    self._log('Recieved: ' + cmdline)  # debug
                    conn.send(self._process(cmdline))

    def _process(self, cmdline):
        cmd = cmdline.strip().split(',')[0]
        args = [] if len(cmdline) == 1 else cmdline[1:]
        if cmd in ['states', 'open', 'close', 'set', 'get']:
            return  exec(cmd + str(*args))
        return '{} invalid command: {}, try \'help\''.format(self.__module__, cmd)


if __name__ == "__main__":
    def runserver():
        '''
          Init and run a server
        '''
        # Ensure we have a socket directory in /run
        if not path.isdir(_sockdir):
            makedirs(_sockdir)
        # Clean any existing socket (or error)
        if path.exists(socket):
            try:
                remove(socket)
            except Exception as e:
                print('Socket {} already exists and cannot be removed.'.format(socket))
                print(e)
                print('Is another instance running?')
                exit(1)

        print('Starting Python PWM server')
        if logfile is not None:
            print('Logging to: {}'.format(logfile))

        p = pypwm_server(logfile)
        p.serve(socket, owner = _sockowner, perm = _sockperm)
        print('Server Exited')

    def runcommand(cmdline):
        '''
          Pass the the command to server
          ? syntax to match python syntax : simple ?
        '''
        return 'TODO: {}'.format(cmdline), 0

    # Parse Arguments and take appropriate action
    try:
        l = argv.index('--logfile')
    except ValueError:
        logfile = None
    else:
        try:
            logfile = argv[l + 1]
        except Exception:
            print('{}: You must supply a filename for the --logfile option.'.format(myname))
            exit(2)
        argv.pop(l + 1)
        argv.pop(l)

    if len(argv) == 1:
        print('{}: No command specified\n{}'.format(myname, usage))
        exit(2)

    # Command is always first argument
    command = argv[1]
    if command == 'server':
        runserver()
    elif command in ['h', 'help', 'Help', '-h', '--help', 'usage', 'info']:
        print(usage)
    else:
        response, status = runcommand(argv[1:])
        print(response)
        exit(status)
    exit(0)

