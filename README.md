# bigspicy

`bigspicy` is a tool for merging circuit descriptions (netlists), generating
Spice decks modeling those circuits, generating Spice tests to measure those
models, and analyzing the results of running Spice on those tests.

`bigspicy` allows you to combine structural Verilog from a PDK, Spice models of
standard cells, a structural Verilog model of some circuit implemented in that
PDK, and parasitics extracted into SPEF format. You can then reason about the
electrical structure of the design however you want.

`bigspicy` generates Spice decks in `Xyce` format, though this can (and should)
be extended to other Spice dialects. (That is why we recommend setting up
`Xyce` below.) 

## Prerequisites
You need:
- The protocol buffer compiler `protoc` 
- Icarus Verilog
- Xyce
  - Note this one is special, and takes some more care. 
- python3
  - pyverilog
  - numpy
  - matplotlib
  - protobuf

On debian-family Linuxes, several of the system-installed dependencies can be installed with  

```
sudo apt install -y protobuf-compiler iverilog
```

Given a `python` installation and environment, all other Python dependencies can be installed with  

```
pip install -e ".[dev]"
```

### Set up Xyce

Install the 'Serial' or 'Parallel' versions of Xyce. Follow the
[Xyce Building Guide](https://xyce.sandia.gov/documentation/BuildingGuide.html).

### Set up XDM

[XDM](https://github.com/Xyce/XDM) is needed to prepare Spice netlists generated for common proprietary Spice
engines for use with `Xyce`. It is only needed to prepare the input libraries used
by `bigspicy`, and only once for each corner in the PDK.

Follow the XDM [installation instructions](https://github.com/Xyce/XDM) on their
GitHub clone. If existing XDM-translated libraries are available, you can skip
this step.

## Compile protos and prepare PDK models

### Generating SPICE library files

Spice files fed to `bigspicy` should be in `Xyce` format because `bigspicy` does
minimal internal processing of the files and will include them almost verbatim.
That means that any PDK Spice files you receive should be converted to `Xyce`'s
spice dialect. The `xdm_bdl` tool (XDM) can do a lot of this for you, though
in some cases you will need to interfere by hand :(

#### e.g. Convert ASAP7 models using `xdm_bdl`

For example, for the `TT` corner and `RVT` ASAP7 cells:
```
xdm_bdl -s hspice ~growly/src/asap7PDK_r1p7/models/hspice/7nm_TT.pm -d lib
xdm_bdl -s hspice ~growly/src/asap7sc7p5t_27/CDL/xAct3D_extracted/asap7sc7p5t_27_R.sp -d lib
```

### Compile protobufs

```
protoc --proto_path vlsir vlsir/*.proto vlsir/*/*.proto --python_out=.
protoc proto/*.proto --python_out=.
```

## Usage


### Merge SPEF, Verilog and Spice information into Circuit protobuf

```
./bigspicy.py \
    --import \
    --verilog example_inputs/final.v \
    --spef example_inputs/final.spef \
    --spice_header lib/7nm_TT.pm \
    --spice_header lib/asap7sc7p5t_27_R.sp \
    --top fp_multiplier \
    --save final.pb \
    --working_dir /tmp/bigspicy
```

### Generate whole-module Spice model

```
./bigspicy.py \
    --load /tmp/bigspicy/final.pb \
    --spice_header lib/7nm_TT.pm \
    --spice_header lib/asap7sc7p5t_27_R.sp \
    --top fp_multiplier \
    --dump_spice fp_multiplier.sp
```

### Generate whole-module Spice model with transistors

```
./bigspicy.py \
    --load /tmp/bigspicy/final.pb \
    --spice_header lib/7nm_TT.pm \
    --spice_header lib/asap7sc7p5t_27_R.sp \
    --top fp_multiplier \
    --flatten_spice \
    --dump_spice fp_multiplier.sp
```

### Generate tests to measure input capacitance

```
./bigspicy.py \
    --load /tmp/bigspicy/final.pb \
    --spice_header lib/7nm_TT.pm \
    --spice_header lib/asap7sc7p5t_27_R.sp \
    --top fp_multiplier \
    --working_dir /tmp/bigspicy \
    --generate_input_capacitance_tests
```

This will generate all necessary test files in `/tmp/bigspicy`. It will also generate a test manifest, `test_manifest.pb`, and an analysis file `circuit_analysis.pb`, which you must specify as paths to subsequent analysis steps.

#### Run Xyce to perform tests

```
cd /tmp/bigspicy
for test in *.linearZ.sp *.transient_*.sp; do
  ~/XyceInstall/Serial/bin/Xyce "${test}" &
done
```

### Generate wire and whole-module tests

```
./bigspicy.py \
    --load /tmp/bigspicy/final.pb \
    --spice_def lib/7nm_TT.pm \
    --spice_def lib/asap7sc7p5t_27_R.sp \
    --top fp_multiplier \
    --working_dir /tmp/bigspicy \
    --generate_module_tests \
    --test_manifest /tmp/bigspicy/test_manifest.pb \
    --test_analysis /tmp/bigspicy/analysis.pb
```

#### Include results of external module measurements

```
./bigspicy.py \
    --load /tmp/bigspicy/final.pb \
    --spice_def lib/7nm_TT.pm \
    --spice_def lib/asap7sc7p5t_27_R.sp \
    --top fp_multiplier \
    --working_dir /tmp/bigspicy \
    --generate_module_tests \
    --test_manifest /tmp/bigspicy/test_manifest.pb \
    --test_analysis /tmp/bigspicy/analysis.pb \
    --analyze_input_capacitance_tests
```

#### Run Xyce to perform tests

```
cd /tmp/bigspicy
for test in *.linearY.sp *.transient.sp; do
  ~/XyceInstall/Serial/bin/Xyce "${test}" &
done
```

### Perform analysis on wire and whole-module tests

```
./bigspicy.py \
    --load /tmp/bigspicy/final.pb \
    --spice_def lib/7nm_TT.pm \
    --spice_def lib/asap7sc7p5t_27_R.sp \
    --top fp_multiplier \
    --working_dir /tmp/bigspicy \
    --test_manifest /tmp/bigspicy/test_manifest.pb \
    --test_analysis /tmp/bigspicy/analysis.pb \
    --analyze_module_tests \
    --input_caps_csv=input_caps.csv \
    --delays_csv=delays.csv
```
