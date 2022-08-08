# Copyright 2022 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0

DESIGN_DIR                   := $(realpath $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST)))))
DESIGN_PDK_HOME              := $(realpath $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST)))))

# This is top:
export DESIGN_NAME            = fp_multiplier
# These are something else:
export DESIGN_NICKNAME        = fp_multiplier
export DESIGN                 = fp_multiplier

export PLATFORM               = sky130hd

#export VERILOG_FILES          = $(sort $(wildcard $(abspath $(DESIGN_DIR)/../../src/$(DESIGN))/*.v))
export SOURCE_DIR	      = /home/aryap/src/bigspicy/example_inputs/fp_multiplier
export VERILOG_FILES          = ${SOURCE_DIR}/fp_multiplier.v
export SDC_FILE               = $(DESIGN_DIR)/constraint.sdc

export CORNER                ?= BC

export LIB_FILES             += $($(CORNER)_LIB_FILES)
export LIB_DIRS              += $($(CORNER)_LIB_DIRS)
export DB_FILES              += $($(CORNER)_DB_FILES)
export DB_DIRS               += $($(CORNER)_DB_DIRS)
export WRAP_LIBS             += $(WRAP_$(CORNER)_LIBS)
export WRAP_LEFS             += $(WRAP_$(CORNER)_LEFS)
export TEMPERATURE            = $($(CORNER)_TEMPERATURE)

export ABC_CLOCK_PERIOD_IN_PS = 400

export DESIGN_POWER           = VDD
export DESIGN_GROUND          = VSS

export CORNER                ?= BC

export PDN_CFG                = $(FOUNDRY_DIR)/openRoad/pdn/grid_strategy-M2-M5-M7.cfg

export DONT_USE_SC_LIB        = $(OBJECTS_DIR)/lib/merged.lib

export PLACE_DENSITY          = 0.99


ifdef ($(ASAP7_USE4X)) 
  export DIE_AREA               = 0 0 50 50
  export CORE_AREA              = 0.5 0.5 49.5 49.5
else
  export DIE_AREA               = 0 0 12.2 12.2
  export CORE_AREA              = 1.08 1.08 11.12 11.12
endif

# Adders degrade GCD
export ADDER_MAP_FILE              :=

export DESIGN_DIR DESIGN_PDK_HOME
