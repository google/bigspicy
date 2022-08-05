To get OpenROAD to work on this design I had to disable CTS and assign pins the
hard way. Here is a diff of the changes, since I don't expect the code will be
stable enough to warrant a patch file:

```diff
diff --git a/flow/Makefile b/flow/Makefile
index eeb29ed..eebf480 100644
--- a/flow/Makefile
+++ b/flow/Makefile
@@ -74,6 +74,7 @@
 # DESIGN_CONFIG=./designs/sky130hs/ibex/config_ppa.mk
 # DESIGN_CONFIG=./designs/sky130hs/jpeg/config_ppa.mk
 
+DESIGN_CONFIG=./designs/asap7/fp_multiplier/config.mk
 # DESIGN_CONFIG=./designs/asap7/gcd/config.mk
 # DESIGN_CONFIG=./designs/asap7/ibex/config.mk
 # DESIGN_CONFIG=./designs/asap7/aes/config.mk
@@ -83,7 +84,7 @@
 # DESIGN_CONFIG=./designs/intel22/aes/config.mk
 #
 # Default design
-DESIGN_CONFIG ?= ./designs/nangate45/gcd/config.mk
+#DESIGN_CONFIG ?= ./designs/nangate45/gcd/config.mk
 # Global override Floorplan
 # export CORE_UTILIZATION := 30
 # export CORE_ASPECT_RATIO := 1
diff --git a/flow/scripts/cts.tcl b/flow/scripts/cts.tcl
index 913b830..9e52659 100644
--- a/flow/scripts/cts.tcl
+++ b/flow/scripts/cts.tcl
@@ -43,22 +43,22 @@ if {[info exist ::env(CTS_CLUSTER_DIAMETER)]} {
   set cluster_diameter 100
 }
 
-if {[info exist ::env(CTS_BUF_DISTANCE)]} {
-clock_tree_synthesis -root_buf "$::env(CTS_BUF_CELL)" -buf_list "$::env(CTS_BUF_CELL)" \
-                     -sink_clustering_enable \
-                     -sink_clustering_size $cluster_size \
-                     -sink_clustering_max_diameter $cluster_diameter \
-                     -distance_between_buffers "$::env(CTS_BUF_DISTANCE)"
-} else {
-clock_tree_synthesis -root_buf "$::env(CTS_BUF_CELL)" -buf_list "$::env(CTS_BUF_CELL)" \
-                     -sink_clustering_enable \
-                     -sink_clustering_size $cluster_size \
-                     -sink_clustering_max_diameter $cluster_diameter \
-
-}
-
-
-set_propagated_clock [all_clocks]
+#if {[info exist ::env(CTS_BUF_DISTANCE)]} {
+#clock_tree_synthesis -root_buf "$::env(CTS_BUF_CELL)" -buf_list "$::env(CTS_BUF_CELL)" \
+#                     -sink_clustering_enable \
+#                     -sink_clustering_size $cluster_size \
+#                     -sink_clustering_max_diameter $cluster_diameter \
+#                     -distance_between_buffers "$::env(CTS_BUF_DISTANCE)"
+#} else {
+#clock_tree_synthesis -root_buf "$::env(CTS_BUF_CELL)" -buf_list "$::env(CTS_BUF_CELL)" \
+#                     -sink_clustering_enable \
+#                     -sink_clustering_size $cluster_size \
+#                     -sink_clustering_max_diameter $cluster_diameter \
+#
+#}
+#
+
+#set_propagated_clock [all_clocks]
 
 set_dont_use $::env(DONT_USE_CELLS)
 
@@ -67,7 +67,7 @@ source $::env(SCRIPTS_DIR)/report_metrics.tcl
 estimate_parasitics -placement
 report_metrics "cts pre-repair"
 
-repair_clock_nets
+#repair_clock_nets
 
 estimate_parasitics -placement
 report_metrics "cts post-repair"
diff --git a/flow/scripts/io_placement.tcl b/flow/scripts/io_placement.tcl
index 8900de2..e9d705d 100644
--- a/flow/scripts/io_placement.tcl
+++ b/flow/scripts/io_placement.tcl
@@ -24,7 +24,12 @@ if {![info exists ::env(FOOTPRINT)]} {
     source $::env(IO_CONSTRAINTS)
   }
   place_pins -hor_layer $::env(IO_PLACER_H) \
-             -ver_layer $::env(IO_PLACER_V)
+             -ver_layer $::env(IO_PLACER_V) \
+             -group_pins {a[0] a[1] a[2] a[3] a[4] a[5] a[6] a[7] a[8] a[9] a[10] a[11] a[12] a[13] a[14] a[15]} \
+             -group_pins {b[0] b[1] b[2] b[3] b[4] b[5] b[6] b[7] b[8] b[9] b[10] b[11] b[12] b[13] b[14] b[15]} \
+             -group_pins {b[0] b[1] b[2] b[3] b[4] b[5] b[6] b[7] b[8] b[9] b[10] b[11] b[12] b[13] b[14] b[15]} \
+             -group_pins {y[0] y[1] y[2] y[3] y[4] y[5] y[6] y[7] y[8] y[9] y[10] y[11] y[12] y[13] y[14] y[15]} \
+             -group_pins {y[16] y[17] y[18] y[19] y[20] y[21] y[22] y[23]}
 }
 
 if {![info exists standalone] || $standalone} {
```
