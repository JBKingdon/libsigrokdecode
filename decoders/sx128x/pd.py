##
## This file is part of the libsigrokdecode project.
##
## Copyright (C) 2014 Jens Steinhauser <jens.steinhauser@gmail.com>
## Copyright (C) 2022 James Kingdon
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, see <http://www.gnu.org/licenses/>.
##

import sigrokdecode as srd

class ChannelError(Exception):
    pass

# sx1280 status combines the current mode and the status of the last command

sx1280_status_modes = {
    2 : 'STDBY_RC',
    3 : 'STDBY_XOSC',
    4 : 'FS',
    5 : 'RX',
    6 : 'TX',
}

sx1280_status_status = {
    1 : 'CMD PROCESSED',
    2 : 'DATA AVAIL',
    3 : 'CMD TIMEOUT',
    4 : 'CMD P ERROR',
    5 : 'CMD EX FAIL',
    6 : 'CMD TX DONE'
}

regs = {
#   addr: ('name',        size)
    0x00: ('TODO',      1),
}

# typedef enum RadioCommands_u
# {
#     SX1280_RADIO_WRITE_REGISTER = 0x18,
#     SX1280_RADIO_READ_REGISTER = 0x19,
#     SX1280_RADIO_WRITE_BUFFER = 0x1A,
#     SX1280_RADIO_READ_BUFFER = 0x1B,
#     SX1280_RADIO_SET_SLEEP = 0x84,
#     SX1280_RADIO_SET_STANDBY = 0x80,
#     SX1280_RADIO_SET_FS = 0xC1,
#     SX1280_RADIO_SET_TX = 0x83,
#     SX1280_RADIO_SET_RXDUTYCYCLE = 0x94,
#     SX1280_RADIO_SET_CAD = 0xC5,
#     SX1280_RADIO_SET_TXCONTINUOUSWAVE = 0xD1,
#     SX1280_RADIO_SET_TXCONTINUOUSPREAMBLE = 0xD2,
#     SX1280_RADIO_SET_PACKETTYPE = 0x8A,
#     SX1280_RADIO_GET_PACKETTYPE = 0x03,
#     SX1280_RADIO_SET_TXPARAMS = 0x8E,
#     SX1280_RADIO_SET_CADPARAMS = 0x88,
#     SX1280_RADIO_SET_BUFFERBASEADDRESS = 0x8F,
#     SX1280_RADIO_SET_MODULATIONPARAMS = 0x8B,
#     SX1280_RADIO_SET_PACKETPARAMS = 0x8C,
#     SX1280_RADIO_GET_RXBUFFERSTATUS = 0x17,
#     SX1280_RADIO_GET_RSSIINST = 0x1F,
#     SX1280_RADIO_SET_DIOIRQPARAMS = 0x8D,
#     SX1280_RADIO_GET_IRQSTATUS = 0x15,
#     SX1280_RADIO_CALIBRATE = 0x89,
#     SX1280_RADIO_SET_REGULATORMODE = 0x96,
#     SX1280_RADIO_SET_SAVECONTEXT = 0xD5,
#     SX1280_RADIO_SET_AUTOTX = 0x98,
#     SX1280_RADIO_SET_AUTOFS = 0x9E,
#     SX1280_RADIO_SET_LONGPREAMBLE = 0x9B,
#     SX1280_RADIO_SET_UARTSPEED = 0x9D,
#     SX1280_RADIO_SET_RANGING_ROLE = 0xA3,
# } SX1280_RadioCommands_t;

CMD_GET_PACKET_STATUS = 0x1D

sx1280_commands = {
    # cmd   name            # number of extra bytes in command
    0x1B: ('READ BUF',       3),
    0x1D: ('GET PKT STATUS', 3),
    0x82: ('SET RX',         3),
    0x86: ('SET FREQ',       3),
    0x97: ('CLR IRQSTATUS',  2),
    0xC0: ('GET STATUS',     1),


}

class Decoder(srd.Decoder):
    api_version = 3
    id = 'sx128x'
    name = 'sx128x'
    longname = 'Semtech sx128x'
    desc = '2.4GHz Lora Radio'
    license = 'gplv2+'
    inputs = ['spi']
    outputs = []
    tags = ['IC', 'Wireless/RF']
    options = (
        {'id': 'chip', 'desc': 'Chip type',
            'default': 'sx1280', 'values': ('sx1280', 'somethingElse')},
    )
    annotations = (
        # Sent from the host to the chip.
        ('cmd', 'Commands sent to the device'),
        ('tx-data', 'Payload sent to the device'),

        # Returned by the chip.
        ('register', 'Registers read from the device'),
        ('rx-data', 'Payload read from the device'),

        ('warning', 'Warnings'),
    )
    ann_cmd = 0
    ann_tx = 1
    ann_reg = 2
    ann_rx = 3
    ann_warn = 4
    annotation_rows = (
        ('commands', 'Commands', (ann_cmd, ann_tx)),
        ('responses', 'Responses', (ann_reg, ann_rx)),
        ('warnings', 'Warnings', (ann_warn,)),
    )

    def __init__(self):
        self.reset()

    def reset(self):
        self.next()
        self.requirements_met = True
        self.cs_was_released = False

    def start(self):
        self.out_ann = self.register(srd.OUTPUT_ANN)
        # if self.options['chip'] == 'xn297':
        #     regs.update(xn297_regs)

    def warn(self, pos, msg):
        '''Put a warning message 'msg' at 'pos'.'''
        self.put(pos[0], pos[1], self.out_ann, [self.ann_warn, [msg]])

    def putp(self, pos, ann, msg):
        '''Put an annotation message 'msg' at 'pos'.'''
        self.put(pos[0], pos[1], self.out_ann, [ann, [msg]])

    def next(self):
        '''Resets the decoder after a complete command was decoded.'''
        # 'True' for the first byte after CS went low.
        self.first = True

        # The current command, and the minimum and maximum number
        # of data bytes to follow.
        self.cmd = None
        self.cmdInt = 0
        self.min = 0
        self.max = 0

        # Used to collect the bytes after the command byte
        # (and the start/end sample number).
        self.mb = []
        self.mb_s = -1
        self.mb_e = -1

    def mosi_bytes(self):
        '''Returns the collected MOSI bytes of a multi byte command.'''
        return [b[0] for b in self.mb]

    def miso_bytes(self):
        '''Returns the collected MISO bytes of a multi byte command.'''
        return [b[1] for b in self.mb]

    def decode_command(self, pos, b):
        '''Decodes the command byte 'b' at position 'pos' and prepares
        the decoding of the following data bytes.'''
        c = self.parse_command(b)
        if c is None:
            self.warn(pos, 'unknown command')
            return

        self.cmd, self.dat, self.min, self.max = c
        self.cmdInt = b

        if self.min > 1:
            # Don't output anything now, the command is merged with
            # the data bytes following it.
            self.mb_s = pos[0]
        else:
            self.putp(pos, self.ann_cmd, self.format_command())

    def format_command(self):
        '''Returns the label for the current command.'''
        if self.cmd == 'R_REGISTER':
            reg = regs[self.dat][0] if self.dat in regs else 'unknown register'
            return 'Cmd R_REGISTER "{}"'.format(reg)
        else:
            # return 'Cmd {}'.format(self.cmd)
            return self.cmd

    def parse_command(self, b):
        '''Parses the command byte.

        Returns a tuple consisting of:
        - the name of the command
        - additional data needed to dissect the following bytes
        - minimum number of following bytes
        - maximum number of following bytes
        '''

        #if (b & 0xe0) in (0b00000000, 0b00100000):
            #c = 'R_REGISTER' if not (b & 0xe0) else 'W_REGISTER'
            #d = b & 0x1f
            #m = regs[d][1] if d in regs else 1
            #return (c, d, 1, m)

        if b in sx1280_commands:
            commandName   = sx1280_commands[b][0]
            commandLength = sx1280_commands[b][1]
            return (commandName, None, commandLength, 252)  # max probably needs refinement

        # TODO Add more commands

    def decode_register(self, pos, ann, regid, data):
        '''Decodes a register.

        pos   -- start and end sample numbers of the register
        ann   -- is the annotation number that is used to output the register.
        regid -- may be either an integer used as a key for the 'regs'
                 dictionary, or a string directly containing a register name.'
        data  -- is the register content.
        '''

        if type(regid) == int:
            # Get the name of the register.
            if regid not in regs:
                self.warn(pos, 'unknown register')
                return
            name = regs[regid][0]
        else:
            name = regid

        # Multi byte register come LSByte first.
        data = reversed(data)

        if self.cmd == 'W_REGISTER' and ann == self.ann_cmd:
            # The 'W_REGISTER' command is merged with the following byte(s).
            label = '{}: {}'.format(self.format_command(), name)
        else:
            label = 'Reg {}'.format(name)

        if name == 'STATUS':
            # Need to extract mode and command status bits
            statusByte = next(data)
            statusMode = (statusByte & 0b11100000) >> 5
            statusCmdStatus = (statusByte &0b00011100) >> 2
            # TODO convert numbers to text descriptions
            if statusMode in sx1280_status_modes:
                smText = sx1280_status_modes[statusMode]
            else:
                smText = '{}?'.format(statusMode)

            if statusCmdStatus in sx1280_status_status:
                sStatusText = sx1280_status_status[statusCmdStatus]
            else:
                sStatusText = '{}?'.format(statusCmdStatus)

            text = '{}, {}'.format(smText, sStatusText)
            self.putp(pos, ann, text)
            self.end_of_status_pos = pos[1]

            if statusCmdStatus in (3,4,5):
                self.putp(pos, self.ann_warn, 'Prev CMD FAILED!')

        else:
            self.decode_mb_data(pos, ann, data, label, True)


    def decode_mb_data(self, pos, ann, data, label, always_hex):
        '''Decodes the data bytes 'data' of a multibyte command at position
        'pos'. The decoded data is prefixed with 'label'. If 'always_hex' is
        True, all bytes are decoded as hex codes, otherwise only non
        printable characters are escaped.'''

        if always_hex:
            def escape(b):
                return '{:02X}'.format(b)
        else:
            def escape(b):
                c = chr(b)
                if not str.isprintable(c):
                    return '\\x{:02X}'.format(b)
                return c

        data = ''.join([escape(b) for b in data])
        text = '{} = "{}"'.format(label, data)
        self.putp(pos, ann, text)

    def finish_command(self, pos):
        '''Decodes the remaining data bytes at position 'pos'.'''

        self.putp(pos, self.ann_cmd, self.cmd)

        # Commands that return values need extra handling
        if self.cmdInt == CMD_GET_PACKET_STATUS:
            # bytes 2 through 6 are the result
            # For Lora:
            #   byte2 is rssiSync
            #   byte3 is snr
            # indexes are off by one because the first byte isn't saved
            rssi = -(self.miso_bytes()[1] / 2)
            snr = self.miso_bytes()[2] / 4
            text = 'RSSI {}, SNR {}'.format(rssi, snr)
            self.putp((self.end_of_status_pos,pos[1]), self.ann_reg, text)


        # if self.cmd == 'R_REGISTER':
        #     self.decode_register(pos, self.ann_reg,
        #                          self.dat, self.miso_bytes())
        # elif self.cmd == 'W_REGISTER':
        #     self.decode_register(pos, self.ann_cmd,
        #                          self.dat, self.mosi_bytes())
        # elif self.cmd == 'R_RX_PAYLOAD':
        #     self.decode_mb_data(pos, self.ann_rx,
        #                         self.miso_bytes(), 'RX payload', False)
        # elif (self.cmd == 'W_TX_PAYLOAD' or
        #       self.cmd == 'W_TX_PAYLOAD_NOACK'):
        #     self.decode_mb_data(pos, self.ann_tx,
        #                         self.mosi_bytes(), 'TX payload', False)
        # elif self.cmd == 'W_ACK_PAYLOAD':
        #     lbl = 'ACK payload for pipe {}'.format(self.dat)
        #     self.decode_mb_data(pos, self.ann_tx,
        #                         self.mosi_bytes(), lbl, False)
        # elif self.cmd == 'R_RX_PL_WID':
        #     msg = 'Payload width = {}'.format(self.mb[0][1])
        #     self.putp(pos, self.ann_reg, msg)
        # elif self.cmd == 'ACTIVATE':
        #     self.putp(pos, self.ann_cmd, self.format_command())
        #     if self.mosi_bytes()[0] != 0x73:
        #         self.warn(pos, 'wrong data for "ACTIVATE" command')

    def decode(self, ss, es, data):
        if not self.requirements_met:
            return

        ptype, data1, data2 = data

        if ptype == 'CS-CHANGE':
            if data1 is None:
                if data2 is None:
                    self.requirements_met = False
                    raise ChannelError('CS# pin required.')
                elif data2 == 1:
                    self.cs_was_released = True

            if data1 == 0 and data2 == 1:
                # Rising edge, the complete command is transmitted, process
                # the bytes that were send after the command byte.
                if self.cmd:
                    # Check if we got the minimum number of data bytes
                    # after the command byte.
                    if len(self.mb) < self.min:
                        self.warn((ss, ss), 'missing data bytes')
                    elif self.mb:
                        self.finish_command((self.mb_s, self.mb_e))

                self.next()
                self.cs_was_released = True
        elif ptype == 'DATA' and self.cs_was_released:
            mosi, miso = data1, data2
            pos = (ss, es)

            if miso is None or mosi is None:
                self.requirements_met = False
                raise ChannelError('Both MISO and MOSI pins required.')

            if self.first:
                self.first = False
                # First MOSI byte is always the command.
                self.decode_command(pos, mosi)
                # First MISO byte is always the status register.
                self.decode_register(pos, self.ann_reg, 'STATUS', [miso])
            else:
                if not self.cmd or len(self.mb) >= self.max:
                    self.warn(pos, 'excess byte')
                else:
                    # Collect the bytes after the command byte.
                    if self.mb_s == -1:
                        self.mb_s = ss
                    self.mb_e = es
                    self.mb.append((mosi, miso))
