# -*- coding: utf-8 -*-
#
# Copyright © Spyder Project Contributors
# Licensed under the terms of the MIT License
# (see spyder/__init__.py for details)

"""
In addition to the remote_call mechanism implemented in CommBase:
 - Send a message to a debugging kernel
"""
import logging
import pickle

from qtpy.QtCore import QEventLoop, QObject, QTimer, Signal

from spyder_kernels.comms.commbase import CommBase
from spyder.py3compat import TimeoutError

logger = logging.getLogger(__name__)


class KernelComm(CommBase, QObject):
    """
    Class with the necessary attributes and methods to handle
    communications with a console.
    """

    _sig_got_reply = Signal()
    sig_debugging = Signal(bool)
    sig_exception_occurred = Signal(str, bool)

    def __init__(self):
        super(KernelComm, self).__init__()

        self.kernel_client = None
        self._debugging = False

        self.register_call_handler(
            'set_debug_state', self._handle_debug_state)
        self.register_call_handler(
            '_async_error', self._async_error)

    def set_kernel_client(self, kernel_client):
        """Register new kernel client and open comm."""
        self._register_comm(
            # Create new comm and send the highest protocol
            kernel_client.comm_manager.new_comm(self._comm_name, data={
                'pickle_protocol': pickle.HIGHEST_PROTOCOL}))
        self.kernel_client = kernel_client

    def remote_call(self, interrupt=False, blocking=False, callback=None,
                    comm_id=None):
        """Get a handler for remote calls."""
        return super(KernelComm, self).remote_call(
            interrupt=interrupt, blocking=blocking, callback=callback,
            comm_id=comm_id)

    # ---- Private -----
    def _get_call_return_value(self, call_dict):
        """
        Interupt the kernel if needed.
        """
        settings = call_dict['settings']
        if 'interrupt' in settings and settings['interrupt']:
            self._signal_update_kernel()

        return super(KernelComm, self)._get_call_return_value(
            call_dict)

    def _signal_update_kernel(self):
        """Interrupt the kernel to give a chance to read other messages."""
        self._pdb_update()

    def _pdb_update(self):
        """
        Update by sending an input to pdb.
        """
        if self._debugging and self.kernel_client:
            cmd = (u"!get_ipython().kernel.frontend_comm" +
                   ".remote_call(blocking=True).pong()")
            self.kernel_client.input(cmd)

    def _handle_debug_state(self, is_debugging):
        """Update the debug state."""
        self._debugging = is_debugging
        self.sig_debugging.emit(is_debugging)

    def _wait_reply(self, call_id, call_name, timeout):
        """Wait for the other side reply."""
        if call_id in self._reply_inbox:
            return

        # Create event loop to wait with
        wait_loop = QEventLoop()
        self._sig_got_reply.connect(wait_loop.quit)
        wait_timeout = QTimer()
        wait_timeout.setSingleShot(True)
        wait_timeout.timeout.connect(wait_loop.quit)

        # Wait until the kernel returns the value
        wait_timeout.start(timeout * 1000)
        while len(self._reply_waitlist) > 0:
            if not wait_timeout.isActive():
                self._sig_got_reply.disconnect(wait_loop.quit)
                if call_id in self._reply_waitlist:
                    raise TimeoutError(
                        "Timeout while waiting for {}".format(
                            self._reply_waitlist))
                return
            wait_loop.exec_()

        wait_timeout.stop()
        self._sig_got_reply.disconnect(wait_loop.quit)

    def _handle_remote_call_reply(self, msg_dict, buffer, load_exception):
        """
        A blocking call received a reply.
        """
        super(KernelComm, self)._handle_remote_call_reply(
            msg_dict, buffer, load_exception)
        self._sig_got_reply.emit()

    def _async_error(self, error_wrapper):
        """
        Handle an error that was raised on the other side and sent back.
        """
        for line in error_wrapper.format_error():
            self.sig_exception_occurred.emit(line, True)
