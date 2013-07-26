#!/usr/bin/env python
#
# Copyright (c) SAS Institute, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#


import errno
import fcntl
import os
import select
import signal
import struct
import sys
import telnetlib
import termios

from telnetlib import IAC, IP, SB, SE, NAWS

TERMKEY = '\x1d' # equals ^]

def getTerminalSize():
    s = struct.pack('HHHH', 0, 0, 0, 0)
    result = fcntl.ioctl(sys.stdin.fileno(), termios.TIOCGWINSZ, s)
    rows, cols = struct.unpack('HHHH', result)[0:2]
    return rows, cols

class TelnetClient(telnetlib.Telnet):
    def __init__(self, *args, **kw):
        telnetlib.Telnet.__init__(self, *args, **kw)
        signal.signal(signal.SIGINT, self.ctrl_c)
        signal.signal(signal.SIGWINCH, self.sigwinch)
        self.oldTerm = None
        self.oldFlags = None

    def set_raw_mode(self):
        fd = sys.stdin.fileno()
        self.oldTerm = termios.tcgetattr(fd)
        newattr = termios.tcgetattr(fd)
        newattr[3] = newattr[3] & ~termios.ICANON & ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSANOW, newattr)
        self.oldFlags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, self.oldFlags | os.O_NONBLOCK)

    def restore_terminal(self):
        fd = sys.stdin.fileno()
        if self.oldTerm:
            termios.tcsetattr(fd, termios.TCSAFLUSH, self.oldTerm)
        if self.oldFlags:
            fcntl.fcntl(fd, fcntl.F_SETFL, self.oldFlags)

    def ctrl_c(self, int, tb):
        self.sock.sendall(IAC + IP)
        self.sock.sendall('close\n')
        raise KeyboardInterrupt

    def sigwinch(self, int, tb):
        self.updateTerminalSize()

    def updateTerminalSize(self):
        rows, cols = getTerminalSize()
        out = struct.pack('>HH', cols, rows)
        out.replace('\xFF', '\xFF\xFF')  # escape IAC
        self.sock.sendall(IAC + SB + NAWS + out + IAC + SE)

    def write(self, buffer):
        if TERMKEY in buffer:
            buffer = buffer[:buffer.find(TERMKEY)]
            if buffer:
                telnetlib.Telnet.write(self, buffer)
            self.close()
        else:
            telnetlib.Telnet.write(self, buffer)

    def interact(self):
        self.set_raw_mode()
        try:
            self.updateTerminalSize()
            writeBuffer = []
            while not self.eof:
                readyWriters = []
                readyReaders = []
                neededReaders = [self, sys.stdin]
                neededWriters = []
                while not self.eof:
                    try:
                        rfd, wfd, xfd = select.select(neededReaders,
                                                      neededWriters, [])
                    except select.error, err:
                        if err.args[0] != errno.EINTR: # ignore interrupted select
                            raise
                    readyReaders.extend(rfd)
                    [neededReaders.remove(x) for x in rfd if x in neededReaders]
                    readyWriters.extend(wfd)
                    [neededWriters.remove(x) for x in wfd if x in neededWriters]
                    if self in readyReaders:
                        if sys.stdout in readyWriters:
                            break
                        else:
                            neededWriters.append(sys.stdout)
                    if sys.stdin in readyReaders:
                        if self in readyWriters:
                            break
                        else:
                            neededWriters.append(self)
                if self in readyReaders and sys.stdout in readyWriters:
                    select.select([sys.stdin], [sys.stdout], [])
                    try:
                        text = self.read_eager()
                    except EOFError:
                        print '*** Connection closed by remote host ***'
                        break
                    if text:
                        sys.stdout.write(text)
                        sys.stdout.flush()
                if sys.stdin in readyReaders and self in readyWriters:
                    line = sys.stdin.read(4096)
                    if not line:
                        break
                    self.write(line)
        finally:
            self.restore_terminal()

if __name__ == '__main__':
    t = TelnetClient('localhost', 8000)
    t.interact()
