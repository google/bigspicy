#!/usr/bin/env python3
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

import os
import re
import optparse
from optparse import OptionParser
import glob

import circuit
import circuit_writer
import spice
import spice_analyser
from design import Design


def PrefixRelativeName(prefix, name):
  if name.startswith('/'):
    return name
  return os.path.join(prefix, name)


def FilesExistOrError(file_names):
  for file_name in file_names:
    if not os.path.exists(file_name):
      raise IOError(f'File not found: {file_name}')


def RequireOptions(options, *argv):
  for arg in argv:
    if not getattr(options, arg):
      raise Exception(
          f'option missing: {arg}; the following options are required: ' +
          ', '.join(argv))


def DefineOptions(optparser):
  optparser.add_option('-t', '--top', dest='top_name', default=None, help='top module')
  optparser.add_option('--verilog', dest='verilog_files', default=[], action='append', help='verilog files')
  optparser.add_option('--verilog_include', dest='verilog_includes', default=[], action='append', help='verilog include paths')
  optparser.add_option('--verilog_defines', dest='verilog_defines', default=[], action='append', help='verilog macro definitions')
  optparser.add_option('--spef', dest='spef_files', default=[], action='append', help='spef files')
  
  # FIXME: what is the difference between these two "spice" options? 
  optparser.add_option('--spice', dest='spice_files', default=[], action='append', help='read spice file contents. Subcircuits are read to circuit.Modules')
  optparser.add_option('--spice_header', dest='spice_header_files', default=[], action='append', help='read spice file headers. Subcircuits are read for port order and stored as ExternalModules')

  optparser.add_option('-s', '--dump_spice', dest='dump_spice', default=None, action='store', help='big spice file to write out')
  optparser.add_option('--test_manifest', dest='test_manifest', default=None, action='store', help='read this test manifest and try to find and add the results')
  optparser.add_option('--test_analysis', dest='test_analysis', default=None, action='store', help='read this analysis proto and try to find and add the results')

  optparser.add_option('-f', '--flatten_spice', dest='flatten_spice', default=False, action='store_true', help='flatten spice decks as much as possible')
  optparser.add_option('-d', '--working_dir', dest='working_dir', default=None, action='store', help='prefix directory to output all files')

  optparser.add_option('--delays_csv', dest='delays_csv', default=None, action='store', help='write CSV of measured delays')
  optparser.add_option('--input_caps_csv', dest='input_caps_csv', default='input_caps.csv', action='store', help='write CSV of measured delays')

  # TODO(growly): Helper options.
  optparser.add_option('--import', dest='import_circuit', default=False, action='store_true', help='import a circuit from verilog, SPEF, spice, etc')
  optparser.add_option('--load', dest='load', default=None, action='store', help='read circuit proto containing netlist')
  optparser.add_option('--save', dest='save', default=None, action='store', help='write circuit proto containing final netlist to this file')
  optparser.add_option('--show', dest='show_design', default=False, action='store_true', help='print summary of loaded design')

  optparser.add_option('--from_port', dest='from_port', default=None, action='store', help='dump passively-connected path from this port (requires --to_port)')
  optparser.add_option('--to_port', dest='to_port', default=None, action='store', help='dump passively-connected path to this port (requires --from_port)')

  optparser.add_option('--generate_input_capacitance_tests',
                       dest='generate_input_capacitance_tests',
                       default=False,
                       action='store_true',
                       help='generate spice tests for external module input capacitances')
  optparser.add_option('--analyze_input_capacitance_tests',
                       dest='analyze_input_capacitance_tests',
                       default=False,
                       action='store_true',
                       help='')

  optparser.add_option('--generate_module_tests',
                       dest='generate_module_tests',
                       default=False,
                       action='store_true',
                       help='')
  # TODO(growly): Normalize to incorrect English spelling.
  optparser.add_option('--analyze_module_tests',
                       dest='analyze_module_tests',
                       default=False,
                       action='store_true',
                       help='')


def GlobAndFlatten(files):
  flattened = []
  for spec in files:
    matched = glob.glob(spec)
    if not matched:
      flattened.append(spec)
      continue
    flattened.extend(matched)
  return flattened


def Main():
  optparser = OptionParser()
  DefineOptions(optparser)
  options, args = optparser.parse_args()
  return WithOptions(options)


def WithOptions(options: optparse.Values):

  # Make any output directories necessary.
  output_directory = options.working_dir or '.'
  if not os.path.exists(output_directory):
    os.makedirs(output_directory)
  output_directory = os.path.abspath(output_directory)

  # Check that input files exist.
  verilog_files = GlobAndFlatten(options.verilog_files)
  spef_files = GlobAndFlatten(options.spef_files)
  spice_headers = GlobAndFlatten(options.spice_header_files)
  spice_files = GlobAndFlatten(options.spice_files)
  file_names = options.verilog_files + options.spef_files + spice_headers + spice_files

  if options.test_manifest is not None:
    file_names.append(options.test_manifest)
  if options.test_analysis is not None:
    file_names.append(options.test_analysis)
  if options.load is not None:
    file_names.append(options.load)

  FilesExistOrError(file_names)

  spice_libs = [os.path.abspath(path) for path in spice_headers]

  design = Design()

  if options.load:
    # Read an existing circuit description (netlist) from disk.
    reader = circuit_writer.CircuitWriter(design)
    reader.ReadProtoToDesign(options.load)
  elif options.import_circuit:
    if spice_headers:
      design.ParseSpiceDefinitions(spice_headers, headers_only=True)

    if spice_files:
      design.ParseSpiceDefinitions(spice_files, headers_only=False)

    # TODO(growly): It would be nice to be able to add information from verilog,
    # SPEF, spice, etc, files to an existing circuit description. By which I mean,
    # it would be nice to be sure that works.
    if verilog_files:
      design.ParseVerilog(verilog_files, options.verilog_includes, options.verilog_defines)

    if spef_files:
      design.ParseSPEF(spef_files)

    # Turn references to modules by name into references by pointer.
    design.Link()
    design.CheckPowerAndGround()

  if options.show_design:
    design.Show()

  # Find top.
  if options.top_name:
    top = design.FindTop(options.top_name)
    if top is None:
      raise Exception(f'top not found: {options.top_name}')
      sys.exit(1)

  analyser = spice_analyser.SpiceAnalyser(design, output_directory, spice_libs)

  if options.generate_input_capacitance_tests:
    analyser.AddInputCapacitanceTestsForKnownModules(used_by_module=top)
    analyser.AddInputCapacitanceTestsForExternalModules(used_by_module=top)
    analyser.WriteMetadata(options.test_manifest, options.test_analysis)

  if options.analyze_input_capacitance_tests:
    RequireOptions(options, 'test_manifest', 'test_analysis')
    # Read results from a spice run.
    analyser.FindInputCapacitances(options.test_manifest, options.test_analysis)
    csv_file = PrefixRelativeName(
        output_directory, options.input_caps_csv) if options.input_caps_csv else None
    analyser.DumpInputCapacitances(csv_file)

  def SplitBusIndex(text):
    # s0[0] -> (s0, 0)
    # s0 -> (s0, None)
    # None -> None
    if text is None:
      return None
    # Bus delimiter: []
    match = re.match(r'(.*)\[(\d+)\]', text)
    if match is None:
      return text, None
    return match.group(1), match.group(2)

  # TODO(growly): Need to generalise VerilogIdentifier into something that can
  # specify a bus index, width, etc, then use that as the argument here
  # to allow users to specific bus pins as ports.
  if options.from_port and options.to_port:
    ignore_signals = set(['VGND', 'VPWR'])
    from_port, from_index = SplitBusIndex(options.from_port)
    if from_port in top.ports:
      start_port = top.ports[from_port]
    else:
      raise Exception(f'port not found in {top.name}: {from_port}')
      sys.exit(1)
    from_index = int(from_index) if from_index is not None else 0

    to_port, to_index = SplitBusIndex(options.to_port)
    if to_port in top.ports:
      stop_port = top.ports[to_port]
    else:
      raise Exception(f'port not found in {top.name}: {to_port}')
      sys.exit(1)
    to_index = int(to_index) if to_index is not None else 0

    region = circuit.Module.FindConnectedRegionBetweenPorts(
        start_port, stop_port,
        (from_index, from_index), (to_index, to_index),
        #probe_signal_names=set(['VPWR', 'VGND']),
        ignore_signals=ignore_signals)
    suffix = '_flat' if options.flatten_spice else ''
    region.name = (f'{start_port.signal.name}_{from_index}_{from_index}_'
                   f'{stop_port.signal.name}_{to_index}_{to_index}{suffix}')

    file_name = f'{region.name}.sp'
    full_path = os.path.join(output_directory, file_name)

    spice_writer = spice.SpiceWriter(design, flatten=options.flatten_spice)
    spice_writer.WriteRegion(full_path, region)

  if options.generate_module_tests:
    # TODO(growly): Move within SpiceAnalyser.
    # Find a reasonable seed wire for the search.
    #ignore_signals = set(self.design.power_net_names + self.design.ground_net_names)
    ignore_signals = set(['GND', 'VSS', 'VDD'])
    seed = None
    for port in top.ports.values():
      if port.signal in ignore_signals:
        continue
      seed = circuit.Wire(port.signal, 0)
    assert(seed is not None)

    #seed = circuit.Wire(top.ports['a'].signal, 0)
    seed = circuit.Wire(list(top.ports.values())[0].signal, 0)

    analyser.LoadRegionList(
        circuit.Module.ExtractPassiveRegions(seed, ignore_signals))

    analyser.AddRegionTests()
    analyser.AddModuleTest(top, use_regions=True)

    analyser.WriteMetadata(options.test_manifest, options.test_analysis)

  if options.analyze_module_tests:
    RequireOptions(options, 'test_manifest', 'test_analysis')
    csv_file = PrefixRelativeName(
        output_directory, options.delays_csv) if options.delays_csv else None
    analyser.AnalyseModuleTests(
        options.test_manifest,
        options.test_analysis,
        csv_file)

  if options.save is not None:
    writer = circuit_writer.CircuitWriter(design)
    save_file = PrefixRelativeName(output_directory, options.save)
    writer.WriteDesignToProto(save_file)
    writer.WriteDesignToTextProto(save_file + '.txt')

  if options.dump_spice is not None:
    spice_writer = spice.SpiceWriter(design, flatten=options.flatten_spice)
    spice_file = PrefixRelativeName(output_directory, options.dump_spice)
    spice_writer.WriteTop(spice_file)
    print(f'wrote top module ({top.name}) spice module: {spice_file}')



if __name__ == '__main__':
  Main()
