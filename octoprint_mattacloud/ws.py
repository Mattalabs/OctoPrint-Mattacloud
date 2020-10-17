import json
import logging

import websocket

_logger = logging.getLogger("octoprint.plugins.mattacloud")


class Socket():
    def __init__(self, on_open, on_message, on_close, on_error, url, token):
        self.socket = websocket.WebSocketApp(url,
                                             on_open=on_open,
                                             on_message=on_message,
                                             on_close=on_close,
                                             on_error=on_error,
                                             header=[
                                                 "authorization: token {}".format(token)
                                             ]
                                             )

    def on_error(self, error):
        # TODO: handle websocket errors
        _logger.error("Socket on_error: %s", error)

    def on_close(self):
        # TODO: handle websocket errors
        _logger.debug("Closing the websocket...")
        self.disconnect()

    def run(self):
        try:
            self.socket.run_forever()
        except Exception as e:
            _logger.error("Socket run: %s", e)
            pass

    def send_msg(self, msg):
        try:
            if isinstance(msg, dict):
                msg = json.dumps(msg)
            if self.connected() and self.socket is not None:
                self.socket.send(msg)
        except Exception as e:
            _logger.error("Socket send_msg: %s", e)
            pass

    def connected(self):
        return self.socket.sock and self.socket.sock.connected

    def connect(self, on_message, on_close, url, token):
        self.socket = websocket.WebSocketApp(url,
                                             on_message=on_message,
                                             on_close=on_close,
                                             on_error=self.on_error,
                                             header=[
                                                 "authorization: token {}".format(token)
                                             ]
                                             )

    def disconnect(self):
        _logger.debug("Disconnecting the websocket...")
        self.socket.keep_running = False
        self.socket.close()
        _logger.debug("The websocket has been closed.")
