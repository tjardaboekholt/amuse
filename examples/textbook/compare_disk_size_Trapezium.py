import sys
import numpy
import math
from matplotlib import pyplot
from amuse.lab import *

from prepare_figure import single_frame, figure_frame, set_tickmarks
from distinct_colours import get_distinct

import pickle

filepointer = open("Obs_Trapezium_disksizes.pkl", 'r')
(R_obs, yc_obs) = pickle.load(filepointer)
filepointer.close()
filepointer = open("Tr_N2000_R0.5pc_Q0.5_F1.6.pkl", 'r')
(R_sim, yc_sim) = pickle.load(filepointer)
filepointer.close()
print len(R_obs), len(yc_obs)
print len(R_sim), len(yc_sim)

color = get_distinct(2)

x_label = 'R [$R_\odot$]'
y_label = '$f_{<R}$'
figure = single_frame(x_label, y_label, xsize=14, ysize=10)

pyplot.plot(R_obs, 95*yc_obs, c=color[0])
pyplot.plot(R_sim, 95*yc_sim, c=color[1], ls="--")
#pyplot.show()
pyplot.savefig("Tr_N2000_R05pc_Q05_F16_r1")


