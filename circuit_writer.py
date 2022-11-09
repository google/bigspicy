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

from google.protobuf import text_format

import pdb
import circuit
import circuit_pb2 as circuit_pb
import utils_pb2 as utils_pb
from spice_util import SIUnitPrefix

class CircuitWriter():

  CIRCUIT_TO_PB_PORT_DIRECTION_MAP = {
      circuit.Port.Direction.INPUT: circuit_pb.Port.Direction.INPUT,
      circuit.Port.Direction.OUTPUT: circuit_pb.Port.Direction.OUTPUT,
      circuit.Port.Direction.INOUT: circuit_pb.Port.Direction.INOUT,
      circuit.Port.Direction.NONE: circuit_pb.Port.Direction.NONE,
  }

  PB_TO_CIRCUIT_PORT_DIRECTION_MAP = {
    v: k for k, v in CIRCUIT_TO_PB_PORT_DIRECTION_MAP.items()
  }

  CIRCUIT_TO_PB_SI_PREFIX_MAP = {
      None: None,
      SIUnitPrefix.YOCTO: utils_pb.SIPrefix.YOCTO,
      SIUnitPrefix.ZEPTO: utils_pb.SIPrefix.ZEPTO,
      SIUnitPrefix.ATTO: utils_pb.SIPrefix.ATTO,
      SIUnitPrefix.FEMTO: utils_pb.SIPrefix.FEMTO,
      SIUnitPrefix.PICO: utils_pb.SIPrefix.PICO,
      SIUnitPrefix.NANO: utils_pb.SIPrefix.NANO,
      SIUnitPrefix.MICRO: utils_pb.SIPrefix.MICRO,
      SIUnitPrefix.MILLI: utils_pb.SIPrefix.MILLI,
      SIUnitPrefix.CENTI: utils_pb.SIPrefix.CENTI,
      SIUnitPrefix.DECI: utils_pb.SIPrefix.DECI,
      SIUnitPrefix.DECA: utils_pb.SIPrefix.DECA,
      SIUnitPrefix.HECTO: utils_pb.SIPrefix.HECTO,
      SIUnitPrefix.KILO: utils_pb.SIPrefix.KILO,
      SIUnitPrefix.MEGA: utils_pb.SIPrefix.MEGA,
      SIUnitPrefix.GIGA: utils_pb.SIPrefix.GIGA,
      SIUnitPrefix.TERA: utils_pb.SIPrefix.TERA,
      SIUnitPrefix.PETA: utils_pb.SIPrefix.PETA,
      SIUnitPrefix.EXA: utils_pb.SIPrefix.EXA,
      SIUnitPrefix.ZETTA: utils_pb.SIPrefix.ZETTA,
      SIUnitPrefix.YOTTA: utils_pb.SIPrefix.YOTTA,
  }

  PB_TO_CIRCUIT_SI_PREFIX_MAP = {
    v: k for k, v in CIRCUIT_TO_PB_SI_PREFIX_MAP.items()
  }

  def __init__(self, design):
    self.design = design

  @staticmethod 
  def ToPortDirection(direction):
    try:
      return CircuitWriter.CIRCUIT_TO_PB_PORT_DIRECTION_MAP[direction]
    except KeyError:
      raise Exception(f'Unknown port direction: {direction}')

  @staticmethod
  def ToSIPrefix(prefix):
    try:
      return CircuitWriter.CIRCUIT_TO_PB_SI_PREFIX_MAP[prefix]
    except KeyError:
      raise Exception(f'Unknown SI prefix: {prefix}')

  @staticmethod
  def ToSignal(signal, signal_pb):
    signal_pb.name = signal.name
    signal_pb.width = signal.width

  @staticmethod
  def ToSlice(internal_slice, slice_pb):
    slice_pb.signal = internal_slice.signal.name
    slice_pb.top = internal_slice.top
    slice_pb.bot = internal_slice.bottom

  @staticmethod
  def ToPort(port, port_pb):
    port_pb.signal = port.signal.name
    port_pb.direction = CircuitWriter.ToPortDirection(port.direction)

  @staticmethod
  def ToExternalModule(module, module_pb):
    module_pb.name.name = module.name
    for port_name in module.port_order:
      if port_name not in module.ports:
        raise RuntimeError(
            f'port named in port order without associated Port object: {port_name}')
      port_pb = module_pb.ports.add()
      port = module.ports[port_name]
      CircuitWriter.ToPort(port, port_pb)
    for _, signal in module.signals.items():
      CircuitWriter.ToSignal(signal, module_pb.signals.add())

  @staticmethod
  def ToParameter(name, value, param_pb):
    param_pb.name = name
    if isinstance(value, circuit.NumericalValue):
      actual_value = value.value
      if value.unit is not None:
        param_pb.value.prefixed.prefix = CircuitWriter.ToSIPrefix(value.unit)
        store_pb = param_pb.value.prefixed
      else:
        store_pb = param_pb.value
      if isinstance(actual_value, float):
        store_pb.double = actual_value
      elif isinstance(actual_value, int) or isinstance(actual_value, long):
        store_pb.value.prefixed.integer = actual_value
      else:
        raise Exception(f'Unknown numerical type: {type(value)} for {value}')
    elif isinstance(value, str):
      param_pb.value.string = value
    else:
      raise Exception(f'Unknown value type: {type(value)} for {value}')
    return param_pb

  @staticmethod
  def ToConnection(port_name, connection, conn_pb):
    conn_pb.portname = port_name
    if connection.signal is not None:
      conn_pb.target.sig = connection.signal.name
    elif connection.slice is not None:
      CircuitWriter.ToSlice(connection.slice, conn_pb.target.slice)
    elif connection.concat is not None:
      raise Exception(f'Don\'t know how to map concats in conncections: {connection}')
    else:
      raise Exception(f'Cannot map disconnected Connection object: {connection}')
    return conn_pb

  @staticmethod
  def ToInstance(instance, instance_pb):
    instance_pb.name = instance.name
    instance_pb.module.local = instance.module_name
    for name, value in instance.parameters.items():
      CircuitWriter.ToParameter(name, value, instance_pb.parameters.add())
    for port_name, connection in instance.connections.items():
      if connection.IsDisconnected():
        continue
      CircuitWriter.ToConnection(
          port_name, connection, instance_pb.connections.add())

  def ToModule(module, module_pb):
    module_pb.name = module.name
    for name, value in module.default_parameters.items():
      CircuitWriter.ToParameter(name, value, module_pb.parameters.add())
    for port_name in module.port_order:
      port = module.ports[port_name]
      CircuitWriter.ToPort(port, module_pb.ports.add())
    for name, signal in module.signals.items():
      CircuitWriter.ToSignal(signal, module_pb.signals.add())
    for name, instance in module.instances.items():
      CircuitWriter.ToInstance(instance, module_pb.instances.add())

  def ToCircuitProto(self):
    design = self.design

    package_pb = circuit_pb.Package()
    #package_pb.name = design.top
    for name, module in design.external_modules.items():
      CircuitWriter.ToExternalModule(module, package_pb.ext_modules.add())
    for name, module in design.known_modules.items():
      CircuitWriter.ToModule(module, package_pb.modules.add())

    return package_pb

  def WriteDesignToTextProto(self, filename):
    package = self.ToCircuitProto()
    with open(filename, 'w') as f:
      f.write(text_format.MessageToString(package))

  def WriteDesignToProto(self, filename):
    package = self.ToCircuitProto()
    with open(filename, 'wb') as f:
      # TODO(growly): bytes-to-string conversion required encoding!
      f.write(package.SerializeToString())

  @staticmethod 
  def FromPortDirection(direction):
    try:
      return CircuitWriter.PB_TO_CIRCUIT_PORT_DIRECTION_MAP[direction]
    except KeyError:
      raise Exception(f'Unknown port direction: {direction}')

  @staticmethod
  def GetKnownSignal(signal_name, known_signals={}):
    if signal_name not in known_signals:
      raise Exception(f'Signal name is not known: {signal_name}')
    return known_signals[signal_name]

  @staticmethod
  def FromSignal(signal_pb):
    signal_name = signal_pb.name
    return circuit.Signal(signal_name, width=signal_pb.width)

  @staticmethod
  def FromSlice(slice_pb, known_signals={}):
    sliceyboi = circuit.Slice()
    signal_name = slice_pb.signal
    sliceyboi.signal = CircuitWriter.GetKnownSignal(signal_name, known_signals)
    sliceyboi.top = slice_pb.top
    sliceyboi.bottom = slice_pb.bot
    return sliceyboi

  @staticmethod
  def FromPort(port_pb, known_signals={}):
    # Ports represent signals implicitly
    port = circuit.Port()
    port.signal = CircuitWriter.GetKnownSignal(port_pb.signal, known_signals)
    port.direction = CircuitWriter.FromPortDirection(port_pb.direction)
    return port

  @staticmethod
  def FromConcat(concat_pb):
    raise NotImplementedError()

  @staticmethod
  def FromModule(module_pb):
    module = circuit.Module()
    module.name = module_pb.name
    for signal_pb in module_pb.signals:
      signal = CircuitWriter.FromSignal(signal_pb)
      if signal.name in module.signals:
        print('how did this happen')
        assert(signal.width == module.signals[signal.name].width)
      module.signals[signal.name] = signal
    for port_pb in module_pb.ports:
      port = CircuitWriter.FromPort(port_pb, module.signals)
      port.signal.Connect(port)
      port_name = port.signal.name
      module.ports[port_name] = port
      module.port_order.append(port_name)
      # TODO(growly): Add signals of port to signals? It should have been put there
      # by the serialiser?
    for instance_pb in module_pb.instances:
      instance = CircuitWriter.FromInstance(instance_pb, module.signals)
      module.instances[instance.name] = instance
    for param_pb in module_pb.parameters:
      name = param_pb.name
      instance.default_parameters[name] = CircuitWriter.FromParameter(param_pb)

    return module

  @staticmethod
  def FromSIPrefix(prefix_pb):
    try:
      return CircuitWriter.PB_TO_CIRCUIT_SI_PREFIX_MAP[prefix_pb]
    except KeyError:
      raise Exception('Unknown SI prefix: {prefix_pb}')

  @staticmethod
  def FromParameter(param_pb):
    set_value = param_pb.value.WhichOneof('value')
    if set_value is None:
      return
    if set_value in ('integer', 'double'):
      value = getattr(param_pb.value, set_value)
      return circuit.NumericalValue(value)
    if set_value == 'string':
      return param_pb.value.string
    if set_value == 'prefixed':
      prefixed_pb = param_pb.value.prefixed
      set_inner_value = prefixed_pb.WhichOneof('number')
      if set_inner_value in ('integer', 'double'):
        # This is a numerical value.
        value = getattr(param_pb.value.prefixed, set_inner_value)
        prefix = CircuitWriter.FromSIPrefix(prefixed_pb.prefix)
        return circuit.NumericalValue(value, prefix)
    raise Exception(f'Cannot interpret Parameter {param_pb}')

  @staticmethod
  def FromConnection(port_name, conn_pb, known_signals={}):
    connection = circuit.Connection(port_name)
    referenced_signals = []
    target = conn_pb.target
    set_field = target.WhichOneof('stype')
    if set_field is None:
      return None
    if set_field == 'sig':
      connection.signal = CircuitWriter.GetKnownSignal(conn_pb.target.sig, known_signals)
      referenced_signals.append(connection.signal)
    elif set_field == 'slice':
      connection.slice = CircuitWriter.FromSlice(conn_pb.target.slice, known_signals)
      connection.slice.Connect(connection)
      referenced_signals.append(connection.slice.signal)
    elif set_field == 'concat':
      raise Exception('Can\'t deal with concat types yet')
    else:
      raise Exception(f'Unknown field set in Connection proto: {set_field}')
    return connection, referenced_signals

  @staticmethod
  def FromInstance(instance_pb, known_signals={}):
    instance = circuit.Instance()
    instance.name = instance_pb.name
    set_field = instance_pb.module.WhichOneof('to')
    if set_field == 'local':
      instance.module_name = instance_pb.module.local
    elif set_field == 'external':
      instance.module_name = instance_pb.module.external.name
    else:
      raise Exception('Instance does not have module reference set')
    for param_pb in instance_pb.parameters:
      name = param_pb.name
      instance.parameters[name] = CircuitWriter.FromParameter(param_pb)
    for conn_pb in instance_pb.connections:
      port_name = conn_pb.portname
      connection, _ = CircuitWriter.FromConnection(port_name, conn_pb, known_signals)
      connection.instance = instance
      slice_or_signal = connection.signal or connection.slice
      slice_or_signal.Connect(connection)
      instance.connections[port_name] = connection
    return instance

  @staticmethod
  def FromExternalModule(module_pb):
    module = circuit.ExternalModule()
    if module_pb.name.domain:
      print('warning: external module has qualifying domain that we ignore: '
            f'{module.name.domain}')
    module.name = module_pb.name.name
    for signal_pb in module_pb.signals:
      signal = CircuitWriter.FromSignal(signal_pb)
      module.signals[signal.name] = signal
    for port_pb in module_pb.ports:
      port = CircuitWriter.FromPort(port_pb, module.signals)
      port.signal.Connects(port)
      port_name = port.signal.name
      module.ports[port_name] = port
      module.port_order.append(port_name)
    return module

  def FromCircuitProto(self, package_pb):
    design = self.design
    for module_pb in package_pb.modules:
      module = CircuitWriter.FromModule(module_pb)
      design.known_modules[module.name] = module
    for module_pb in package_pb.ext_modules:
      module = CircuitWriter.FromExternalModule(module_pb)
      if module.name in circuit.PRIMITIVE_MODULES:
        continue
      design.external_modules[module.name] = module

    for module_name, module in design.known_modules.items():
      for instance_name, instance in module.instances.items():
        instance_of = instance.module_name
        referenced = None
        if instance_of in circuit.PRIMITIVE_MODULES:
          referenced = circuit.PRIMITIVE_MODULES[instance_of]
          # TODO(growly): This might not be true for all primitive modules.
          referenced.is_passive = True
        elif instance_of in design.known_modules:
          referenced = design.known_modules[instance_of]
        elif instance_of in design.external_modules:
          referenced = design.external_modules[instance_of]
        else:
          raise Exception(
              f'Instance {instance_name} of module {module_name} refers '
              f'instantiates unknown module {instance_of}')
        instance.module = referenced


  def ReadProtoToDesign(self, filename):
    package_pb = circuit_pb.Package()

    with open(filename, 'rb') as f:
      package_pb.ParseFromString(f.read())

    self.FromCircuitProto(package_pb)


