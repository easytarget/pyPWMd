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

    def __init__(self, socket=sock, logfile=None):
        self.socket = socket
        self.logfile = logfile
        self.sysbase  = '/sys/class/pwm'
        self.chipbase = 'pwmchip'
        self.polarities = ['normal','inversed']

        self._log('scanning for pwm timers')
        chips = self._chipscan()
        if len(chips) == 0:
            self._log('No PWM devices available in {}!'.format(self.sysbase))
        else:
            self._log('PWM devices:')
            for chip in chips.keys():
                self._log('- {} with {} timers'.format(chip, chips[chip]))

    def _log(self, string):
        data = '{} :: {}'.format(ctime(), string)
        if self.logfile is not None:
            with open(self.logfile,'w') as logfile:
                logfile.write(data + '\n')
        else:
            print(data)

    def _chipscan(self):
        #returns a dict with <path>:<number of pwms>
        base = '{}/{}'.format(self.sysbase,self.chipbase)
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
           polarity = self.polarities.index(f.read().strip())
        return enable, period, duty, polarity

    def states(self):
        pwms = {}
        chips = self._chipscan()
        for chip in chips.keys():
            c = chip[len(self.sysbase + self.chipbase)+1:]
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
        node = '{}/{}{}/pwm{}'.format(self.sysbase,
            self.chipbase, chip, timer)
        if not path.exists(node):
            return None
        return self._gettimer(node)

    def set(self, chip, timer, enable=None, period=None, duty=None, polarity=None):
        def setprop(n, p, v):
            try:
                with open(n + '/' + p, 'w') as export:
                    export.write(str(v))
            except (FileNotFoundError, OSError) as e:
                self._log('Cannot set {}/{} :: {}'.format(n, p, repr(e)))
                return False
            return True

        node = '{}/{}{}/pwm{}'.format(self.sysbase, self.chipbase, chip, timer)
        if not path.exists(node):
            self._log('error: attempt to set unexported timer {}'.format(node))
            return False
        state = self._gettimer(node)
        print(state)
        if period is not None:
            # min and max values?
            # set duty to zero first?
            if state[3] != period:
                setprop(node, 'period', period)
        if duty is not None:
            #duty = min(period,duty), use period from state if period is None
            if state[3] != duty:
                setprop(node, 'duty_cycle', duty)
        if polarity is not None:
            if state[3] != polarity:
                setprop(node, 'polarity', self.polarities[polarity])
        if enable is not None:
            if state[0] != enable:
                setprop(node, 'enable', enable)
        print(self._gettimer(node))

    def open(self, chip, timer):
        node = '{}/{}{}'.format(self.sysbase, self.chipbase, chip)
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
        node = '{}/{}{}'.format(self.sysbase, self.chipbase, chip)
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
