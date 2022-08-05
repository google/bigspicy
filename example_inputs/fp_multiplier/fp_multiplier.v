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

// Floating-point multiplier unit.
//
// Input/output formats are:
//  MSB                                                       LSB
//  |<-- sign bits --><-- exponent bits --><-- mantissa bits -->|
//
// Mantissa are assumed to be normalised at the input, and are normalised at
// the output. Subnormal numbers are not supported.

// fp_decoder extracts interesting signals from an input floating-point value.
module fp_decoder #(
  parameter SIGN_WIDTH = 1,
  parameter EXPONENT_WIDTH = 8,
  parameter MANTISSA_WIDTH = 7,
  parameter WIDTH = SIGN_WIDTH + EXPONENT_WIDTH + MANTISSA_WIDTH
) (
  input [WIDTH-1:0] value,
  output [SIGN_WIDTH-1:0] sign,
  output [MANTISSA_WIDTH-1:0] mantissa,
  output signed [EXPONENT_WIDTH-1:0] exponent,
  output isPositiveInf,
  output isNegativeInf,
  output isPositiveNaN,
  output isNegativeNaN
);

assign exponent = value[EXPONENT_WIDTH+MANTISSA_WIDTH-1:MANTISSA_WIDTH];
assign mantissa = value[MANTISSA_WIDTH-1:0];
assign sign = value[WIDTH-1:WIDTH-SIGN_WIDTH];

wire exponent_all_high = &exponent;
wire mantissa_any_high = &mantissa;

assign isPositiveInf = ~sign & exponent_all_high & ~mantissa_any_high;
assign isNegativeInf = sign & exponent_all_high & ~mantissa_any_high;
assign isPositiveNaN = ~sign & exponent_all_high & mantissa_any_high;
assign isNegativeNaN = sign & exponent_all_high & mantissa_any_high;

endmodule

// fp_multiplier does the multiplying and normalising.
module fp_multiplier #(
  // bfloat16
  parameter INPUT_SIGN_WIDTH = 1,
  parameter INPUT_EXPONENT_WIDTH = 8,
  parameter INPUT_MANTISSA_WIDTH = 7,
  parameter INPUT_WIDTH = INPUT_SIGN_WIDTH + INPUT_EXPONENT_WIDTH + INPUT_MANTISSA_WIDTH,
  parameter signed INPUT_EXPONENT_BIAS = -32'sd127,

  // IEEE 754 single-precision 32-bit float
  parameter OUTPUT_SIGN_WIDTH = 1,
  parameter OUTPUT_EXPONENT_WIDTH = 8,
  parameter OUTPUT_MANTISSA_WIDTH = 23,
  parameter OUTPUT_WIDTH = OUTPUT_SIGN_WIDTH + OUTPUT_EXPONENT_WIDTH + OUTPUT_MANTISSA_WIDTH,
  parameter signed OUTPUT_EXPONENT_BIAS = -32'sd127
) (
  input [INPUT_WIDTH-1:0] a,
  input [INPUT_WIDTH-1:0] b,
  output [OUTPUT_WIDTH-1:0] y
);

wire signed [INPUT_EXPONENT_WIDTH-1:0] exponent_a;
wire [INPUT_MANTISSA_WIDTH-1:0] stored_mantissa_a;
wire [INPUT_SIGN_WIDTH-1:0] sign_a;

wire signed [INPUT_EXPONENT_WIDTH-1:0] exponent_b;
wire [INPUT_MANTISSA_WIDTH-1:0] stored_mantissa_b;
wire [INPUT_SIGN_WIDTH-1:0] sign_b;

fp_decoder #(
  .SIGN_WIDTH(INPUT_SIGN_WIDTH),
  .EXPONENT_WIDTH(INPUT_EXPONENT_WIDTH),
  .MANTISSA_WIDTH(INPUT_MANTISSA_WIDTH)
) decoder_a (
  .value(a),
  .sign(sign_a),
  .mantissa(stored_mantissa_a),
  .exponent(exponent_a)
);

fp_decoder #(
  .SIGN_WIDTH(INPUT_SIGN_WIDTH),
  .EXPONENT_WIDTH(INPUT_EXPONENT_WIDTH),
  .MANTISSA_WIDTH(INPUT_MANTISSA_WIDTH)
) decoder_b (
  .value(b),
  .sign(sign_b),
  .mantissa(stored_mantissa_b),
  .exponent(exponent_b)
);

// Multiply mantissa.
//
// This product is twice as wide as the extended mantissas (i.e. when they
// include the leading 1 implicit in the encoding format).
//
// The 0th bit (i.e. where the decimal point is) is the 2nd place from the
// MSB. We truncate from the 3rd bit down to store in the output mantissa.
//
// If the MSB of the product is 1, we have to shift the decimal place up and
// adjust the exponent to account for the move (by adding 1).
//
//                            mantissa
//                            product
//                         <- width ------->
//   <--7-->     <--7-->      <-----14----->
// 1.mmmmmmm * 1.mmmmmmm = xx.mmmmmmmmmmmmmm
//                         |        |  normalised and
//   check for normalisation        |  packed into output
//                                  v  mantissa
//                          y.mmmmmmmmmmmmmm00
//
// If the output format can't fit the result, we have to truncate the
// mantissa. If the output format can fit the result and has extra precision,
// we have to pad with zeroes:
//
//                          y.mmmmmmmmmmmmmm00
//                                  |
//                        +---------+---------------+
//                        v                         v
//                    y.mmmmmmm        y.mmmmmmmmmmmmmm0000000000
//
localparam MANTISSA_PRODUCT_WIDTH = 2*(INPUT_MANTISSA_WIDTH+1);
wire [MANTISSA_PRODUCT_WIDTH-1:0] mantissa_product =
    {1'b1, stored_mantissa_a} * {1'b1, stored_mantissa_b};

// Sum exponents. The result might be up to 1 bit wider than the two summands.
wire signed [INPUT_EXPONENT_WIDTH:0] exponent_sum =
    (exponent_a + INPUT_EXPONENT_BIAS) + (exponent_b + INPUT_EXPONENT_BIAS);

// Normalise mantissa and adjust exponent accordingly.
wire do_normalise = mantissa_product[MANTISSA_PRODUCT_WIDTH-1];

// If we have to normalise, this becomes the new exponent.
wire signed [INPUT_EXPONENT_WIDTH:0] exponent_sum_plus_one = exponent_sum + 1'b1;

// TODO(growly): Might need more explicit shifting/concatenation here too.
wire signed [OUTPUT_EXPONENT_WIDTH-1:0] exponent_select =
    do_normalise ? exponent_sum_plus_one : exponent_sum;

// Add bias.
wire signed [OUTPUT_EXPONENT_WIDTH-1:0] exponent_out =
    exponent_select - OUTPUT_EXPONENT_BIAS;

// TODO(growly): Rounding

localparam UNSHIFTED_WIDTH_DIFF = OUTPUT_MANTISSA_WIDTH - 2*INPUT_MANTISSA_WIDTH;
localparam UNSHIFTED_ZEROES = UNSHIFTED_WIDTH_DIFF >= 0 ? UNSHIFTED_WIDTH_DIFF : 0;
localparam UNSHIFTED_LOW_INDEX = UNSHIFTED_WIDTH_DIFF >=0 ? 0 : -UNSHIFTED_WIDTH_DIFF;
wire [OUTPUT_MANTISSA_WIDTH-1:0] mantissa_product_unshifted = {
    mantissa_product[MANTISSA_PRODUCT_WIDTH-3:UNSHIFTED_LOW_INDEX],
    {UNSHIFTED_ZEROES{1'b0}}};

localparam SHIFTED_WIDTH_DIFF = OUTPUT_MANTISSA_WIDTH - (2*INPUT_MANTISSA_WIDTH + 1);
localparam SHIFTED_ZEROES = SHIFTED_WIDTH_DIFF >= 0 ? SHIFTED_WIDTH_DIFF : 0;
localparam SHIFTED_LOW_INDEX = SHIFTED_WIDTH_DIFF >=0 ? 0 : -SHIFTED_WIDTH_DIFF;
wire [OUTPUT_MANTISSA_WIDTH-1:0] mantissa_product_shifted = {
    mantissa_product[MANTISSA_PRODUCT_WIDTH-2:SHIFTED_LOW_INDEX],
    {SHIFTED_ZEROES{1'b0}}};

// A big ol' mux.
wire [OUTPUT_MANTISSA_WIDTH-1:0] mantissa_out =
    do_normalise ? mantissa_product_shifted : mantissa_product_unshifted;

// Note that this doesn't make sense for INPUT_SIGN_WIDTH > 1.
wire output_sign = sign_a ^ sign_b;

assign y = {output_sign, exponent_out, mantissa_out};

endmodule
