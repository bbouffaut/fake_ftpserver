# coding=utf-8
import os
import socket
import threading
import time
import traceback
import requests
import logging

def make_path(*parts):
    path = os.path.join(*parts)
    return path


class BaseFtpThread(threading.Thread):
    GUEST = 'guest'

    def __init__(self, (conn, addr), ftp_server):
        #self.logger = logging.getLogger(__name__)
        #self.logger.setLevel(logging.INFO)
        self.allowed_commands = ''
        self.conn = conn
        self.addr = addr
        self.server = ftp_server
        self._base_dir = self.server.ftp_path
        self.home_dir = self._base_dir
        self.cwd = self.home_dir
        self._authorized = False
        self._user = self.GUEST
        self.rest = False
        self.pasv_mode = False
        self.mode = 'I'
        self.pos = self.rnfn = self.datasock = self.servsock = self.data_addr = \
            self.data_port = None
        threading.Thread.__init__(self)

    def _send(self, data, channel=None):
        if channel == 'data':
            self._log('<= ' + data.rstrip())
            self.datasock.send(data + '\r\n')
        else:
            self._log('<  ' + data)
            self.conn.send(data + '\r\n')

    def _log(self, s, *args):
        import datetime
        t = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        print('[%s %s:%s] %s' % (t, self.addr[0], self.addr[1], s % args))

    def _command_allowed(self, cmd):
        return True

    def run(self):
        self._log('Thread started.')
        self._send('220 Welcome!')
        while True:
            try:
                cmd = self.conn.recv(256)
            except Exception as e:
                self._log('Connection aborted %r', e)
                break
            # TODO: clean characters
            if not cmd:
                break
            else:
                self._log(' > ' + cmd.strip())
                try:
                    c = cmd[:4].strip().upper()
                    if not hasattr(self, c) or not self._command_allowed(c):
                        self._send('502 Command not implemented.')
                    elif self._authorized and c in ['USER', 'PASS']:
                        self._send('503 Bad sequence of commands.')
                    elif not self._user and c in ['PASS']:
                        self._send('503 Bad sequence of commands.')
                    elif not self._authorized and c not in ['USER', 'PASS', 'QUIT']:
                        self._send('530 Not logged in.')
                    else:
                        getattr(self, c)(cmd)
                except Exception:
                    traceback.print_exc()
                    self._send('500 Error.')
        self._log('Thread closed.')

    def start_datasock(self):
        if self.pasv_mode:
            self.datasock, addr = self.servsock.accept()
            self._log('Open passive socket %s:%s', *addr)
        else:
            self.datasock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            self.datasock.connect((self.data_addr, self.data_port))
            self._log('Open given socket %s:%s', self.data_addr, self.data_port)

    def stop_datasock(self):
        if self.datasock:
            self._log('Close socket %s:%s', *self.datasock.getsockname())
            self.datasock.close()
        if self.pasv_mode:
            try:
                self._log('Close passive socket %s:%s', *self.servsock.getsockname())
            except:
                pass
            self.servsock.close()


class FtpThread(BaseFtpThread):

    def OPTS(self, cmd):
        if cmd[5:-2].upper() == 'UTF8 ON':
            self._send('200 OK.')
        else:
            self._send('451 Sorry.')

    def SYST(self, cmd):
        self._send('215 UNIX Type: L8')  # See http://cr.yp.to/ftp/syst.html

    def USER(self, cmd):
        self._user = cmd[4:].strip() or self.GUEST
        self._send('331 OK.')

    def PASS(self, cmd):
        self._send('230 OK.')
        self._authorized = True
        self.cwd = self.home_dir = make_path(self._base_dir, self._user)
        # self._send('530 Incorrect.')

    def QUIT(self, cmd):
        self._send('221 Goodbye.')

    def NOOP(self, cmd):
        self._send('200 OK.')

    def TYPE(self, cmd):
        if cmd[5] in ['I', 'A']:
            self.mode = cmd[5]
            if self.mode == 'I':
                self._send('200 Type set to: Binary.')
            else:
                self._send('200 Type set to: ASCII.')
        else:
            self._send('500 Sorry, only binary and ASCII type supported.')

    def CDUP(self, cmd):
        self._send('200 OK.')

    def PWD(self, cmd):
        self._send('257 "%s"' % self.cwd)

    def CWD(self, cmd):
        chwd = cmd[4:-2]
        if chwd == '/':
            self.cwd = self.home_dir
        elif chwd[0] == '/':
            self.cwd = chwd
        elif chwd == '..':
            head, tail = os.path.split(self.cwd)
            self.cwd = head
        else:
            self.cwd = os.path.join(self.cwd, chwd[0:])
        self._send('250 "%s" is the current directory.' % (self.cwd))

    def PORT(self, cmd):
        if self.pasv_mode:
            self.servsock.close()
            self.pasv_mode = False
        l = cmd[5:].split(',')
        self.data_addr = '.'.join(l[:4])
        self.data_port = (int(l[4]) << 8) + int(l[5])
        self._log('Custom addr and port %s:%s', self.data_addr, self.data_port)
        self._send('200 Get port.')

    def PASV(self, cmd):  # from http://goo.gl/3if2U
        self.pasv_mode = True
        self.servsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.servsock.bind((self.server.ftp_ip, 0))
        self.servsock.listen(1)
        ip, port = self.servsock.getsockname()
        self._log('Opened socket %s:%s', ip, port)
        self._send('227 Entering Passive Mode (%s,%u,%u).' % (
            ','.join(ip.split('.')),
            port >> 8 & 0xFF,
            port & 0xFF,
        ))

    def LIST(self, cmd):
        self._send('150 Here comes the directory listing.')
        print('list:', self.cwd)

        self.start_datasock()
        self.stop_datasock()
        self._send('226 Directory send OK.')

    def MKD(self, cmd):
        self._send('550 File exists.')

    def RMD(self, cmd):
        self._send('250 Directory deleted.')

    def DELE(self, cmd):
        self._send('250 File deleted.')

    def RNFR(self, cmd):
        self._send('350 Ready.')

    def RNTO(self, cmd):
        self._send('250 File renamed.')

    def REST(self, cmd):
        self.pos = int(cmd[5:-2])
        self.rest = True
        self._send('350 Restarting at position %s.' % (self.pos))

    def RETR(self, cmd):
        self._send('150 Opening data connection.')
        self.start_datasock()
        self.stop_datasock()
        self._send('226 Transfer complete.')

    def STOR(self, cmd):
        fn = os.path.join(self.cwd, cmd[5:-2])
        self._log('Upload: ' + fn)
        #fo = open(fn, 'wb')
        self._send('150 Opening data connection.')
        self.start_datasock()
        while True:
            data = self.datasock.recv(1024)
            if not data:
                break
        #    fo.write(data)
        #fo.close()
        self.stop_datasock()
        self._send('226 Transfer complete.')

    def SIZE(self, cmd):
        self._send('213 0')


class FTPserver(threading.Thread):

    def __init__(self, ip='127.0.0.1', port=21, path='/home', can_delete=False):
        self.ftp_ip = ip
        self.ftp_port = port
        self.ftp_path = make_path(path)
        self.can_delete = can_delete
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((ip, port))
        threading.Thread.__init__(self)

    def run(self):
        self.sock.listen(5)
        while True:
            th = FtpThread(self.sock.accept(), ftp_server=self)
            th.daemon = True
            th.start()

    def stop(self):
        self.sock.close()


if __name__ == '__main__':
    import sys
    server_ip = '10.10.0.129'
    server_port = 2121
    if len(sys.argv) > 1:
        if '.' in sys.argv[1]:
            server_ip = sys.argv[1]
        else:
            server_port = int(sys.argv[1])
    if len(sys.argv) > 2:
        server_port = int(sys.argv[2])
    ftp = FTPserver(ip=server_ip, port=server_port)
    ftp.daemon = True
    try:
        ftp.start()
        raw_input('Enter to quit...\n')
    except KeyboardInterrupt:
        pass
    finally:
        ftp.stop()
        print('Bye.')
