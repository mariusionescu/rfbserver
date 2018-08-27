from sys import stdout
from base64 import b64encode, b64decode
import struct
import time
import threading

from twisted.application.strports import listen
from twisted.internet import reactor
from twisted.internet.protocol import Protocol, Factory
from twisted.python import log

import txws
import wx

import ScreenShotWX as ssw
import Image
import ImageChops

log.startLogging(stdout)
thisApp = wx.App(redirect=False)


def imagetopil(image):
    """
    Convert wx.Image to PIL Image.
    """
    w, h = image.GetSize()
    data = image.GetData()

    redImage = Image.new("L", (w, h))
    redImage.fromstring(data[0::3])
    greenImage = Image.new("L", (w, h))
    greenImage.fromstring(data[1::3])
    blueImage = Image.new("L", (w, h))
    blueImage.fromstring(data[2::3])

    if image.HasAlpha():
        alphaImage = Image.new("L", (w, h))
        alphaImage.fromstring(image.GetAlphaData())
        pil = Image.merge('RGB', (redImage, greenImage, blueImage, alphaImage))
    else:
        pil = Image.merge('RGB', (blueImage, greenImage, redImage))
    return pil


CONNECTION = None


class ScreenRFB(threading.Thread):
    def run(self):
        while 1:
            screen_img = ssw.ScreenCapture((0, 0), (640, 480))
            _img = imagetopil(screen_img.ConvertToImage())
            time.sleep(0.1)

            if CONNECTION and CONNECTION.next_state == 'command_dispatcher':

                screen_img = ssw.ScreenCapture((0, 0), (640, 480))
                img = imagetopil(screen_img.ConvertToImage())

                diff = ImageChops.difference(img, _img)
                _b = diff.getbbox()

                if _b:
                    x_pos1, y_pos1, x_pos2, y_pos2 = diff.getbbox()
                    _diff = diff.crop((x_pos1, y_pos1, x_pos2, y_pos2))
                    CONNECTION.update_frame_buffer(_diff, x_pos1, y_pos1)


class RFBProtocol(Protocol):
    rfb_protocol = 'RFB 003.008'
    states = {
        'protocol_version': 'connectionMade',
        'security': 'auth_handshake',
        'security_results': 'security_results',
        'server_init': 'server_init',
        'command_dispatcher': 'command_dispatcher'
    }
    next_state = 'protocol_version'

    def connectionMade(self):
        global CONNECTION
        print 'Connection made'
        self.transport.write('%s\n' % self.rfb_protocol)
        self.next_state = 'security'
        CONNECTION = self

    def dataReceived(self, data):
        run = getattr(self, self.states[self.next_state])
        run(data)

    def auth_handshake(self, data):
        print 'Authenticating...'
        buf = struct.pack("!B", 1)
        buf += struct.pack("!B", 1)
        self.transport.write(buf)
        self.next_state = 'security_results'

    def security_results(self, data):
        print 'Sending security results...'
        buf = struct.pack('!I', 0)
        self.transport.write(buf)
        self.next_state = 'server_init'

    def server_init(self, data):
        print 'Server init...'
        buf = struct.pack('!H', 640)   # height
        buf += struct.pack('!H', 480)  # width
        #
        buf += struct.pack('!B', 32)   # bits-per-pixel
        buf += struct.pack('!B', 24)   # depth
        buf += struct.pack('!B', 0)    # big-endian-flag
        buf += struct.pack('!B', 1)    # true-colour-flag
        buf += struct.pack('!H', 255)  # red-max
        buf += struct.pack('!H', 255)  # green-max
        buf += struct.pack('!H', 255)  # blue-max
        buf += struct.pack('!B', 16)   # red-shift 11
        buf += struct.pack('!B', 5)    # green-shift 0
        buf += struct.pack('!B', 0)    # blue-shift 5
        buf += struct.pack('x')        # padding
        buf += struct.pack('x')        # padding
        buf += struct.pack('x')        # padding
        #
        buf += struct.pack('!I', 1)
        buf += struct.pack('!s', 'a')
        self.transport.write(buf)
        self.next_state = 'command_dispatcher'

    def command_dispatcher(self, data):
        message_type = struct.unpack('!B', data[0])[0]

        if message_type == 3:
            message_type, incremental, x, y, width, height = struct.unpack('!BBHHHH', data)
            screen_img = ssw.ScreenCapture((0, 0), (640, 480))
            img = imagetopil(screen_img.ConvertToImage())

            self.update_frame_buffer(img, 0, 0)

        if message_type == 4:
            print 'KEY', message_type
            screen_img = ssw.ScreenCapture((0, 0), (640, 480))
            img = imagetopil(screen_img.ConvertToImage())

            self.update_frame_buffer(img, 0, 0)

    def update_frame_buffer(self, img, x_pos, y_pos):
        # FrameBufferUpdate
        buf = struct.pack('!B', 0)
        buf += struct.pack('x')
        buf += struct.pack('!H', 1)
        buf += struct.pack('H', x_pos)
        buf += struct.pack('!H', y_pos)
        buf += struct.pack('!H', img.size[0])
        buf += struct.pack('!H', img.size[1])
        buf += struct.pack('!i', 0)
        self.transport.write(buf)

        buf = img.tostring('raw', 'RGBX')
        print 'Image size:', len(buf)
        self.transport.write(buf)


class RFBFactory(Factory):
    protocol = RFBProtocol


txws.encoders = {
    "base64": b64encode,
    "binary, base64": b64encode,
}

txws.decoders = {
    "base64": b64decode,
    "binary, base64": b64decode,
}

port = listen("tcp:8080", txws.WebSocketFactory(RFBFactory()))
reactor.run()
