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

import pdb
import math
from enum import Enum
import collections


import pdb

import spice
from spice_util import NumericalValue, SIUnitPrefix


# Modules describe a cell's structure. They are a template for instantiation of
# the module (cell) in other modules (cells). A design is at its root a module
# description.
#
# +-------------------------------------+
# |    Module        +--------------+   |
# |                  |     Ports    |   |
# |                  +--------------+   |
# |                  +--------------+   |
# |                  |   Instances  |   |
# |                  +--------------+   |
# |                  +--------------+   |
# |                  |    Signals   |   |
# |                  +--------------+   |
# +-------------------------------------+
#
# An instance describes connections to the static ports defined for a module,
# and provides a set of parameters that define particularities about that
# instance.
# +-------------------------------------+
# |    Instance      +--------------+   |
# |                  | Connections  |   |
# |                  +--------------+   |
# |                  +--------------+   |
# |                  |  Parameters  |   |
# |                  +--------------+   |
# +-------------------------------------+

CAPACITOR = None
RESISTOR = None
INDUCTOR = None
PRIMITIVE_MODULES = {}


# TODO(growly): Need a 'Parameter' class to wrap generic parameter values
# and enable appropriate actions for their type.


class Port:
  class Direction(Enum):
    INPUT = 1
    OUTPUT = 2
    INOUT = 3
    NONE = 4

  def __repr__(self):
    return '[port: {} {}]'.format(self.signal, self.direction)

  def __init__(self):
    # This is the internal signal which represents this port/pin. External
    # signals connected to this one use a Connection object.
    self.signal = None
    self.direction = Port.Direction.NONE
    # Capacitance to ground, if known. Whether this is input or output depends
    # on the port direction. TODO(growly): Maybe we'll need to support both,
    # like Liberate does. Actually I don't think this is used. Not sure how to model.
    self.capacitance = None

  def DisconnectFromSignal(self):
    self.signal = None

  def EnumerateWires(self, low=None, high=None):
    if self.signal is None:
      return None
    signal = self.signal
    low = max(0, low) if low is not None else 0
    high = min(signal.width, high) if high is not None else signal.Width
    return [Wire(signal, i) for i in range(low, high)]


class Signal:
  def __init__(self, name, width=1):
    self.name = name
    self.width = width
    # The ports which connect to this signal, if any.
    self.ports = set()

    # Connections to wires in the signal are maintained by the Signal itself;
    # any slice of the Signal implicitly connects each of those wires. Therefore
    # slices can remain lightweight and be duplicated as a bookkeeping measure
    # where needed.
    self.connects = collections.defaultdict(set)

    # If this signal is known to probably replace some signal in a previous
    # version of the circuit, include the name of that signal here:
    self.parent_name = None

  def __repr__(self):
    out = '[signal: {} w={}]'.format(self.name, self.width)
    return out

  def Connect(self, to, index=None):
    if index is None:
      # If no index is given, connect to all indices.
      for i in range(self.width):
        self.connects[i].add(to)
      return
    self.connects[index].add(to)

  def Connects(self, index=None):
    if index is not None:
      return self.connects[index]

    union = set()
    for k in range(self.width):
      union.update(self.connects[k])
    return union

  def ConnectsAnything(self):
    if not self.connects:
      return False
    for index, connects in self.connects.items():
      if connects:
        return True
    return False

  def FindLoadPorts(self, index=None):
    connects = self.Connects(index=index)
    load_ports = set()
    for connected in connects:
      if isinstance(connected, Port) and (
          connected.direction == Port.Direction.OUTPUT):
        # Even if we're at an output port of our greater circuit, we don't know
        # what might load it externally, so we can't use this.
        continue
      if isinstance(connected, Connection) and (
          connected.DirectionOfInstancePort() == Port.Direction.INPUT):
        module = connected.instance.module
        port = module.ports[connected.port_name]
        load_ports.add((connected.port_name, module, port))
    return load_ports

  def Disconnect(self, entity=None, include_ports=False):
    for i in range(self.width):
      self.DisconnectIndex(index=i, entity=entity, include_ports=include_ports)

  def DisconnectEntity(self, index, entity):
    connects = self.connects[index]
    connects.remove(entity)
    #print(f'removed {entity} from {index} {self}')
    if isinstance(entity, Connection) or isinstance(entity, Port):
      entity.DisconnectFromSignal()

  def DisconnectIndex(self, index, entity=None, include_ports=False):
    for connected in list(self.connects[index]):
      if not include_ports and isinstance(connected, Port):
        continue
      if entity is not None:
        if connected == entity:
          self.DisconnectEntity(index, connected)
        continue
      # By default, remove everything else:
      #print(f'disconnecting {connected} from {index} on {self}')
      self.DisconnectEntity(index, connected)

  def Width(self):
    return self.width


class Wire:
  """A Signal reference with a single index, always width-1.

  Use as a (signal, index) pair for keys, too."""

  def __init__(self, signal, index):
    self.signal = signal
    self.index = index

  def __hash__(self):
    return hash((self.signal, self.index))

  def __eq__(self, other):
    return self.signal == other.signal and self.index == other.index

  def __repr__(self):
    return f'[wire {self.signal.name}[{self.index}]]'

  def __lt__(self, other):
    if self.signal.name < other.signal.name:
      return True
    return self.index < other.index

  def Connects(self):
    if not self.signal or self.index is None:
      raise Exception('Wire should have a signal and an index')
    return self.signal.Connects(self.index)

  def SpiceName(self):
    if self.signal.width == 1:
      return self.signal.name
    else:
      return f'{self.signal.name}.{self.index}'


class Connection:
  """A connection describes all of the signals to which a port is connected.

  The full port bus is described. If only a Signal is connected, the widths
  must match. If a Slice is connected, the Slice width must match the Port
  width. If a Concatenation is connected, the total width of that
  Concatenation must match.
  """
  def __init__(self, port_name):
    self.port_name = port_name
    self.instance = None
    self.signal = None
    self.slice = None
    self.concat = None

  def __repr__(self):
    #desc = 'connection {} <-> '.format(self.port_name)
    instance_name = self.instance.name if self.instance else 'None'
    desc = f'[connection {instance_name}/{self.port_name} =>'
    if self.signal is not None:
      desc += '{}'.format(self.signal)
    elif self.slice is not None:
      desc += '{}'.format(self.slice)
    elif self.concat is not None:
      desc += '{}'.format(self.concat)
    else:
      desc += 'disconnected'
    desc += ']'
    return desc

  def IsDisconnected(self):
    return self.signal is None and self.slice is None and self.concat is None

  def EnumerateWires(self):
    signal = self.GetConnectedSignal()
    indices = self.IndexOnSignal()
    return [Wire(signal, k + indices[0])
            for k in range(indices[1] - indices[0] + 1)]

  def IndexOnSignal(self):
    # Returns a pair of [hi, low] indices to which this Connection
    # connects. Like in Verilog.
    if self.signal is not None:
      return (self.signal.width - 1, 0)
    if self.slice is not None:
      return (self.slice.top, self.slice.bottom)
    raise NotImplementedError()

  def DirectionOfInstancePort(self):
    if (type(self.instance.module) is ExternalModule and
        self.port_name not in self.instance.module.ports):
      return ExternalModule.GuessDirectionOfExternalModulePort(self.port_name)

    return self.instance.module.ports[self.port_name].direction

  def GetConnected(self):
    if self.signal is not None:
      return self.signal
    if self.slice is not None:
      return self.slice
    if self.concat is not None:
      return self.concat
    return None

  def GetConnectedSignal(self):
    if self.signal is not None:
      return self.signal
    if self.slice is not None:
      return self.slice.signal
    if self.concat is not None:
      raise NotImplementedError()

  def Disconnect(self):
    assert self.port_name in self.instance.connections, f'{self.port_name} not in {self.instance.connections}'
    self.DisconnectFromSignal()
    del self.instance.connections[self.port_name]

  def DisconnectFromSignal(self):
    self.signal = None
    self.slice = None
    self.concat = None

  def DisconnectFromParent(self, include_ports=False):
    if self.signal is not None:
      self.signal.Disconnect(self, include_ports=include_ports)
    elif self.slice is not None:
      self.slice.Disconnect(self, include_ports=include_ports)


class Slice: 

  def __init__(self):
    self.signal = None
    self.top = None
    self.bottom = None

  def __repr__(self):
    return '[slice: {}[{}:{}]]'.format(self.signal.name, self.top, self.bottom)

  def Connect(self, to, index=None):
    if index is None:
      # If no index is given, connect to all indices.
      for i in range(self.top - self.bottom + 1):
        index = i + self.bottom
        self.signal.Connect(to, index=index)
      return
    elif index < self.bottom or index > self.top:
      raise IndexError(f'slice does not include index {index}')
    self.signal.Connect(to, index=index)

  def Disconnect(self, entity, include_ports=False):
    for i in range(self.top - self.bottom + 1):
      index = i + self.bottom
      self.signal.DisconnectIndex(index, entity=entity, include_ports=include_ports)

  def Connects(self):
    connects = set()
    for i in range(self.top - self.bottom + 1):
      k = i + self.bottom
      connects.update(self.signal.connects[k])
    return connects

  def Width(self):
    return self.top - self.bottom + 1

#  # NOTE(growly): Not sure if this is working:
#  def __eq__(self, other):
#    if (self.signal is None and other.signal is not None) or (
#        self.signal is not None and other.signal is None):
#      return False
#    elif (self.signal is not None and other.signal is not None and
#        self.signal != other.signal):
#        return False
#    # Both self.signal and other.signal are None, so try:
#    if self.top != other.top:
#      return False
#    if self.bottom != other.bottom:
#      return False
#    return True
#
#  # Implemented so that equal slices have equal hashes:
#  def __hash__(self, other):
#    return hash((self.signal.name if self.signal else None, self.top, self.bottom))


class Instance:

  def __init__(self):
    self.name = None
    self.module_name = None
    self.module = None
    self.parameters = {}
    self.connections = {}

    # If Connection objects are not available but we know the order in which signals
    # should be connected to ports, keep them here. This happens when we interpret
    # a spice deck not having loaded the master modules.
    self.connections_by_order = []

  def __repr__(self):
    conn_list = []
    port_order = (self.module.port_order
        if self.module is not None else sorted(self.connections.keys()))
    for port_name in port_order:
      if port_name in self.connections:
        connection = self.connections[port_name]
        conn_list.append(f'{port_name}: {connection}')
    return '[instance {} of {}, params={} connections={}]'.format(
        self.name,
        self.module_name,
        self.parameters,
        conn_list)


class TwoEndedElement(Instance):

  def __init__(self, left, right):
    super().__init__()
    for port_name, to_connect in zip(('A', 'B'), (left, right)):
      connection = Connection(port_name)
      connection.instance = self
      self.connections[port_name] = connection
      if isinstance(to_connect, Signal):
        connection.signal = to_connect
      elif isinstance(to_connect, Slice):
        connection.slice = to_connect
      to_connect.Connect(connection)


class Capacitor(TwoEndedElement):

  def __init__(self, left_signal, right_signal, value):
    super().__init__(left_signal, right_signal)
    self.module = CAPACITOR
    self.module_name = CAPACITOR.name
    self.parameters['capacitance'] = value


class Resistor(TwoEndedElement):

  def __init__(self, left_signal, right_signal, value):
    super().__init__(left_signal, right_signal)
    self.module = RESISTOR
    self.module_name = RESISTOR.name
    self.parameters['resistance'] = value


class Inductor(TwoEndedElement):

  def __init__(self, left_signal, right_signal, value):
    super().__init__(left_signal, right_signal)
    self.module = INDUCTOR
    self.module_name = INDUCTOR.name
    self.parameters['inductance'] = value


class ExternalModule:
  
  def __init__(self):
    self.name = None
    self.ports = {}
    self.port_order = []
    self.signals = {}
    self.is_sequential = False
    self.is_passive = False
    self.default_parameters = {}

    # Per port, per index, /*per step [indicating the analysis params],*/
    # store the measured small signal input capacitance.
    self.input_capacitances = collections.defaultdict(dict)

    # Per port (by name).
    self.large_signal_step_capacitances = {}
    self.large_signal_sinusoidal_capacitances = {}

  def __repr__(self):
    ports = ', '.join(self.port_order)
    return f'[module {self.name} (external) ports: {ports}]'

  def GuessPorts(self, instances):
    """ Guess the ports from all the instances. """
    pass

  def GetOrCreateSignal(self, name, width=1):
    if name in self.signals:
      return self.signals[name]
    # print(f'module {self.name} creating signal named "{name}"') ## Shut up already WE KNOW!
    signal = Signal(name, width=width)
    self.signals[name] = signal
    return signal

  def GetOrCreatePort(self, name, width=1, direction=Port.Direction.NONE):
    if name in self.ports:
      return self.ports[name]
    print(f'module {self.name} creating port named "{name}" width={width} direction={direction}')
    port = Port()
    port.name = name
    port.direction = direction

    signal = self.GetOrCreateSignal(name, width=width)
    signal.Connect(port)

    # NOTE(growly): This is here because putting it in Signal is slightly more
    # annoying (have to check if any index connects to the port before removing
    # it in Disconnect).
    signal.ports.add(port)

    port.signal = signal
    self.ports[name] = port
    self.port_order.append(name)
    return port

  def MakeReasonableGuessAtInputCapacitanceForPort(self, port_name, index=0):
    step = None
    sin = None
    small = None
    if port_name in self.large_signal_sinusoidal_capacitances:
      sin = self.large_signal_sinusoidal_capacitances[port_name]
    if port_name in self.large_signal_step_capacitances:
      step = self.large_signal_step_capacitances[port_name]
    try:
      small = self.input_capacitances[port_name][index]
    except KeyError:
      pass
    guesses = list(filter(lambda x: x is not None and x > 0.0, [small, step, sin]))
    if not guesses:
      return None
    mean = sum(guesses)/len(guesses)
    return mean

  @staticmethod
  def GuessDirectionOfExternalModulePort(port_name):
    # !!! HACK HACK HACK HACK !!!
    # FIXME(growly): UGH this flippin' SUCKS.
    # Our verilog parser breaks when reading these statements:
    #
    #  specify
    #          (A => Y) = 0;
    #  endspecify
    #
    # So we can't read the standard cell models that tell us what directions
    # the ports have. So we have to make it up.
    #
    # $ grep output asap7sc7p5t_27/Verilog/*.v | cut -f2 | sort | uniq
    # output CON, SN;
    # output GCLK;
    # output H;
    # output L;
    # output q;
    # output Q;
    # output QN;
    # output Y;
    #
    # (likewise for 'input')
    #
    # We have the same problem for every PDK smh. For sky130, the verilog fails
    # to parse because alot of cells are defined conditionally with
    # preprocessor macros, distinguishing for example versions with and without
    # power pins. The same trick applies:
    # grep output sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v | sort | uniq
    #
    # output COUT;
    # output COUT_N;
    # output GCLK;
    # output HI;
    # output LO;
    # output Q  ;
    # output Q_N;
    # output SUM ;
    # output X;
    # output Y;
    # output Z ;

    # raise RuntimeError('Check this function and make sure it correctly guesses '
    #                    'port directions for your PDK.')

    if port_name in ('d', 'g', 's', 'b'):
      return Port.Direction.NONE
      
    if port_name in ('VDD', 'VSS', 'VPWR', 'VGND'):
      return Port.Direction.INOUT
    #elif port_name in ('Y', 'q', 'H', 'L', 'Q', 'QN', 'GCLK', 'CON', 'SN'):
    #  # ASAP7
    #  return Port.Direction.OUTPUT
    elif port_name in ('COUT', 'COUT_N', 'GCLK', 'HI', 'LO', 'Q', 'Q_N', 'SUM',
                       'X', 'Y', 'Z'):
      # Sky130
      return Port.Direction.OUTPUT
    else:
      return Port.Direction.INPUT


class Module(ExternalModule):

  def __init__(self):
    ExternalModule.__init__(self)

    self.instances = {}

    # TODO(aryap): Need to know what ground and power nets are.

    # How many 10^x of an Ohm. (None => x = 0)
    self.resistance_unit_prefix = None
    # How many 10^x of a Farad. (None => x = 0)
    self.capacitance_unit_prefix = None
    # How many 10^x of a second. (None => x = 0)
    self.time_unit_prefix = None
    # How many 10^x of a Henry. (None => x = 0)
    self.inductance_unit_prefix = None
    
  @classmethod
  def FromVerilog(cls, ast_node: "verilog.ast.Node") -> "Module":
    """ Create a `Module` from a `verilog.ast.Node`. """
    from verilog import ModuleReader 
    
    this = cls()
    ModuleReader.LoadAST(this, ast_node)
    return this 

  def __repr__(self):
    desc = f'[module {self.name}]'
    return desc

  def Show(self):
    print(f'module: {self.name}')
    print(f'\t{len(self.ports)} ports:')
    for port_name, port in self.ports.items():
      print(f'\t\t{port_name}: {port}')
    print(f'\t{len(self.signals)} signals:')
    print(f'\t{len(self.instances)} instacnes:')
    for name, instance in self.instances.items():
      print(f'\t\t{name}: {instance.module_name}')
      for port_name, connection in instance.connections.items():
        print(f'\t\t\t{port_name}: {connection}')

  # Critical paths are those which constrain the overall clock speed of the circuit.
  # That means they are the slowest path(s) between any two sequential elements
  # (latches, flops). Ports are not sequential per se, but since we don't know
  # what they connect to we have to consider them our boundary.
  def FindCriticalPaths(self):
    pass

  def FindPaths(self):

    def IsTerminalNode(node):
      if isinstance(node, Port):
        return True
      if isinstance(node, Instance) and node.module.is_sequential:
        return True
      return False

    def GetSliceOrSignal(sink):
      if isinstance(sink, Connection):
        return sink.GetConnected()
      raise ValueError(f'not sure what to do about a {sink}')

    starting_paths = collections.deque()

    # In this imagining, Signals are zero-cost virtual connections since we
    # assume that all circuit-level timing cost is attribute to the resistor
    # and capacitor instances generated by extraction (that is, we cannot use
    # this search for hypothetical wire models).
    for port in self.ports.values():
      if port.direction in (Port.Direction.INPUT, Port.Direction.INOUT):
        signal = port.signal

        # A width-1 slice should be unique since it defines the wire.
        # We should find these in the 'connects' set of the signal.
        for index, connects in sorted(signal.connects.items(), key=lambda x: x[0]):
          sinks = set(connects)
          sinks.remove(port)
          for sink in sinks:
            path = TimingPath(port)
            path.Add(sink)
            starting_paths.append(path)

    while starting_paths:
      starting_path = starting_paths.popleft()

      to_visit = collections.deque()
      to_visit.append(starting_path.steps[-1])

      # Seen should contain... ports and connections.
      # If it contained instances you wouldn't be able to weave in and out of
      # the same instance.
      seen = set([starting_path.start, starting_path.steps[-1]])

      print('new path')
      while to_visit:
        current = to_visit.popleft()
        if not isinstance(current, Connection):
          raise ValueError(f'not sure what to do about a {current}')
        print(f'current: {current}')
        if current in seen:
          print(f'seen: {current}')
          continue

        # We have arrived at the instance of some module on one of its ports.
        # We follow all INOUT and OUTPUT ports from this module. The instance
        # itself is considered a blackbox.
        inbound_port_name = current.port_name
        instance = current.instance

        if instance.module.is_sequential:
          print('TODO(growly): Stop here')

        module = instance.module
        for port_name, connection in instance.connections.items():
          if port_name == inbound_port_name:
            continue
          if connection.DirectionOfInstancePort() not in (
              Port.Direction.OUTPUT, Port.Direction.INOUT):
            continue
          # At this point we know the exit port from the instance (it's given
          # in 'connection').
          slice_or_signal = connection.GetConnected()
          if isinstance(slice_or_signal, Slice):
            index = slice_or_signal.bottom
            sinks = set(slice_or_signal.signal.connects[index])
            assert connection in sinks, (
                'connection should be in the list of connected objects which it '
                'purportedly connects')
            sinks.remove(connection)
            for sink in sinks:
              to_visit.append(sink)

          # 'connection' is the outgoing port/signal pair.
          #to_visit.append(connection)
      print('done')

  # TODO(growly): Stop search at GND and VSS!

  @staticmethod
  def FindConnectedRegionBetweenPorts(
      source_port, sink_port, source_range=None, sink_range=None,
      ignore_signals=set()):
    # We traverse a graph of:
    #             +--------+                +----------+                +--------+
    #             | Signal |                | Instance |                | Signal |
    #             +--------+                +----------+                +--------+
    #            /          \              /            \              /
    # +---------+            +------------+              +------------+ 
    # |  Port   |            | Connection |              | Connection |
    # +---------+            +------------+              +------------+
    #
    # and return the collection of these items that form a combinational path
    # between
    if not isinstance(source_port, Port):
      # This doesn't have to be limited to a Port, but for now that's all we need.
      raise NotImplementedError()

    source_low = source_range[0] if source_range is not None else 0
    source_high = source_range[1] if source_range is not None else source.signal.width - 1
    sink_low = sink_range[0] if sink_range is not None else 0
    sink_high = sink_range[1] if sink_range is not None else sink.signal.width - 1

    seen = set([source_port])
    to_visit = collections.deque()

    for i in range(source_high - source_low + 1):
      k = i + source_low
      to_visit.extend([x for x in source_port.signal.connects[k] if x != source_port])

    some_sink_found = False

    region = DesignRegion()
    source_wires = source_port.EnumerateWires(low=source_low, high=source_high+1)
    region.AddWiresForDirection(source_wires, source_port.direction)
    sink_wires = sink_port.EnumerateWires(low=sink_low, high=sink_high+1)
    region.AddWiresForDirection(sink_wires, sink_port.direction)

    while to_visit:
      current = to_visit.popleft()
      # print(current)
      if isinstance(current, Port):
        if current is sink_port:
          # We're done.
          seen.add(current)
          some_sink_found = True
      elif isinstance(current, Connection):
        # 'current' is an incoming connection to an instance, since we
        # process outgoing connections below.
        instance = current.instance
        if instance.module.is_sequential:
          # This is a timing boundary; do not consider outputs connected.
          continue
        region.instances.add(instance)
        for port_name, outgoing in current.instance.connections.items():
          #pdb.set_trace()
          if outgoing is current:
            # Skip the incoming port.
            continue
          if outgoing in seen:
            continue
          # Only follow outputs.
          if outgoing.DirectionOfInstancePort() not in (
              Port.Direction.OUTPUT, Port.Direction.INOUT):
            continue
          if outgoing.GetConnectedSignal().name in ignore_signals:
            continue
          #print(f'finding signals connected to {outgoing.GetConnectedSignal().name}')
          seen.add(outgoing)
          slice_or_signal = outgoing.GetConnected()
          for next_port_or_connection in slice_or_signal.Connects():
            if next_port_or_connection in seen:
              continue
            seen.add(next_port_or_connection)
            to_visit.append(next_port_or_connection)
      else:
        raise NotImplementedError()

    inout_wires = set()
    for instance in region.instances:
      for connection in instance.connections.values():
        inout_wires.update(connection.EnumerateWires())
    region.AddWiresForDirection(sorted(inout_wires), Port.Direction.INOUT)


    if some_sink_found:
      more_inout_wires = set()
      #for instance in region.instances:
      #  for connection in instance.connections.values():
      #    signal = connection.GetConnectedSignal()
      #    if signal.name in probe_signal_names:
      #      wires = connection.EnumerateWires()
      #      region.AddWiresForDirection(wires, Port.Direction.INOUT)

      return region
    return None

  # TODO(growly): Ok big problem is that we're assuming that the netlist is
  # flattened into single-width wires everywhere, but this is only because the
  # SPEF extraction gives us this view. The Wire class helps with this but it
  # was added late and isn't used everywhere it could be.

  @staticmethod
  def FindConnectedSubgraphFrom(start, ignore_signals):
    next_starting_points = collections.deque()
    to_visit = collections.deque([start])
    seen = set()

    # A region is made up of Instances in the interior and Wires at the edges.
    # The Wires refer to existing signals.
    region = DesignRegion()

    # Coupling capacitances below this value are considered boundaries for the
    # subgraph.
    COUPLING_CAP_LIMIT = NumericalValue(100, SIUnitPrefix.ATTO)

    def FindConnectionsTo(current):
      connections = None
      signal = None
      indices = None
      if isinstance(current, Wire):
        signal = current.signal
        connections = current.Connects()
        indices = (current.index, current.index)
      elif isinstance(current, Connection):
        signal = current.GetConnectedSignal()
        indices = current.IndexOnSignal()
        slice_or_signal = current.GetConnected()
        if isinstance(slice_or_signal, Slice):
          assert slice_or_signal.top == slice_or_signal.bottom
          connections = slice_or_signal.signal.Connects(slice_or_signal.bottom)
        if isinstance(slice_or_signal, Signal):
          assert slice_or_signal.width == 1
          connections = slice_or_signal.Connects()
      else:
        raise NotImplementedError()
      return connections, signal, indices

    # This says nothing of the direction of the connection, only that it is an edge
    # connected to the node (instance) and it is not the one we came in on
    # (incoming connection).
    def FindOutgoingConnectionsFrom(instance, incoming_connection):
      viable = []
      for _, outgoing in instance.connections.items():
        if outgoing is incoming_connection:
          continue
        if outgoing.GetConnectedSignal().name in ignore_signals:
          continue
        # Do not continue through this instance through ports which are
        # strictly INPUTs.
        #if outgoing.DirectionOfInstancePort() not in (
        #    Port.Direction.OUTPUT, Port.Direction.INOUT):
        #  continue
        viable.append(outgoing)
      return viable

    # This search works by hopping from net to net; at each net, we find all
    # the connected instances (cells) and inspect their type. Depending on the
    # type, we continue the search through them, or we do not.
    while to_visit:
      current = to_visit.popleft()
      if current in seen:
        continue

      # Find candidate connections to this wire/signal.
      connections, signal, indices = FindConnectionsTo(current)
      if signal.name in ignore_signals:
        continue

      # to_visit contains egress connections attached to some instance.
      # We have to search for the ingress connections connected to the
      # egress signal, then find the egress connections from those instances
      # to add back to the to_visit queue.
      for connection in connections:
        if connection in seen:
          continue
        seen.add(connection)

        # From our seed connection ('current'), we are connected through a
        # Signal to either Ports or Connections. Ports are boundaries.
        # Connections represent instances, which are either interior to the
        # subgraph of interest or boundaries. Ports do not present additional
        # avenues to continue the search. Interior instances do. Boundary
        # instances otherwise provide new starting points for the search.

        if isinstance(connection, Port):
          # Ports are boundaries, so we need to add this to the covered
          # subgraph but not pursue it.
          port = connection
          wires = [Wire(port.signal, k + indices[0]) for k in range(indices[1] - indices[0] + 1)]
          region.AddWiresForDirection(wires, port.direction)
          region.AttachPorts(wires)
          if port.direction in (Port.Direction.INPUT,):
            region.AttachSimulatedDrivers(wires)
          elif port.direction in (Port.Direction.OUTPUT,):
            region.AttachVoltageProbes(wires)
          continue

        assert(isinstance(connection, Connection))

        instance = connection.instance
        #if instance in seen:
        #  continue
        outgoing = FindOutgoingConnectionsFrom(instance, connection)
        if instance.module == RESISTOR:
          region.instances.add(instance)
          to_visit.extend(outgoing)
        elif instance.module == CAPACITOR:
          region.instances.add(instance)
          capacitance = instance.parameters['capacitance']
          if capacitance >= COUPLING_CAP_LIMIT:
            to_visit.extend(outgoing)
          else:
            # We include the capacitor as a boundary element but do not follow
            # its connections. The external pin(s) is now a probe point, or
            # possibly a bias point.
            for external in outgoing:
              wires = external.EnumerateWires()
              region.AddWiresForOppositeDirection(wires, external.DirectionOfInstancePort())
              region.AttachBias(wires)
        else:
          assert(not instance.module.is_passive)

          # In this case, the boundary instance is excluded from the interior
          # outright. The outgoing connections on the other side of the
          # instance are used as seeds to search for the next connected
          # subgraph. The incoming connection is used for probes, and to define
          # boundary pins.
          wires = connection.EnumerateWires()
          region.AddWiresForOppositeDirection(wires, connection.DirectionOfInstancePort())
          region.AttachPorts(wires)

          if connection.DirectionOfInstancePort() in (
              Port.Direction.INPUT, Port.Direction.INOUT):
            region.AttachVoltageProbes(wires)
          elif connection.DirectionOfInstancePort() == Port.Direction.OUTPUT:
            region.AttachSimulatedDrivers(wires)

          # If we have data on the load capacitance at this boundary (i.e. the
          # input capacitance to a module), we include it as a simulated load.
          if type(instance.module) is ExternalModule and (
              connection.DirectionOfInstancePort() == Port.Direction.INPUT):
            region.AttachCapacitiveLoads(instance, connection, update_ports=True)

          next_starting_points.extend(outgoing)

        seen.add(instance)

    return region, seen, next_starting_points


  @staticmethod
  def ExtractPassiveRegions(seed, ignore_signals=None):
    # TODO(growly): These are a property of the module or design!
    # FIXME(growly): Our primitives reference the module/design/hardcoded
    # ground nets. We should automatically add these to the port list for the
    # region. We should also check that all of the referenced nets for a region
    # are in some port list. The hack is to simply make them global.
    # FIXME(growly): '.NODESET' seems to do what we use 'DC source' for;
    # meaning it sets the initial conditions of a net where we introduce a DC
    # bias.
    ignore_signals = ignore_signals or set(['GND', 'VSS', 'VDD'])

    print(f'seed: {seed}')

    # These are Ports or Connections, which refer to Ports of Instances.
    starting_points = collections.deque([seed])

    # This is going to get huge.
    globally_seen = set()

    num_subgraphs = 0
    while starting_points:
      start = starting_points.popleft()
      if start in globally_seen:
        #print(f'start {start} in globally seen; skipping')
        continue
      else:
        #print(f'start is: {start}')
        pass

      subgraph, seen, next_starting_points = Module.FindConnectedSubgraphFrom(start, ignore_signals)
      num_subgraphs += 1
      subgraph.name = f'region.{num_subgraphs}'

      globally_seen.update(seen)
      starting_points.extend(next_starting_points)

      yield subgraph

      #if num_subgraphs == 1:
      #  break


class VerilogIdentifier:

  def __init__(self, text):
    self.source_text = text
    self.raw = None

    self._Parse()

  def _Parse(self):
    # Try to reduce the identifier to the sequence of ASCII characters
    # it represents, after digesting the escaping permitted in the Verilog
    # file.
    #
    # See section 5.6 in the IEEE Verilog spec.
    if self.source_text.startswith('\\'):
      # The identifier should end with a space, per section 5.6.1.
      if self.source_text.endswith(' '):
        self.raw = self.source_text[1:-1]
      else:
        # This isn't technically legal but it looks like pyverilog drops the
        # trailing space.
        self.raw = self.source_text[1:]

    else:
      # It's not clear to me if by this point the identifier is just a string
      # with pesky escape characters (backslashes), or if we have to understand
      # hierarchical naming (dot-delimited), or if we have to understand and
      # extract bus indices, etc. I'll assume the former.
      self.raw = self.source_text.replace('\\', '')


class DesignRegion:
  """A subset of elements from some design for testing.

  This is a description of what elements to test and how; it can also
  be used to test whole-modules as black boxes."""

  class DUTType(Enum):
    SUB_REGION = 1
    MODULE = 2
    EXTERNAL_MODULE = 3

  def __init__(self, instances=set()):
    #self.design = design
    self.name = 'unnamed'
    self.dut_type = DesignRegion.DUTType.SUB_REGION

    self.instances = instances
    self.module = None

    # Simulation set up and probes.
    self.dc_biases = {}
    self.dc_sources = {}
    self.loads = {}
    self.simulated_drivers = {}
    self.voltage_probes = {}

    self.subcircuit_delay_measurements = []
    self.subcircuit_voltage_probes = []

    # These are Spice Ports, i.e. for an N-Port network.
    self.port_network_ports = {}
    self.input_wires = set()
    self.inout_wires = set()
    self.output_wires = set()

    # Results.
    # These are the TestManifest messages that describe where the results come
    # from.
    self.transient_pbs = []
    self.linear_pbs = []
    # Unknown delay measurements (with unresolveable net names).
    self.other_delays = []
    # LinearAnalysisResults object.
    self.linear_analyses = None
    # Map of file name to FFT results in that file.
    self.fft_results = {}
    # Other measurements from the .mt* files, with again the filename as the
    # key.
    self.other_measurements = {}
    # Time series data from voltage probes and such, keyed by UPPERCASE Spice
    # names for signals. Leaf elements are an Nx2 np.array.
    self.probe_results = {}

  def AddWiresForDirection(self, wires, direction):
    if direction == Port.Direction.INPUT:
      self.input_wires.update(wires)
    elif direction == Port.Direction.OUTPUT:
      self.output_wires.update(wires)
    elif direction == Port.Direction.INOUT:
      self.inout_wires.update(wires)
    else:
      raise NotImplementedError(f'cannot add wires; unknown direction: {direction}')

  def AddWiresForOppositeDirection(self, wires, direction):
    if direction == Port.Direction.INPUT:
      direction = Port.Direction.OUTPUT
    elif direction == Port.Direction.OUTPUT:
      direction = Port.Direction.INPUT
    self.AddWiresForDirection(wires, direction)

  def AttachPorts(self, wires, load_connection=None):
    new_ports = {wire.SpiceName(): spice.Port(wire) for wire in wires}
    for key, port in new_ports.items():
      if key not in self.port_network_ports:
        self.port_network_ports[key] = port

  def AttachBias(self, wires):
    self.dc_biases.update(
        {wire.SpiceName(): spice.DCVoltageSource(wire) for wire in wires})

  def AttachSimulatedDrivers(self, wires):
    self.simulated_drivers.update(
        {wire.SpiceName(): spice.SimulatedDriver(wire) for wire in wires})

  def AttachVoltageProbes(self, wires):
    self.voltage_probes.update(
        {wire.SpiceName(): spice.VoltageProbe(wire) for wire in wires})

  def AttachCapacitiveLoads(self, instance, connection, update_ports=True):
    port_name = connection.port_name
    wires = EnumerateWiresInConnection(connection)
    module = instance.module
    assert(type(module) is ExternalModule)
    for i, wire in enumerate(wires):
      input_capacitance = module.MakeReasonableGuessAtInputCapacitanceForPort(
          port_name, i)
      if not input_capacitance:
        continue
      if update_ports:
        try:
          port = port_network_ports[wire.SpiceName()]
          port.load_capacitance = NumericalValue(input_capacitance, None)
        except KeyError:
          pass
      loads[wire.SpiceName()] = spice.CapacitiveLoad(
          wire, NumericalValue(input_capacitance, None))

  def HasResultsForTag(self, tag):
    for transient_pb in self.transient_pbs:
      if tag in transient_pb.tags:
        return True
    for linear_pb in self.linear_pbs:
      if tag in linear_pb.tags:
        return True
    return False

  def OrderedWires(self):
    all_wires = []
    if self.dut_type in (
        DesignRegion.DUTType.MODULE, DesignRegion.DUTType.EXTERNAL_MODULE) and (
            self.module is not None):
      for port_name in self.module.port_order:
        port = self.module.ports[port_name]
        all_wires.extend(Wire(port.signal, i) for i in range(port.signal.width))
    else:
      all_wires = list(self.input_wires | self.inout_wires | self.output_wires)
      all_wires.sort(key=lambda x: (x.signal.name, x.index))
    return all_wires


class TimingPath:
  def __init__(self, start):
    self.start = start
    self.steps = []

  def Add(self, step):
    self.steps.append(step)

#  def __repr__(self):
#    return ', '.join([repr(self.start)] + [repr(x) for x in self.steps])


def DefinePrimitives():
  global CAPACITOR
  CAPACITOR = ExternalModule()
  CAPACITOR.name = 'CAPACITOR'
  CAPACITOR.is_passive = True
  _ = CAPACITOR.GetOrCreatePort('A', width=1, direction=Port.Direction.INOUT)
  _ = CAPACITOR.GetOrCreatePort('B', width=1, direction=Port.Direction.INOUT)
  CAPACITOR.default_parameters['capacitance'] = NumericalValue(0.0, None)

  global RESISTOR
  RESISTOR = ExternalModule()
  RESISTOR.name = 'RESISTOR'
  RESISTOR.is_passive = True
  _ = RESISTOR.GetOrCreatePort('A', width=1, direction=Port.Direction.INOUT)
  _ = RESISTOR.GetOrCreatePort('B', width=1, direction=Port.Direction.INOUT)
  RESISTOR.default_parameters['resistance'] = NumericalValue(0.0, None)

  global INDUCTOR
  INDUCTOR = ExternalModule()
  INDUCTOR.name = 'INDUCTOR'
  INDUCTOR.is_passive = True
  _ = INDUCTOR.GetOrCreatePort('A', width=1, direction=Port.Direction.INOUT)
  _ = INDUCTOR.GetOrCreatePort('B', width=1, direction=Port.Direction.INOUT)
  INDUCTOR.default_parameters['inductance'] = NumericalValue(0.0, None)

  global PRIMITIVE_MODULES
  PRIMITIVE_MODULES[CAPACITOR.name] = CAPACITOR
  PRIMITIVE_MODULES[RESISTOR.name] = RESISTOR
  PRIMITIVE_MODULES[INDUCTOR.name] = INDUCTOR


# This sets up the global CAPACITOR, RESISTOR and INDUCTOR instances.
DefinePrimitives()
