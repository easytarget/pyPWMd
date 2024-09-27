'''
  PWM server daemon
'''

from time import ctime
from sys import argv
from os import path
from glob import glob

sock = '/run/pwm.sock'

class pypwm_server:
    '''
        PWM node control daemon (server)
        Needs root..
    '''

    def __init__(self, socket = sock, logfile = None):
        self.socket = socket
        self._logfile = logfile
        self._sysbase  = '/sys/class/pwm'
        self._chipbase = 'pwmchip'
        self._polarities = ['normal', 'inversed']

        self._log('Scanning for pwm timers')
        chips = self._chipscan()
        if len(chips) == 0:
            self._log('No PWM devices available in {}!'.format(self._sysbase))
        else:
            self._log('PWM devices:')
            for chip in chips.keys():
                self._log('- {} with {} timers'.format(chip, chips[chip]))

    def _log(self, string):
        data = '{} :: {}'.format(ctime(), string)
        if self._logfile is not None:
            with open(self._logfile,'w') as f:
                f.write(data + '\n')
        else:
            print(data)

    def _chipscan(self):
        #returns a dict with <path>:<number of pwms>
        base = '{}/{}'.format(self._sysbase,self._chipbase)
        chips = {}
        for chip in glob('{}*'.format(base)):
            with open(chip + '/npwm','r') as npwm:
                chips[chip] = int(npwm.read())
        return chips

    def _gettimer(self,node):
        with open(node + '/enable','r') as f:
           enable = int(f.read())
        with open(node + '/period','r') as f:
           period = int(f.read())
        with open(node + '/duty_cycle','r') as f:
           duty = int(f.read())
        with open(node + '/polarity','r') as f:
           polarity = self._polarities.index(f.read().strip())
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
                return False
            return True

        node = '{}/{}{}/pwm{}'.format(self._sysbase, self._chipbase, chip, timer)
        if not path.exists(node):
            self._log('error: attempt to set unexported timer {}'.format(node))
            return False
        state = list(self._gettimer(node))
        print('before' + str(state))  # debug
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
        print('after' + str(self._gettimer(node)))  # debug

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
            return True

if __name__ == "__main__":
    '''
      Init and run a server
    '''
    logfile = None
    if len(argv) > 1:
        logfile = argv[1]

    print('Starting Python PWM server')
    if logfile is not None:
        print('Logging to: {}'.format(logfile))

    p = pypwm_server(sock, logfile)
    print(p.states())
