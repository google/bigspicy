# vim: set shiftwidth=2 softtabstop=2 ts=2 expandtab:
#
#    Copyright 2022 Google LLC
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        https://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import circuit
from datetime import datetime
import time
from spice_util import NumericalValue, SIUnitPrefix
from enum import Enum
import os
import re


SPLIT_KEEPING_PARAMS_RE = re.compile(r'(?<!=)\s+(?!=)')


class GeneralWhoopsieDaisy(Exception):
  pass


class SpiceInstance():

  def __init__(self):
    self.name = None
    self.connections = []
    self.params = []
    self.module_name = None


class SpiceSubckt():

  def __init__(self):
    self.name = None
    self.ports = []
    self.params = []
    self.instances = []


  def __repr__(self):
    return (f'spice subckt {self.name} ports {self.ports} params {self.params} '
            f'# instances {len(self.instances)}')


  def ToModule(self, design=None):
    """ Return a circuit.Module describing the netlist of this spice subcircuit.
    """
    module = circuit.Module()
    module.name = self.name
    
    # Since we're building this from a Spice .subckt definition, all ports are
    # inout and there are no buses. Right?
    for port in self.ports:
      module.GetOrCreatePort(port, width=1, direction=circuit.Port.Direction.INOUT)

    for param in self.params:
      key, value = param.split('=')
      module.default_parameters[key] = value

    for spice_inst in self.instances:
      instance = circuit.Instance()
      instance.name = spice_inst.name
      module.instances[instance.name] = instance
      instance.module_name = spice_inst.module_name

      for param in spice_inst.params:
        key, value = param.split('=')
        instance.parameters[key] = value

      # instance.module must be linked later.
      instance.module = None

      if instance.module is not None:
        for i, signal_name in enumerate(spice_inst.connections):
          signal = module.GetOrCreateSignal(signal_name, width=1)
          try:
            port_name = instance.module.port_order[i]
          except KeyError:
            raise KeyError(f'instance ports do not match module ports '
                           f'{instance.name} of {instance.module_name}')
          connection = circuit.Connection(port_name)
          connection.instance = instance
          connection.signal = signal
      else:
        for signal_name in spice_inst.connections:
          signal = module.GetOrCreateSignal(signal_name, width=1)
          instance.connections_by_order.append(signal)
    return module


class SpiceReader():
  """ A largely incomplete SPICE parser with one objective:
          1) extract the port order for spice definitions of modules (subckts)
  """
  class State(Enum):
    NONE = 0
    SUBCKT = 1
    INCLUDE = 2

  def __init__(self, headers_only=False):
    self.port_order_by_module = {}
    self.spice_files = set()
    self.headers_only = headers_only

    self.subckts = []

  @staticmethod
  def ResolvePathReference(source_file, path):
    path = path.lstrip('"\'')
    path = path.rstrip('"\'')

    if path.startswith('/'):
      return path

    relative_to = os.path.dirname(source_file)
    return os.path.normpath(os.path.join(relative_to, path))

  def ParseInclude(self, source_file_name, lines):
    line = lines[0]
    i = 1
    while i < len(lines):
      if line.startswith('+'):
        line += line[1:]
      i += 1

    tokens = line.lower().split()
    # Remove '.include' command which should be first token:
    remaining_tokens = ' '.join(tokens[1:])
    return SpiceReader.ResolvePathReference(source_file_name, remaining_tokens)

  def ParseSubckt(self, lines):
    if not lines:
      return

    ignore_tokens = {'params:'}
    module_name = None
    ports = []
    params = []
    instances = []

    def ParseLine(line):
      nonlocal module_name
      # God bless you, regular expressions:
      tokens = SPLIT_KEEPING_PARAMS_RE.split(line)
      tokens = list(filter(
          lambda x: x is not None and len(x) > 0 and x.lower() not in ignore_tokens,
          tokens))
      if not tokens:
        return
      if tokens[0].lower() == '.subckt':
        if len(tokens) < 2:
          raise GeneralWhoopsieDaisy('.subckt line should have module name')

        module_name = tokens[1]
        for token in tokens[2:]:
          if '=' in token:
            params.append(token)
          else:
            ports.append(token)

      if self.headers_only:
        # Ignore the internals of subckt definitions.
        return

      first_token = tokens[0].lower()
      if first_token.startswith('x'):
        # Instance. Find first param declaration or end of line:
        try:
          first_param = next(i for i, value in enumerate(tokens) if '=' in value)
        except StopIteration:
          first_param = len(tokens)

        spice_inst = SpiceInstance()
        spice_inst.name = tokens[0]
        spice_inst.module_name = tokens[first_param - 1]
        spice_inst.connections = tokens[1:first_param - 1]

        if first_param < len(tokens):
          spice_inst.params = tokens[first_param:]
        instances.append(spice_inst)
      elif first_token.startswith('r'):
        pass
      elif first_token.startswith('c'):
        pass
        
    line = ''
    i = 0
    while i < len(lines):
      next_line = lines[i].strip()
      if next_line.startswith('*'):
        i += 1
        continue
      if next_line.startswith('+'):
        line += next_line[1:]
        i += 1
        continue

      # Process previous, now concatenated, line.
      ParseLine(line)

      line = next_line
      i += 1

    self.port_order_by_module[module_name] = ports

    # Parse the last line.
    ParseLine(line)

    spice_subckt = None
    if not self.headers_only:
      spice_subckt = SpiceSubckt()
      spice_subckt.name = module_name
      spice_subckt.ports = ports
      spice_subckt.params = params
      spice_subckt.instances = instances
    return spice_subckt

  def ReadWithoutRecursing(self, file_name, included_files):
    if file_name in self.spice_files:
      return
    print(f'reading {file_name}')
    self.spice_files.add(file_name)

    state = SpiceReader.State.NONE
    lines = []

    with open(file_name) as f:
      for line in f:
        if not line:
          continue

        tokens = line.split()
        if not tokens:
          continue
        spice_command = tokens.pop(0).lower()

        if state == SpiceReader.State.SUBCKT:
          lines.append(line)
          if spice_command == '.ends':
            subckt = self.ParseSubckt(lines)
            lines = []
            state = SpiceReader.State.NONE
            if subckt:
              self.subckts.append(subckt)
          continue

        if state == SpiceReader.State.INCLUDE:
          lines.append(line)
          if line != '' and spice_command != '+':
            new_file_name = self.ParseInclude(file_name, lines)
            print(f'including spice file: {new_file_name}')
            included_files.add(new_file_name)
            state = SpiceReader.State.NONE
          continue

        if spice_command == '.include':
          lines = [line]
          state = SpiceReader.State.INCLUDE

        elif spice_command == '.subckt':
          lines = [line]
          state = SpiceReader.State.SUBCKT

  def Read(self, file_name):
    file_names = set([file_name])
    while file_names:
      file_name = file_names.pop()
      self.ReadWithoutRecursing(file_name, file_names)

  def Show(self):
    print('Read: ')
    for file_name in self.spice_files:
      print(f'\t{file_name}')
    print('Module definitions:')
    for module_name, port_order in self.port_order_by_module.items():
      ports = ', '.join(port_order)
      print(f'\t{module_name}: {ports}')


class SpiceWriter():
  def __init__(self, design, flatten=False):
    self.design = design
    self.default_connections = {
        'VSS': circuit.Signal('VSS'),
        'VDD': circuit.Signal('VDD'),
        'VGND': circuit.Signal('VGND'),
        'VPWR': circuit.Signal('VPWR'),
    }
    self.flatten = flatten
    self._ResetCounters()

  def _ResetCounters(self):
    self.num_resistors_named = 0
    self.num_capacitors_named = 0
    self.num_other_named = 0
    self.num_floating_nets = 0

  def ModulePortList(self, module):
    spice_port_list = []
    for port_name in module.port_order:
      port = module.ports[port_name]
      if port.signal.width == 1:
        spice_port_list.append(port_name)
      else:
        for x in range(port.signal.width):
          spice_port_list.append(f'{port_name}.{x}')
    return ' '.join(spice_port_list)

  def SpiceSignalName(self, signal_or_slice, index=None, prefix=None):
    if signal_or_slice is None:
      # The signal is probably disconnected; create a new floating node that
      # isn't connected to anything else and use that instead.
      name = f'no_conn_{self.num_floating_nets}'
      self.num_floating_nets += 1
      return name
    if isinstance(signal_or_slice, circuit.Signal):
      return signal_or_slice.name
    assert(isinstance(signal_or_slice, circuit.Slice))
    net_slice = signal_or_slice
    assert(net_slice.top == net_slice.bottom)
    index = net_slice.bottom
    signal_name = f'{net_slice.signal.name}.{index}'
    if prefix:
      signal_name = prefix + '_' + signal_name
    return signal_name

  def _MakeSpiceName(self, instance, additional_prefix=None):
    # NOTE(growly): It would be nice to store this with each instance after
    # generating it, to avoid conflicts between instance names and spice-
    # valid names (that e.g. start with an 'X'), but first we have to decide
    # if it makes sense to include that in the Circuit protobuf.

    def EnsurePrefix(string, prefix):
      if string.startswith(prefix):
        return string
      else:
        return f'{prefix}{string}'

    def InsertSpiceApprovedPrefix(string, prefix):
      if not prefix:
        return string
      return f'{string[0]}_{prefix}_{string[1:]}'

    existing_name = InsertSpiceApprovedPrefix(instance.name, additional_prefix)

    instance_name = ''
    # Special checks for spice primitives.
    if instance.module.name == circuit.RESISTOR.name:
      if existing_name:
        return EnsurePrefix(existing_name, 'R')
      instance_name = f'R{self.num_resistors_named}'
      self.num_resistors_named += 1
    elif instance.module.name == circuit.CAPACITOR.name:
      if existing_name:
        return EnsurePrefix(existing_name, 'C')
      instance_name = f'C{self.num_capacitors_named}'
    else:
      if existing_name:
        return EnsurePrefix(existing_name, 'X')
      instance_name = f'X{self.num_other_named}'
      self.num_other_named += 1

    return InsertSpiceApprovedPrefix(instance_name, additional_prefix)

  def SpiceInstantiation(self, instance, signal_map={}, prefix=None, generate_names=True):
    if instance.module_name in self.design.known_modules:
      module = self.design.known_modules[instance.module_name]
    else:
      module = self.design.external_modules[instance.module_name]
    connection_list = []
    if not module.port_order:
      print(f'warning: no port order for module {instance.module_name}, '
            f'instance {instance.name} will not be connected')
    for port_name in module.port_order:
      signal = None
      if port_name in instance.connections:
        connection = instance.connections[port_name]
        signal = connection.signal or connection.slice
      elif port_name in self.default_connections:
        signal = self.default_connections[port_name]

      spice_signal_name = self.SpiceSignalName(signal)
      if spice_signal_name in signal_map:
        spice_signal_name = signal_map[spice_signal_name]
      elif prefix:
        spice_signal_name = prefix + '_'  + spice_signal_name

      connection_list.append(spice_signal_name)

    connections = ' '.join(connection_list)
    type_name = ''
    instance_name = self._MakeSpiceName(
        instance, additional_prefix=prefix) if generate_names else instance.name
    skipped = None

    params = {}
    params.update(module.default_parameters)
    # Overwrite module parameters with any instance-specific ones.
    params.update(instance.parameters)

    # Special checks for spice primitives.
    if module.name == circuit.RESISTOR.name:
      params['R'] = instance.parameters['resistance'].XyceFormat()
      del params['resistance']
    elif module.name == circuit.CAPACITOR.name:
      capacitance = instance.parameters['capacitance']
      if capacitance == NumericalValue(0.0, None):
        # Do not write 0-value capacitances.
        skipped = 'because C=0'
      params['C'] = capacitance.XyceFormat()
      del params['capacitance']
    else:
      type_name = module.name 

    params_out = ' '.join('{}={}'.format(k, v) for k, v in params.items())
    out = f'** {instance}\n'
    instantiation = f'{instance_name} {connections} {type_name} {params_out}'
    if skipped:
      out += f'** {instantiation} [skipped {skipped}]'
    else:
      out += instantiation
    return out

  def FlattenedInstance(self, instance, prefix=None):
    module = instance.module
    
    signal_map = {}

    # TODO(growly): module params!

    for port_name in module.port_order:
      signal = None
      if port_name in instance.connections:
        connection = instance.connections[port_name]
        signal = connection.signal or connection.slice
      elif port_name in self.default_connections:
        signal = self.default_connections[port_name]

      internal_signal_name = self.SpiceSignalName(module.ports[port_name].signal)
      signal_map[internal_signal_name] = self.SpiceSignalName(signal)

    out = f'** replacing {instance.name} with the contents of {instance.module_name}\n'
    for child_instance in module.instances.values():
      # If it's a Module, it's internal, and we know the contents. Otherwise
      # it would be an ExternalModule.
      if type(child_instance.module) is circuit.Module:
        out += self.FlattenedInstance(child_instance, prefix=instance.name)
        continue

      out += self.SpiceInstantiation(child_instance, signal_map=signal_map,
                                     prefix=instance.name, generate_names=True) + '\n'
    return out

  def FormatInstances(self, instances, generate_names=False):
    out = ''
    for instance in instances:
      if self.flatten and type(instance.module) is circuit.Module:
        out += f'{self.FlattenedInstance(instance)}\n'
      else:
        out += f'{self.SpiceInstantiation(instance, generate_names=generate_names)}\n'
    return out

  def WriteRegion(self, file_name, region, generate_names=False):
    # Ports have to be defined somehow. For now let's assume we have some in
    # the subgraph. Ports also have to be sorted so that the thing that
    # instantiates the subckt understands it.
    # TODO(growly): Create a separate structure to keep track of this?
    instance_set = region.instances
    pins = region.OrderedWires()
    pin_names = []
    for pin in pins:
      if not isinstance(pin, circuit.Wire):
        raise NotImplementedError()
      pin_names.append(pin.SpiceName())

    instances = sorted(list(instance_set), key=lambda x: x.name)
    with open(file_name, 'w') as f:
      f.write('** SPICE netlist generated by bigspicy.py at '
              f'{datetime.utcnow().ctime()} UTC\n')
      f.write(f'** {len(instance_set)} instances; '
              f'{len(pins)} input/inout/output wires\n')

      # Need to keep some connections per instance disconnected if they're not in the subgraph
      f.write(f'.SUBCKT {region.name}\n')
      f.write('+ ' + ' '.join(pin_names) + '\n')

      f.write(self.FormatInstances(instances, generate_names=generate_names))

      f.write('.ENDS\n')

  def WriteTop(self, file_name):
    if not self.design.top:
      raise GeneralWhoopsieDaisy('no top module available')
    self.WriteModule(self.design.top, file_name)

  def WriteModule(self, module, file_name):
    with open(file_name, 'w') as f:
      f.write('** SPICE netlist generated by bigspicy.py at '
              f'{datetime.utcnow().ctime()} UTC\n')
      f.write(f'.SUBCKT {module.name}\n')
      f.write(f'+ {self.ModulePortList(module)}\n')
      f.write(self.FormatInstances(module.instances.values()))
      f.write('.ENDS\n')


# This becomes a capacitance between the given wire and ground.
class CapacitiveLoad:

  def __init__(self, wire, value=None):
    self.wire = wire
    self.value = value


class SimulatedDriver:

  def __init__(self, wire):
    self.wire = wire
    # Step input, sinusoid, etc.
    self.input_waveform = None


# This becomes a DC voltage source between the given wire and ground.
class DCVoltageSource:

  def __init__(self, wire, value=None):
    self.wire = wire
    # Voltage, in volts
    self.value = value

  def __repr__(self):
    return f'[dc source to {self.wire}]'


# VoltageProbe indicates to us to measure some value on some net.
class VoltageProbe:

  def __init__(self, wire):
    self.wire = wire
    self.name = f'V_probe_{wire.signal.name}_{wire.index}'


class DelayMeasurement:

  def __init__(self, source_wire, sink_wire):
    self.name = None
    # Source, a.k.a. trigger.
    self.source_wire = source_wire
    self.source_value = None
    # Sink, a.k.a. target.
    self.sink_wire = sink_wire
    self.sink_value = None
    

# TODO(growly): Merge 'DelayMeasurement' and 'Measurement', since they both
# model the .MEASURE command.
class Measurement:

  class MeasureType(Enum):
    MAX = 1
    MIN = 2
    WHEN = 3

  MEASURE_TYPE_TO_XYCE = {
      MeasureType.MAX: 'MAX',
      MeasureType.MIN: 'MIN',
      MeasureType.WHEN: 'WHEN',
  }

  def __init__(self, target_wire, measure_type):
    self.name = None
    self.target_wire = target_wire
    self.target_value = None
    self.measure_type = measure_type
    self.from_time = None


# This becomes a port between the wire and ground, used for Spice's N-Port
# Network analysis. It is unfortunate how overloaded "Port" is.
class Port:

  def __init__(self, wire, dc_bias=None):
    self.wire = wire
    # This might be a SweepParameter.
    self.dc_bias = dc_bias
    self.number = None
    # NumericalValue
    self.load_capacitance = None
    self.external_connections = None

  def __repr__(self):
    return f'[port-network port on {self.wire} num={self.number}]'


class SweepParameter:

  def __init__(self, name, low, high=None, step=None):
    self.name = name
    self.low = low
    self.high = high
    self.step = step

  def __repr__(self):
    return f'[spice parameter {self.name}: {self.values}]'


class FFTSpec:

  def __init__(self, wire, base_freq_hz=None, num_points=None,
               in_subcircuit=None):
    self.wire = wire
    self.base_freq_hz = base_freq_hz
    self.num_points = num_points
    self.format = 'UNORM'  # or NORM

    # To crudely indicate that this signal is part of the subcircuit in the
    # Spice test, this indicated the of a subcircuit instance we prefix 
    # when specifying which signal to FFT. This is a gross and I'm sad.
    # TODO(growly): Tidy up how spice tests are represented. Make consistent
    # how we indicate that a signal belongs to a subcircuit.
    self.in_subcircuit = in_subcircuit

  def SpiceLine(self):
    node_name = ''
    if self.in_subcircuit:
      node_name += self.in_subcircuit + ':'
    node_name += self.wire.SpiceName()
    line = f'.FFT V({node_name})'
    if self.base_freq_hz is not None:
      line += f' FREQ={self.base_freq_hz}'
    if self.num_points is not None:
      line += f' NP={int(self.num_points)}'
    if self.format:
      line += f' FORMAT={self.format}'
    return line


class InputWaveform:

  def __init__(self, wire, reference_wire):
    self.wire = wire
    self.reference_wire = reference_wire

class StepInput(InputWaveform):

  def __init__(
      self,
      wire,
      reference_wire,
      low_voltage=NumericalValue(0.0),
      high_voltage=NumericalValue(0.7),
      delay_s=NumericalValue(1.0),
      rise_time_s=NumericalValue(1.0, SIUnitPrefix.PICO),
      fall_time_s=NumericalValue(1.0, SIUnitPrefix.PICO),
      pulse_width_s=NumericalValue(2, SIUnitPrefix.NANO),
      period_s=NumericalValue(4, SIUnitPrefix.NANO)):
    super().__init__(wire, reference_wire)
    self.low_voltage = low_voltage
    self.high_voltage = high_voltage
    self.delay_s = delay_s
    self.rise_time_s = rise_time_s
    self.fall_time_s = fall_time_s
    self.pulse_width_s = pulse_width_s
    self.period_s = period_s

  def SpiceLine(self, device_name):
    # Xyce reference guide: PULSE(V1 V2 TD TR TF PW PER)
    return (
        f'{device_name} {self.wire.SpiceName()} {self.reference_wire.SpiceName()} '
        f'PULSE({self.low_voltage} {self.high_voltage} '
        f'{self.delay_s} {self.rise_time_s} '
        f'{self.fall_time_s} {self.pulse_width_s} '
        f'{self.period_s})')


class SinusoidalInput(InputWaveform):

  def __init__(
      self,
      wire,
      reference_wire,
      offset_v=NumericalValue(0.0, None),
      amplitude_v=NumericalValue(1.0, None),
      frequency_hz=NumericalValue(1.0, None),
      delay_s=NumericalValue(0.0),
      attentuation_factor=NumericalValue(0.0),
      phase=NumericalValue(0.0)):
    super().__init__(wire, reference_wire)
    self.offset_v = offset_v
    self.amplitude_v = amplitude_v
    self.frequency_hz = frequency_hz
    self.delay_s = delay_s
    self.attentuation_factor = attentuation_factor  
    self.phase = phase

  def SpiceLine(self, device_name):
    # Xyce reference guide: SIN(V0 VA FREQ TD THETA PHASE)
    return (
        f'{device_name} {self.wire.SpiceName()} '
        f'{self.reference_wire.SpiceName()} SIN({self.offset_v} '
        f'{self.amplitude_v} {self.frequency_hz} '
        f'{self.delay_s} {self.attentuation_factor} '
        f'{self.phase})')
