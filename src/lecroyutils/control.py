import re
from enum import Enum
from typing import AnyStr, Dict, Union

import vxi11

from .data import LecroyScopeData

VBSValue = Union[str, int, float]


def _escape(value: VBSValue) -> str:
    if isinstance(value, str):
        return f'"{value}"'
    return repr(value)


def _unpack_response(res: str) -> str:
    if res[:4].upper() == 'VBS ':
        return res[4:]
    return res


class TriggerMode(Enum):
    stopped = 'Stopped'
    single = 'Single'
    normal = 'Normal'
    auto = 'Auto'


class TriggerType(Enum):
    edge = 'EDGE'
    width = 'WIDTH'
    qualified = 'QUALIFIED'
    window = 'WINDOW'
    internal = 'INTERNAL'
    tv = 'TV'
    pattern = 'PATTERN'


class LecroyComm:
    def __init__(self, ip: str):
        self.scope = vxi11.Instrument(ip)

    def action(self, action: str):
        self.scope.write(f'VBS \'{action}\'')

    def method(self, method: str, *args: VBSValue, timeout: float = None) -> str:
        old_timeout = self.scope.timeout
        if timeout is not None:
            self.scope.timeout = timeout + old_timeout

        arg_string = ', '.join(map(_escape, args))
        self.scope.write(f'VBS? \'return = {method}({arg_string})\'')
        response = _unpack_response(self.scope.read())

        self.scope.timeout = old_timeout
        return response

    def set(self, var: str, value: VBSValue):
        self.scope.write(f'VBS \'{var} = {_escape(value)}\'')

    def read(self, var: str) -> str:
        self.scope.write(f'VBS? \'return = {var}\'')
        return _unpack_response(self.scope.read())

    def wait_opc(self):
        self.scope.write("*OPC?")
        opc = self.scope.read()
        assert opc == '1' or '*OPC 1'


class LecroyChannel:
    def __init__(self, comm: LecroyComm, source: str):
        """Inits the scope channel

        Args:
            comm (LecroyComm): Communication adapter
            source (str): Channel source
        """
        self.name = source.upper()
        self.comm = comm

    @property
    def coupling(self) -> str:
        return self.comm.read('app.acquisition.' + self.name + '.Coupling')

    @coupling.setter
    def coupling(self, coupling: str = 'DC50'):
        """Set the channel coupling of the source specified

        Args:
            coupling (str, optional): Coupling is typically 'DC50', 'DC1M', 'AC1M', 'GND','DC100k'. Defaults to 'DC50'.

        Raises:
            Exception: on invalid Coupling
        """
        if coupling.upper() not in ['DC50', 'DC1M', 'AC1M', 'GND', 'DC100k']:
            raise Exception(f'Invalid Coupling: {coupling}')

        self.comm.action('app.acquisition.' + self.name + '.Coupling = "' + coupling.upper() + '"')

    @property
    def vertical_offset(self) -> float:
        return float(self.comm.read('app.acquisition.' + self.name + '.VerOffset'))

    @vertical_offset.setter
    def vertical_offset(self, offset: float = 0.0):
        """Sets the vertical offset of the channel

        Args:
            offset (float, optional): Vertical offset. Defaults to 0.0.

        """
        self.comm.action('app.acquisition.' + self.name + '.VerOffset = ' + str(offset))

    @property
    def vertical_scale(self) -> float:
        """Get Vertical scale of the DSO

        Args:
            source (str): Channel source

        Returns:
            float: Vertical scale value
        """
        return float(self.comm.read('app.acquisition.' + self.name + '.VerScale'))

    @vertical_scale.setter
    def vertical_scale(self, ver_scale: float = 0.001):
        """Set vertical scale for the channel

        Args:
            ver_scale (float, optional): vertical scale. Defaults to 0.001.
        """
        self.comm.action('app.Acquisition.' + self.name + '.VerScale = ' + str(ver_scale))

    def set_view(self, view: bool = True):
        """Set view on or off

        Args:
            channel (str): Analog or Digital source
            view (bool, optional): True sets view ON. Defaults to True.
            digitalGroup (str, optional): This is ignored if source is analog. If it is a digital source, specifies the group it belongs to. Defaults to 'Digital1'.

        Raises:
            ParametersError: on invalid source or group
        """
        self.comm.action('app.acquisition.' + self.name.upper() + '.view = ' + str(view))


class LecroyScope:
    """
    Allows to control a lecroy oscilloscopes per vxi11.

    The remote connection settings in the oscilloscope must be set to vxi11.
    """

    def __init__(self, ip: str) -> None:
        """
        Connects to an oscilloscope defined by the given ip.

        :param ip: the ip address of the oscilloscope to connect to
        """
        self.available_channels = []
        self.available_parameters = []

        self._comm = LecroyComm(ip)
        self._parse_available_resources()
        self.chan: dict[str, LecroyChannel] = {v: LecroyChannel(self._comm, v) for v in self.available_channels}

    def is_idle(self) -> str:
        return self._comm.method('app.WaitUntilIdle', 5)

    def _parse_available_resources(self):
        for resource in self._comm.read('app.ExecsNameAll').split(','):
            if re.match(r"C\d.*", resource):
                self.available_channels.append(resource)
            elif re.match(r"P\d.*", resource):
                self.available_parameters.append(resource)

    def check_source(self, source: str):
        # currently no digital channels supported
        self.check_channel(source)

    def check_channel(self, channel: str):
        if channel.upper() not in self.available_channels:
            raise Exception(f'Channel {channel} not available.')

    def check_parameter(self, parameter: str):
        if parameter.upper() not in self.available_parameters:
            raise Exception(f'Parameter {parameter} not available.')

    def acquire(self, timeout: float = 0.1, force=False) -> bool:
        return self._comm.method('app.Acquisition.acquire', timeout, force, timeout=timeout) == '1'

    @property
    def trigger_mode(self) -> TriggerMode:
        return TriggerMode(self._comm.read('app.Acquisition.TriggerMode'))

    @trigger_mode.setter
    def trigger_mode(self, mode: TriggerMode):
        self._comm.set('app.Acquisition.TriggerMode', mode.value)

    @property
    def trigger_source(self) -> str:
        return self._comm.read('app.Acquisition.Trigger.Source')

    @trigger_source.setter
    def trigger_source(self, source: str):
        if source.upper() not in ['EXT', 'LINE']:
            self.check_source(source)
        self._comm.set('app.Acquisition.Trigger.Source', source.upper())

    @property
    def trigger_type(self) -> TriggerType:
        return TriggerType(self._comm.read('app.Acquisition.Trigger.Type').upper())

    @trigger_type.setter
    def trigger_type(self, new_type: TriggerType):
        self._comm.set('app.Acquisition.Trigger.Type', new_type.value)

    @property
    def trigger_level(self) -> str:
        return self._comm.read(f'app.Acquisition.Trigger.{self.trigger_source}.Level')

    @trigger_level.setter
    def trigger_level(self, level: VBSValue):
        source = self.trigger_source
        if source.upper() not in ['EXT', *self.available_channels]:
            raise NotImplementedError(f'Setting of trigger_level not supported for current trigger_source ({source}).')

        self._comm.set(f'app.Acquisition.Trigger.{source}.Level', level)

    def clear_statistics(self):
        self._comm.action('app.Measure.ClearSweeps')

    def statistics(self, parameter: str) -> Dict[str, str]:
        self.check_parameter(parameter)
        return {
            'last': self._comm.read(f'app.Measure.{parameter}.last.Result.Value'),
            'max': self._comm.read(f'app.Measure.{parameter}.max.Result.Value'),
            'mean': self._comm.read(f'app.Measure.{parameter}.mean.Result.Value'),
            'min': self._comm.read(f'app.Measure.{parameter}.min.Result.Value'),
            'num': self._comm.read(f'app.Measure.{parameter}.num.Result.Value'),
            'sdev': self._comm.read(f'app.Measure.{parameter}.sdev.Result.Value'),
            'status': self._comm.read(f'app.Measure.{parameter}.Out.Result.Status')
        }

    def _screenshot_raw(self) -> bytes:
        self._comm.scope.write(
            "HCSU DEV, PNG, FORMAT, PORTRAIT, BCKG, WHITE, DEST, REMOTE, PORT, NET, AREA, GRIDAREAONLY")
        self._comm.scope.write("SCDP")
        return self._comm.scope.read_raw()

    def save_screenshot(self, file_path: AnyStr):
        with open(file_path, 'wb') as f:
            f.write(self._screenshot_raw())

    def _waveform_raw(self, source: str) -> bytes:
        self.check_source(source)
        self._comm.scope.write(f'{source}:WF?')
        return self._comm.scope.read_raw()

    def waveform(self, source: str) -> LecroyScopeData:
        return LecroyScopeData(self._waveform_raw(source), source_desc=f'{source}-live')

    def save_waveform(self, source: str, file_path: AnyStr):
        with open(file_path, 'wb') as f:
            f.write(self._waveform_raw(source))

    def save_waveform_on_lecroy(self):
        self._comm.action('app.SaveRecall.Waveform.SaveFile')

    # Next methods are based on https://github.com/TeledyneLeCroy/lecroydso

    def recall_default_panel(self):
        """Recall the default setup of the DSO
        """
        self._comm.action('app.SaveRecall.Setup.DoRecallDefaultPanel')
        self._comm.wait_opc()

    def force_trigger(self):
        """Forces a trigger on the instrument
        """
        self._comm.scope.write('FRTR')

    @property
    def serial_number(self) -> str:
        """Get the serial number of the DSO

        Returns:
            str: Serial number as a string
        """
        return self._comm.read('app.SerialNumber')

    @property
    def instrument_model(self) -> str:
        """Gets the instrument model of the DSO

        Returns:
            str: Instrument model as a string
        """
        return self._comm.read('app.InstrumentModel')

    @property
    def firmware_version(self) -> str:
        """Gets the firmware version of the DSO

        Returns:
            str: Firmware version as string
        """
        return self._comm.read('app.FirmwareVersion')

    @property
    def horizontal_scale(self) -> float:
        """Gets the Horizontal scale
        Returns:
            [float]: horizontal scale value
        """
        hor_scale = float(self._comm.read('app.Acquisition.Horizontal.horscale'))
        return hor_scale

    @horizontal_scale.setter
    def horizontal_scale(self, hor_scale: float):
        """Sets the horizontal scale of the DSO
        Args:
            hor_scale (float): Horizontal scale value
        """
        self._comm.set('app.Acquisition.Horizontal.horscale', hor_scale)

    @property
    def horizontal_offset(self) -> float:
        """Gets the Horizontal offset

        Returns:
            [float]: horizontal offset value
        """
        hor_offset = float(self._comm.read('app.Acquisition.Horizontal.horoffset'))
        return hor_offset

    @horizontal_offset.setter
    def horizontal_offset(self, hor_offset: float = 0.0):
        """Set the Horizontal offset of the scope

        Args:
            hor_offset (float, optional): Horizontal offset value. Defaults to 0.0.
        """
        self._comm.set('app.Acquisition.Horizontal.horoffset', hor_offset)

    @property
    def sample_rate(self) -> float:
        """Gets the sample rate of the DSO

        Returns:
            float: Sample rate value
        """
        sample_rate = float(self._comm.read('app.Acquisition.Horizontal.samplerate'))
        return sample_rate

    @sample_rate.setter
    def sample_rate(self, sample_rate: float):
        """Set the sample rate to a specific value. This sets the DSO to FixedSampleRate
        memory mode.

        Args:
            sample_rate (float): sample rate value

        Raises:
            Exception: on invalid Sample rate
        """
        self.memory_mode = 'FIXEDSAMPLERATE'
        self._comm.set('app.Acquisition.Horizontal.samplerate', sample_rate)
        if self.sample_rate != float(sample_rate):
            raise Exception(f'Invalid Sample Rate: {sample_rate}')

    @property
    def memory_mode(self) -> str:
        """Gets the memory mode of the DSO

        Returns:
            str: Memory mode as a string
        """
        return self._comm.read('app.Acquisition.Horizontal.maximize')

    @memory_mode.setter
    def memory_mode(self, maximize: str = 'SetMaximumMemory'):
        """Set Memory mode of the DSO

        Args:
            maximize (str, optional): Possible values are SETMAXIMUMMEMORY|FIXEDSAMPLERATE. Defaults to 'SetMaximumMemory'.

        Raises:
            ParametersError: on invalid Memory mode
        """
        if maximize.upper() not in ['SETMAXIMUMMEMORY', 'FIXEDSAMPLERATE']:
            raise Exception(f'Invalid Memory mode: {maximize}')

        self._comm.set('app.Acquisition.Horizontal.maximize', maximize.upper())

    @property
    def trigger_coupling(self) -> str:
        source = self.trigger_source

        if source.upper() not in ['EXT', *self.available_channels]:
            raise Exception(f'Invalid channel: {source}')

        return self._comm.read(f'app.Acquisition.Trigger.{source.upper()}.Coupling')

    @trigger_coupling.setter
    def trigger_coupling(self, coupling: str):
        """Set the Trigger Coupling of the DSO

        Args:
            coupling (str): Sets the coupling.

        Raises:
            Exception: Invalid channel or coupling
        """
        source = self.trigger_source

        if source.upper() not in ['EXT', *self.available_channels]:
            raise Exception(f'Invalid channel: {source}')

        if coupling.upper() not in ('DC', 'AC', 'LFREJ', 'HFREJ'):
            raise Exception(f'Trigger Coupling not valid: {coupling}')

        self._comm.action('app.Acquisition.Trigger.' + source.upper() + '.Coupling = "' + coupling.upper() + '"')

    @property
    def trigger_impedance(self) -> str:
        source = self.trigger_source

        if source.upper() not in ['EXT', *self.available_channels]:
            raise Exception(f'Invalid channel: {source}')

        return self._comm.read(f'app.Acquisition.Trigger.{source.upper()}.InputImpedance')

    @trigger_impedance.setter
    def trigger_impedance(self, impedance: str):
        """Set the Trigger Impedance of the DSO

        Args:
            impedance (str): Sets the impedance.

        Raises:
            Exception: Invalid channel or impedance
        """
        source = self.trigger_source

        if source.upper() not in ['EXT', *self.available_channels]:
            raise Exception(f'Invalid channel: {source}')

        if impedance.upper() not in ('50', '1M'):
            raise Exception(f'Trigger Impedance not valid: {impedance}')

        self._comm.action('app.Acquisition.Trigger.' + source.upper() + '.InputImpedance = ' + impedance.upper() + '')