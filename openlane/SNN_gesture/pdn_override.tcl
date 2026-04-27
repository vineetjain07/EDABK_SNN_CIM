# Define the macro instances directly here to bypass LibreLane config validation
set ::env(FP_PDN_MACROS) "neuron_core_inst.synapse_matrix_inst.genblk1.*.X1_inst"
set ::env(FP_MACRO_HORIZONTAL_HALO) "50"
set ::env(FP_MACRO_VERTICAL_HALO) "20"

# 1) Global connections (Mapping ALL Caravel nets)
add_global_connection -net vccd1 -inst_pattern .* -pin_pattern vccd1 -power
add_global_connection -net vccd1 -inst_pattern .* -pin_pattern VDDC  -power
add_global_connection -net vdda1 -inst_pattern .* -pin_pattern VDDA  -power
add_global_connection -net vccd2 -inst_pattern .* -pin_pattern vccd2 -power
add_global_connection -net vdda2 -inst_pattern .* -pin_pattern vdda2 -power

add_global_connection -net vssd1 -inst_pattern .* -pin_pattern vssd1 -ground
add_global_connection -net vssd1 -inst_pattern .* -pin_pattern VSS   -ground
add_global_connection -net vssd2 -inst_pattern .* -pin_pattern vssd2 -ground
add_global_connection -net vssa1 -inst_pattern .* -pin_pattern vssa1 -ground
add_global_connection -net vssa2 -inst_pattern .* -pin_pattern vssa2 -ground

# 2) Voltage domain setup
# vccd1 is the primary power, vdda1 is added as secondary power to allow
# the PDN generator to create stripes for both within the same CORE area.
set_voltage_domain -name CORE -power vccd1 -ground vssd1 -secondary_power vdda1


# 3) Digital Core PDN Grid
define_pdn_grid -name stdcell_grid -starts_with POWER -voltage_domain CORE

# 4) Standard Cell M1 Rails (digital only)
# These are the horizontal rails that feed every standard cell row.
# NOTE: M1 is confirmed to already exist in the design from the Caravel DEF.
# This command ensures the PDN database registers them as power nets.

add_pdn_stripe -grid stdcell_grid -layer met1 -width 0.48 -followpins -starts_with POWER

# 5a) Digital Power Stripes (vccd1 / vssd1)
# offset=46 → stripes at Y=46, 226, 406, 586 ...
# -extend_to_boundary stretches stripes to the die edge to touch Caravel wrapper pins.
# met5 is widened to 6.0um to improve overlap with small 0.34um M3 secondary pin stubs on macros (after R270 rotation)

add_pdn_stripe -grid stdcell_grid -layer met4 -width 3.1 -pitch 180 -offset 20  -starts_with POWER -extend_to_boundary
add_pdn_stripe -grid stdcell_grid -layer met5 -width 6.0 -pitch 180 -offset 46  -starts_with POWER -extend_to_boundary

# 5b) Analog Power Stripes (vdda1 / vssa1)
# offset=136 → stripes at Y=136, 316, 496, 676 ... (interleaved between digital stripes)
add_pdn_stripe -grid stdcell_grid -layer met5 -width 6.0 -pitch 180 -offset 136 -starts_with POWER -extend_to_boundary -nets {vdda1 vssd1}

# 6) Macro Grid Configuration (handles BOTH VDDC->vccd1 and VDDA->vdda1)
# Macro power pins (VDDC, VDDA, VSS) are on met3 (confirmed from Neuromorphic_X1.lef).
# After R270 rotation, the M3 rails become VERTICAL.
# M4 is also VERTICAL -> parallel -> no via intersection possible.
# M5 is HORIZONTAL -> it DOES intersect rotated M3 -> via stack is placed here.

define_pdn_grid -macro -default -name macro_grid -starts_with POWER \
    -halo "$::env(FP_MACRO_HORIZONTAL_HALO) $::env(FP_MACRO_VERTICAL_HALO)"

# Connect macro met3 pins to global met5 via a via stack (met3->via3->met4->via4->met5)
add_pdn_connect -grid macro_grid -layers "met3 met5"

# 7) Via Connections ("Elevators" between metal layers)
# met1 -> met4: Connects standard cell M1 rails to the vertical M4 grid.
add_pdn_connect -grid stdcell_grid -layers "met1 met4"

# met3 -> met4: Connects macro power pins (on met3) to the vertical M4 grid.
#               This is the critical link that powers the Neuromorphic_X1 macros.
add_pdn_connect -grid stdcell_grid -layers "met3 met4"

# met4 -> met5: Connects vertical M4 to the top-level horizontal M5 distribution.
#               This is the link to the Caravel wrapper supply pins.
add_pdn_connect -grid stdcell_grid -layers "met4 met5"

 
# 8) Execute PDN generation
pdngen
