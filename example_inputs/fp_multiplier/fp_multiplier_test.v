// Copyright 2022 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
//
// SPDX-License-Identifier: Apache-2.0

`timescale  1ns/1ns

module fp_multiplier_test;

reg clk, rst;
localparam CLOCK_PERIOD = 20;   // nanoseconds

initial clk = 0;
always #(CLOCK_PERIOD/2) clk = ~clk;

// bfloat16
localparam INPUT_SIGN_WIDTH = 1;
localparam INPUT_EXPONENT_WIDTH = 8;
localparam INPUT_MANTISSA_WIDTH = 7;
localparam INPUT_WIDTH = INPUT_SIGN_WIDTH + INPUT_EXPONENT_WIDTH + INPUT_MANTISSA_WIDTH;
localparam signed INPUT_EXPONENT_BIAS = -32'sd127;

// IEEE 754 single-precision 32-bit float
localparam OUTPUT_SIGN_WIDTH = 1;
localparam OUTPUT_EXPONENT_WIDTH = 8;
localparam OUTPUT_MANTISSA_WIDTH = 23;
localparam OUTPUT_WIDTH = OUTPUT_SIGN_WIDTH + OUTPUT_EXPONENT_WIDTH + OUTPUT_MANTISSA_WIDTH;
localparam signed OUTPUT_EXPONENT_BIAS = -32'sd127;

reg [INPUT_WIDTH-1:0] a, b;
wire [OUTPUT_WIDTH-1:0] y;
reg [OUTPUT_WIDTH-1:0] c;

// y = {y_sign, y_exponent, y_mantissa}
wire [OUTPUT_SIGN_WIDTH-1:0] y_sign = y[OUTPUT_WIDTH-OUTPUT_SIGN_WIDTH +: OUTPUT_SIGN_WIDTH];
wire [OUTPUT_EXPONENT_WIDTH-1:0] y_exponent =
    y[OUTPUT_MANTISSA_WIDTH +: OUTPUT_EXPONENT_WIDTH];
wire [OUTPUT_MANTISSA_WIDTH-1:0] y_mantissa = y[0 +: OUTPUT_MANTISSA_WIDTH];

// y = a * b
fp_multiplier #(
  .INPUT_SIGN_WIDTH(INPUT_SIGN_WIDTH),
  .INPUT_EXPONENT_WIDTH(INPUT_EXPONENT_WIDTH),
  .INPUT_MANTISSA_WIDTH(INPUT_MANTISSA_WIDTH),
  .INPUT_WIDTH(INPUT_WIDTH),
  .INPUT_EXPONENT_BIAS(INPUT_EXPONENT_BIAS),
  .OUTPUT_SIGN_WIDTH(OUTPUT_SIGN_WIDTH),
  .OUTPUT_EXPONENT_WIDTH(OUTPUT_EXPONENT_WIDTH),
  .OUTPUT_MANTISSA_WIDTH(OUTPUT_MANTISSA_WIDTH),
  .OUTPUT_WIDTH(OUTPUT_WIDTH),
  .OUTPUT_EXPONENT_BIAS(OUTPUT_EXPONENT_BIAS)
) dut (
  .a(a),
  .b(b),
  .y(y)
);

initial begin
  $dumpfile("fp_multiplier_test.vcd");
  $dumpvars;

  $display("Hand-written sanity-check:");
  // Hand-written sanity-check.
  a = 16'b0_10000000_1000000;
  b = 16'b0_10000100_1001000;
  // This circuit is purely combinational but I guess we still need a clock
  // cycle to load the registers? Or at least 1 tick to propagate?
  #CLOCK_PERIOD;
  $display("%b", y);
  $display("did normalise: %b", dut.do_normalise);
  $display("%b %b %b\n", y_sign, y_exponent, y_mantissa);

  $display("Another hand-written sanity check.");
  // Hand-written sanity-check.
  a = 16'b1_11111000_1110000;
  b = 16'b1_10110100_1100100;
  // This circuit is purely combinational but I guess we still need a clock
  // cycle to load the registers? Or at least 1 tick to propagate?
  #CLOCK_PERIOD;
  $display("%b", y);
  $display("did normalise: %b", dut.do_normalise);
  $display("%b %b %b\n", y_sign, y_exponent, y_mantissa);

  $display("Automatic cases:");
  //`include "auto_cases.v"

  $display("done");
  $finish;
end

endmodule
