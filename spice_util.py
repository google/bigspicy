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
import numpy as np
import collections
import math
import re
from enum import Enum

FFTResultDataPoint = collections.namedtuple(
        'FFTResultDataPoint', ['index', 'freq_hz', 'magnitude', 'phase_deg'])

class NumericalValue():
  def __init__(self, value, unit=None):
    self.value = value
    self.unit = unit

  def __repr__(self):
    return f'{self.value} prefix:{self.unit}'

  def __str__(self):
    letter = self.unit.Letter() if self.unit else ''
    return f'{self.value}{letter}'

  def InBaseUnits(self):
    new_value = self.value
    unit = self.unit
    if unit is not None:
      shift = unit.value
      new_value = new_value * math.pow(10, shift)
    return NumericalValue(new_value, None)

  def _InOtherUnits(self, other_unit):
    if other_unit == self.unit:
      return self
    other_power = other_unit.value if other_unit else 0
    self_power = self.unit.value if self.unit else 0
    power_difference = self_power - other_power
    new_value = self.value * math.pow(10, power_difference)
    return NumericalValue(new_value, other_unit)

  def __eq__(self, other):
    return self._InOtherUnits(other.unit).value == other.value

  def __lt__(self, other):
    val = self._InOtherUnits(other.unit).value < other.value
    #print(f'{self} < {other} = {val}')
    return val

  def __ge__(self, other):
    return other < self

  def SpiceFormat(self):
    # Use:
    # t
    # g
    # meg
    # k
    # m
    # u
    # n
    # p
    # f
    pass

  def XyceFormat(self):
    return str(self.InBaseUnits().value).upper()


class SIUnitPrefix(Enum):
  YOCTO = -24
  ZEPTO = -21
  ATTO = -18
  FEMTO = -15
  PICO = -12
  NANO = -9
  MICRO = -6
  MILLI = -3
  CENTI = -2
  DECI = -1
  DECA = 1
  HECTO = 2
  KILO = 3
  MEGA = 6
  GIGA = 9
  TERA = 12
  PETA = 15
  EXA = 18
  ZETTA = 21
  YOTTA = 24

  def Letter(self):
    return _LETTER_BY_UNIT[self]


_LETTER_BY_UNIT = {
  SIUnitPrefix.YOCTO: 'y',
  SIUnitPrefix.ZEPTO: 'z',
  SIUnitPrefix.ATTO: 'a',
  SIUnitPrefix.FEMTO: 'f',
  SIUnitPrefix.PICO: 'p',
  SIUnitPrefix.NANO: 'n',
  SIUnitPrefix.MICRO: 'u',
  SIUnitPrefix.MILLI: 'm',
  SIUnitPrefix.CENTI: 'c',
  SIUnitPrefix.DECI: 'd',
  SIUnitPrefix.DECA: 'da',
  SIUnitPrefix.HECTO: 'h',
  SIUnitPrefix.KILO: 'k',
  SIUnitPrefix.MEGA: 'M',
  SIUnitPrefix.GIGA: 'G',
  SIUnitPrefix.TERA: 'T',
  SIUnitPrefix.PETA: 'P',
  SIUnitPrefix.EXA: 'E',
  SIUnitPrefix.ZETTA: 'Z',
  SIUnitPrefix.YOTTA: 'Y'
}


class SmallSignalParameters:

  def __init__(self, str_tokens):
    """Consume the AC measurements from Spice, less the first column."""
    dim = math.sqrt(len(str_tokens)/2.0)
    if not dim.is_integer():
        raise Exception(f'expecting square number of columns, not {dim}')
    dim = int(dim)
    values = []
    i = 0
    while i < len(str_tokens):
      values.append(
          np.cdouble(complex(float(str_tokens[i]), float(str_tokens[i+1]))))
      i += 2
    self.matrix = np.resize(np.matrix(values), (dim, dim))
    self.type = None

  def Print(self):
    print(self.matrix)

  def __getitem__(self, key):
    butchered_key = tuple(k - 1 for k in key)
    return self.matrix.__getitem__(butchered_key)


def ReadMeasurementsFile(file_name):
  """Interprets Xyce-generated .mt0 files."""
  if not os.path.exists(file_name):
    #print(f'file not found: {file_name}')
    return {}
  print(f'reading {file_name}')
  variables = {}
  with open(file_name, 'r') as f:
    for line in f:
      key, value = line.split(' = ')
      variables[key] = float(value)
  return variables


def ReadFFTFile(file_name):
  if not os.path.exists(file_name):
      return {}
  print(f'reading {file_name}')
  DC_LINE_RE = re.compile(
      '^DC component.*(?:Norm. )?Mag= ([0-9.eE+-]+).*Phase= ([\d.eE+-]+).*$')
  # NOTE(growly): We assume that we only every look at the V( ) voltage 
  # of a signal. Otherwise change this regex:
  HEADER_LINE_RE = re.compile('^FFT analysis for V\((.*)\):$')
  # The .fft0 file will contains, one after another, dumps of FFT
  # measurements for each signal given to Spice. We collect the
  # FFTResultDataPoint of each into this dict.
  analyses = {}
  with open(file_name, 'r') as f:
    data = None
    signal_name = None
    for line in f:
      if line.startswith('FFT analysis'):
        # Store data for last signal being listed.
        # Prep for more data.
        match = HEADER_LINE_RE.match(line)
        signal_name = match.group(1)  
        data = []
        continue
      if line.startswith('DC component'):
        match = DC_LINE_RE.match(line)
        if not match:
          raise Exception(f'{line} did not match')
        data.append(FFTResultDataPoint(
            index = -1,
            freq_hz = 0.0,
            magnitude = float(match.group(1)),
            phase_deg = float(match.group(2))))
        continue
      split = line.split()
      try:
        point = FFTResultDataPoint(
            index = int(split[0]),
            freq_hz = float(split[1]),
            magnitude = float(split[2]),
            phase_deg = float(split[3]))
      except:
        # Probably not a result line
        continue
      if data is not None:
        data.append(point)
    assert signal_name not in analyses
    if signal_name and data:
      analyses[signal_name] = data
  return analyses


def ReadPrintFileForTimeSeries(file_name):
  if not os.path.exists(file_name):
    return {}
  print(f'reading {file_name}')
  data_by_header = {}
  with open(file_name, 'r') as f:
    headers = None
    for line in f:
      if line.startswith('End'):
        continue
      if headers is None:
        headers = line.split()
        for header in headers:
          data_by_header[header] = []
        continue
      tokens = line.split()
      for i, token in enumerate(tokens):
        data_by_header[headers[i]].append(float(tokens[i]))
  return data_by_header


def ReadPrintFile(file_name):
  # We expect one line of headers.
  if not os.path.exists(file_name):
    return []
  print(f'reading {file_name}')
  with open(file_name, 'r') as f:
    headers = None
    data = []
    for line in f:
      if line.startswith('End'):
        continue
      if headers is None:
        headers = line.split()
        continue
      tokens = line.split()
      data.append({headers[i]: tokens[i] for i in range(len(tokens))})
  return data


def ReadCSVFile(file_name):
  if not os.path.exists(file_name):
    return []
  print(f'reading {file_name}')
  with open(file_name, 'r') as f:
    return [row for row in csv.DictReader(f)]
  return []


def ReadStepFile(file_name):
  header_to_column = {}
  column_to_header = {}
  if not os.path.exists(file_name):
    return {}
  params = {}
  print(f'reading {file_name}')
  with open(file_name, 'r') as f:
    for line in f:
      if line.startswith('End'):
        break
      if not header_to_column:
        tokens = line.split()
        for i, token in enumerate(tokens):
          header_to_column[token] = i
          column_to_header[i] = token
        continue
      tokens = line.split()
      step = int(tokens[header_to_column['STEP']])
      params[step] = {
          column_to_header[k]: token for k, token in enumerate(tokens)}
  return params


def ReadACAnalysisFile(file_name):
  if not os.path.exists(file_name):
      return {}
  ac_analysis = collections.defaultdict(dict)
  print(f'reading {file_name}')
  with open(file_name) as f:
    last_freq_hz = None
    step = -1
    read_parameters = False
    for line in f:
      if line.strip() == '[Network Data]':
        read_parameters = True
        continue
      if line.strip()== '[End]':
        read_parameters = False
        continue
      if line.startswith('!'):
        continue
      if read_parameters:
        tokens = line.split()
        freq_hz = float(tokens[0])
        if last_freq_hz is None or freq_hz < last_freq_hz:
            # We've moved onto the next step.
          step += 1
        last_freq_hz = freq_hz
        ac_analysis[step][freq_hz] = SmallSignalParameters(tokens[1:])
  return ac_analysis
