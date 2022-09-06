module test (
  VGND,
  VPWR,
  hi
);
  input VGND;
  input VPWR;
  output hi;

  sky130_fd_sc_hd__conb_1 const_hi (
    .HI(hi),
    .VGND(VGND),
    .VNB(VGND),
    .VPB(VPWR),
    .VPWR(VPWR));

endmodule
