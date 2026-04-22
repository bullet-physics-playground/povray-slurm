#version 3.7;

global_settings { assumed_gamma 1.0 }

camera {
  location <0, 2, -10>
  look_at <0, 0, 0>
}

light_source { <10, 10, -10> color rgb <1,1,1> }

sphere {
  <clock*5 - 2.5, 0, 0>, 1
  texture { pigment { color rgb <1, 0, 0> } }
}

plane {
  y, -1
  texture { pigment { color rgb <0.8,0.8,0.8> } }
}
