# coding=utf-8
import os
import socket
import threading
import time
import traceback


class FTPserverThread(threading.Thread):

    def __init__(self, (conn, addr), ftp_server):
        self.conn = conn
        self.addr = addr
        self.server = ftp_server
        self.cwd = self.basewd
        self.rest = False
        self.pasv_mode = False
        self.pos = self.rnfn = self.datasock = self.servsock = self.data_addr = self.data_port = self.mode = None
        threading.Thread.__init__(self)

    @property
    def basewd(self):
        return self.server.ftp_path

    def run(self):
        self.conn.send('220 Welcome!\r\n')
        while True:
            cmd = self.conn.recv(256)
            if not cmd:
                break
            else:
                print 'Recieved:', cmd
                try:
                    func = getattr(self, cmd[:4].strip().upper())
                    func(cmd)
                except Exception:
                    traceback.print_exc()
                    self.conn.send('500 Sorry.\r\n')
 
    def SYST(self, cmd):
        self.conn.send('215 UNIX Type: L8\r\n')

    def OPTS(self, cmd):
        if cmd[5:-2].upper() == 'UTF8 ON':
            self.conn.send('200 OK.\r\n')
        else:
            self.conn.send('451 Sorry.\r\n')

    def USER(self, cmd):
        self.conn.send('331 OK.\r\n')

    def PASS(self, cmd):
        self.conn.send('230 OK.\r\n')  # self.conn.send('530 Incorrect.\r\n')

    def QUIT(self, cmd):
        self.conn.send('221 Goodbye.\r\n')

    def NOOP(self, cmd):
        self.conn.send('200 OK.\r\n')

    def TYPE(self, cmd):
        self.mode = cmd[5]
        self.conn.send('200 Binary mode.\r\n')
 
    def CDUP(self, cmd):
        if not os.path.samefile(self.cwd, self.basewd):
            self.cwd = os.path.abspath(os.path.join(self.cwd, '..'))
        self.conn.send('200 OK.\r\n')

    def PWD(self, cmd):
        cwd = os.path.relpath(self.cwd, self.basewd)
        if cwd == '.':
            cwd = '/'
        else:
            cwd = '/' + cwd
        self.conn.send('257 \"%s\"\r\n' % cwd)

    def CWD(self, cmd):
        chwd = cmd[4:-2]
        if chwd == '/':
            self.cwd = self.basewd
        elif chwd[0] == '/':
            self.cwd = os.path.join(self.basewd, chwd[1:])
        else:
            self.cwd = os.path.join(self.cwd, chwd)
        self.conn.send('250 OK.\r\n')
 
    def PORT(self, cmd):
        if self.pasv_mode:
            self.servsock.close()
            self.pasv_mode = False
        l = cmd[5:].split(',')
        self.data_addr = '.'.join(l[:4])
        self.data_port = (int(l[4]) << 8) + int(l[5])
        self.conn.send('200 Get port.\r\n')
 
    def PASV(self, cmd):  # from http://goo.gl/3if2U
        self.pasv_mode = True
        self.servsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.servsock.bind((self.server.ftp_ip, 0))
        self.servsock.listen(1)
        ip, port = self.servsock.getsockname()
        print 'open', ip, port
        self.conn.send('227 Entering Passive Mode (%s,%u,%u).\r\n' % (','.join(ip.split('.')), port >> 8 & 0xFF,
                                                                      port & 0xFF))
 
    def start_datasock(self):
        if self.pasv_mode:
            self.datasock, addr = self.servsock.accept()
            print 'connect:', addr
        else:
            self.datasock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.datasock.connect((self.data_addr, self.data_port))
 
    def stop_datasock(self):
        self.datasock.close()
        if self.pasv_mode:
            self.servsock.close()

    def LIST(self, cmd):
        self.conn.send('150 Here comes the directory listing.\r\n')
        print 'list:', self.cwd
        self.start_datasock()
        for t in os.listdir(self.cwd):
            k = self._list_item(os.path.join(self.cwd, t))
            self.datasock.send(k + '\r\n')
        self.stop_datasock()
        self.conn.send('226 Directory send OK.\r\n')
 
    def _list_item(self, fn):
        st = os.stat(fn)
        fullmode = 'rwxrwxrwx'
        mode = ''
        for i in range(9):
            mode += ((st.st_mode >> (8 - i)) & 1) and fullmode[i] or '-'
        d = os.path.isdir(fn) and 'd' or '-'
        ftime = time.strftime(' %b %d %H:%M ', time.gmtime(st.st_mtime))
        return d + mode + ' 1 user group ' + str(st.st_size) + ftime + os.path.basename(fn)
 
    def MKD(self, cmd):
        dn = os.path.join(self.cwd, cmd[4:-2])
        os.mkdir(dn)
        self.conn.send('257 Directory created.\r\n')
 
    def RMD(self, cmd):
        dn = os.path.join(self.cwd, cmd[4:-2])
        if self.server.can_delete:
            os.rmdir(dn)
            self.conn.send('250 Directory deleted.\r\n')
        else:
            self.conn.send('450 Not allowed.\r\n')
 
    def DELE(self, cmd):
        fn = os.path.join(self.cwd, cmd[5:-2])
        if self.server.can_delete:
            os.remove(fn)
            self.conn.send('250 File deleted.\r\n')
        else:
            self.conn.send('450 Not allowed.\r\n')
 
    def RNFR(self, cmd):
        self.rnfn = os.path.join(self.cwd, cmd[5:-2])
        self.conn.send('350 Ready.\r\n')
 
    def RNTO(self, cmd):
        fn = os.path.join(self.cwd, cmd[5:-2])
        os.rename(self.rnfn, fn)
        self.conn.send('250 File renamed.\r\n')
 
    def REST(self, cmd):
        self.pos = int(cmd[5:-2])
        self.rest = True
        self.conn.send('250 File position reseted.\r\n')
 
    def RETR(self, cmd):
        fn = os.path.join(self.cwd, cmd[5:-2])
        #fn=os.path.join(self.cwd,cmd[5:-2]).lstrip('/')
        print 'Download:', fn
        if self.mode == 'I':
            fi = open(fn, 'rb')
        else:
            fi = open(fn, 'r')
        self.conn.send('150 Opening data connection.\r\n')
        if self.rest:
            fi.seek(self.pos)
            self.rest = False
        data = fi.read(1024)
        self.start_datasock()
        while data:
            self.datasock.send(data)
            data = fi.read(1024)
        fi.close()
        self.stop_datasock()
        self.conn.send('226 Transfer complete.\r\n')
 
    def STOR(self, cmd):
        fn = os.path.join(self.cwd, cmd[5:-2])
        print 'Upload:', fn
        if self.mode == 'I':
            fo = open(fn, 'wb')
        else:
            fo = open(fn, 'w')
        self.conn.send('150 Opening data connection.\r\n')
        self.start_datasock()
        while True:
            data = self.datasock.recv(1024)
            if not data:
                break
            fo.write(data)
        fo.close()
        self.stop_datasock()
        self.conn.send('226 Transfer complete.\r\n')

    def SIZE(self, cmd):
        self.conn.send('213 0\r\n')
        #self.conn.send('200 OK.\r\n')


class FTPserver(threading.Thread):

    def __init__(self, ip='127.0.0.1', port=21, path='/tmp/ftp', can_delete=False):
        if not os.path.exists(path):
            os.mkdir(path)
        self.ftp_ip = ip
        self.ftp_port = port
        self.ftp_path = path
        self.can_delete = can_delete
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((ip, port))
        threading.Thread.__init__(self)
 
    def run(self):
        self.sock.listen(5)
        while True:
            th = FTPserverThread(self.sock.accept(), ftp_server=self)
            th.daemon = True
            th.start()
 
    def stop(self):
        self.sock.close()


if __name__ == '__main__':
    import sys
    ip = '127.0.0.1'
    port = 2121
    if len(sys.argv) > 1:
        if '.' in sys.argv[1]:
            ip = sys.argv[1]
        else:
            port = int(sys.argv[1])
    if len(sys.argv) > 2:
        port = int(sys.argv[2])
    ftp = FTPserver(ip=ip, port=port)
    ftp.daemon = True
    try:
        ftp.start()
        raw_input('Enter to quit...\n')
    except KeyboardInterrupt:
        pass
    finally:
        ftp.stop()
        print 'Bye.'
