import time
import numpy

from amuse.lab import *
from amuse.units import units,nbody_system
from amuse.datamodel import Particles

from amuse.community.fi.interface import Fi
from amuse.community.gadget2.interface import Gadget2

from cooling_class import Cooling, SimplifiedThermalModelEvolver
from amuse.ext.sink import SinkParticles

COOL = False

class Hydro:
        def __init__(self, hydro_code, particles):
                
                if not hydro_code in [Fi,Gadget2]:
                    raise Exception("unsupported Hydro code: %s"%(hydro_code.__name__))

                self.typestr = "Hydro"
                self.namestr = hydro_code.__name__

                system_size = 2|units.parsec
                
                eps = 0.05 | units.parsec
                Mcloud = particles.mass.sum()
                N = len(particles)
                dt = 0.2*numpy.pi*numpy.power(eps, 1.5)/numpy.sqrt(constants.G*Mcloud/N)
                print "Hydro timesteps:", dt, "N=", len(particles)

                self.gas_particles = particles
                self.sink_particles = Particles(0)
                
                self.cooling_flag = "thermal_model"

                self.density_threshold = (1|units.MSun)/(eps)**3
                self.merge_radius = eps

                self.converter = nbody_system.nbody_to_si(1|units.MSun, system_size)

                if hydro_code is Fi:
                        self.code = hydro_code(self.converter, mode="openmp", redirection="file")

                        self.code.parameters.begin_time= 0.0|units.Myr
                        self.code.parameters.use_hydro_flag=True
                        self.code.parameters.self_gravity_flag=True
                        self.code.parameters.periodic_box_size = 100.*system_size
                        """
                        isothermal_flag:
                        When True then we have to do our own adiabatic cooling (and Gamma has to be 1.0)
                        When False then we dont do the adjabatic cooling and Fi is changing u
                        """
                        self.code.parameters.isothermal_flag=True
                        self.code.parameters.integrate_entropy_flag=False
                        self.code.parameters.timestep = 0.5*dt
                        #self.code.parameters.verbosity=99
                        self.code.parameters.verbosity=0
                        
                        self.code.parameters.gamma=1
                        self.code.parameters.integrate_entropy_flag=False
                        self.gamma = self.code.parameters.gamma

                if hydro_code is Gadget2:
                        print "WARNING: Gadget support is WIP"
                        print "check the Gadget2 makefile_options"
                        # todo: variable number_of_workers
                        self.code = hydro_code(self.converter, number_of_workers=4)
                        self.code.parameters.begin_time= 0.0|units.Myr
                        self.code.parameters.time_max=dt*2**int(numpy.log2(4*(10|units.Myr)/dt))
                        self.code.parameters.max_size_timestep=0.5*dt
                        #~ self.code.parameters.min_size_timestep=
                        print "Isofag;", self.code.parameters.isothermal_flag
                        print "gamma=",  self.code.parameters.polytropic_index_gamma
                        #assert self.code.parameters.isothermal_flag == True
                        assert self.code.parameters.no_gravity_flag == False
                        # constant gas smoothing
                        self.code.parameters.gas_epsilon=eps
                        assert self.code.parameters.eps_is_h_flag==False
                        #assert self.code.parameters.polytropic_index_gamma == 1.

                        if self.cooling_flag=="internal":
                            raise Exception("gadget internal cooling not implemented")

                        self.gamma = self.code.parameters.polytropic_index_gamma

                self.code.parameters.stopping_condition_maximum_density = self.density_threshold
                self.code.commit_parameters()
                        
                if len(self.gas_particles)>0:
                    self.code.gas_particles.add_particles(self.gas_particles)

                self.parameters = self.code.parameters
                
                print self.code.parameters
                
                # In order to be using the bridge
                self.get_gravity_at_point = self.code.get_gravity_at_point
                self.get_potential_at_point = self.code.get_potential_at_point
                self.get_hydro_state_at_point = self.code.get_hydro_state_at_point

                # Create a channel
                self.channel_to_gas = self.code.gas_particles.new_channel_to(self.gas_particles)
                self.channel_to_sinks = self.code.dm_particles.new_channel_to(self.sink_particles)
                
                # External Cooling
                print "Cooling flag:", self.cooling_flag
                self.cooling = SimplifiedThermalModelEvolver(self.code.gas_particles)
                #self.cooling = Cooling(self.code.gas_particles)
                self.cooling.model_time=self.code.model_time


        def print_diagnostics(self):
                print "Time=", self.code.model_time.in_(units.Myr)
                print "N=", len(self.gas_particles), len(self.sink_particles)

                if len(self.sink_particles)>0:
                    print "Sink masses:", len(self.code.dm_particles.mass)
                    print "Sink masses:", len(self.sink_particles)

        def write_set_to_file(self, index):
                filename = "hydro_molecular_cloud_collapse_i{0:04}.amuse".format(index)
                write_set_to_file(self.code.gas_particles, filename, "amuse", append_to_file=False)
                write_set_to_file(self.code.dm_particles, filename, "amuse")
        
        @property
        def model_time(self):
                return self.code.model_time
        
        @property
        def gas_particles(self):
                return self.code.gas_particles

        @property
        def stop(self):
                return self.code.stop
                
        def evolve_model(self, model_time):
            
            start_time = time.time()

            density_limit_detection = self.code.stopping_conditions.density_limit_detection
            density_limit_detection.enable()

            model_time_old=self.code.model_time
            dt=model_time - model_time_old
            print "Evolve Hydrodynamics:", dt.in_(units.yr)

            if COOL:
                print "Cool gas for dt=", (dt/2).in_(units.Myr)
                self.cooling.evolve_for(dt/2)
                #print "...done."
            self.code.evolve_model(model_time)
            #print "gas evolved."
            while density_limit_detection.is_set():
                self.resolve_sinks()

                print "..done"
                ##if len(self.sink_particles)>1: self.merge_sinks()
                self.code.evolve_model(model_time)
                self.channel_to_sinks.copy()
                print "end N=", len(self.sink_particles), len(self.code.dm_particles)

            if COOL:
                print "Cool gas for another dt=", (dt/2).in_(units.Myr)
                self.cooling.evolve_for(dt/2)
                #print "...done."
            #self.code.evolve_model(model_time)
            print "final N=", len(self.sink_particles),len(self.code.dm_particles)
            print "final Ngas=", len(self.gas_particles),len(self.code.gas_particles)
            self.channel_to_gas.copy()
            self.channel_to_sinks.copy()
            print "final N=", len(self.sink_particles),len(self.code.dm_particles)
            #~ print "Hydro arrived at:", self.code.model_time.in_(units.Myr)

            #print "Accrete from ambied gas"
            #self.accrete_sinks_from_ambiant_gas()

        def resolve_sinks(self):
            print "processing high dens particles...",
            highdens=self.gas_particles.select_array(lambda rho:rho>self.density_threshold,["rho"])
            print "N=", len(highdens)
            candidate_sinks=highdens.copy()
            self.gas_particles.remove_particles(highdens)
            self.gas_particles.synchronize_to(self.code.gas_particles)
            #self.gas_particles.synchronize_to(self.cooling.gas_particles)
            if len(self.sink_particles)>0:
                print "new sinks..."
                if len(candidate_sinks)>0: # had to make some changes to prevent double adding particles
                    print "Adding sinks, N=", len(candidate_sinks)
                    newsinks_in_code = self.code.dm_particles.add_particles(candidate_sinks)
                    newsinks = Particles()
                    for nsi in newsinks_in_code:
                        if nsi not in self.sink_particles:
                            newsinks.add_particle(nsi)
                        else:
                            print "this sink should not exicst"
                        newsinks.sink_radius=self.sink_particles.sink_radius.max()
                    print "pre N=", len(self.sink_particles), len(newsinks), len(self.code.dm_particles)
                    self.sink_particles.add_sinks(newsinks)
                    print "post N=", len(self.sink_particles), len(newsinks), len(self.code.dm_particles)
                    print "Why can I not prim the sinks=", self.sink_particles
                else:
                    print "N candidates:", len(candidate_sinks)
            else:
                print "Create new sinks: N=", len(candidate_sinks)
                if len(candidate_sinks)>0:
                    newsinks_in_code = self.code.dm_particles.add_particles(candidate_sinks)
                    sink_particles_tmp = newsinks_in_code.copy()
                    print "creating new sinks..."
                    self.sink_particles=SinkParticles(sink_particles_tmp, 
                                                      looping_over="sources")
#                    self.channel_to_sinks = self.code.dm_particles.new_channel_to(self.sink_particles)

                    
                    print "New sinks created: ", len(sink_particles_tmp)
                else:
                    print "No sinks created."
                            
        def accrete_sinks_from_ambiant_gas(self):
           if len(self.sink_particles)==0:
               return
           print "accrete_sinks_from_ambiant_gas"
           #print sinks.__class__
           print 'Sinks: Accrete from ambiant gas:', len(self.gas_particles), len(self.code.gas_particles)
           print 'Sinks:', len(self.sink_particles), len(self.code.dm_particles)
           print self.sink_particles.sink_radius.in_(units.AU)

#            if SPEED_UP_ACCRETION:
           highdens = self.gas_particles.select_array(lambda rho:rho>self.density_threshold,["rho"])
           candidate_sinks = highdens.copy()
           accreted_particles = self.sink_particles.accrete(candidate_sinks)
#            else:
#           accreted_particles = self.sink_particles.accrete(self.gas_particles)

           print 'Ambiant gas accreted:', len(accreted_particles), 'particles, dM=', accreted_particles.mass.sum().in_(units.MSun) 
           #print 'Ambiant gas accreted:', len(hydro.gas_particles)-len(gas), 'particles, dM=', (hydro.gas_particles.mass.sum()-gas.mass.sum()).in_(units.MSun) 
           self.gas_particles.synchronize_to(self.code.gas_particles)
           #self.sink_particles.synchronize_to(self.code.dm_particles)
            
            
        def merge_sinks(self):
            print "Let gravity take care of merging sinks" 
            if True:
               if self.merge_radius<=quantities.zero:
                   return
               print "identify groups.." 
               ccs=self.sink_particles.copy().connected_components(threshold=self.merge_radius)
               if len(ccs):
                   print "merging sink sets... "
               nmerge=0
               newsinks=Particles()
               for cc in ccs:
                   if len(cc) >1:
                       nmerge+=1
                   if len(cc) > 3: 
                       print "warning: large merge(than 3) ", len(cc)
                   cc=cc.copy()
                   self.sink_particles.remove_particles(cc)
                   self.sink_particles.synchronize_to(self.code.dm_particles)
                   new = self.merge_stars(cc)
                   newsinks.add_particle(new)
               if len(newsinks)>0:
                   #new_in_code = self.dm_particles.add_particles(newsinks)
                   #self.sink_particles.add_sinks(new_in_code,angular_momentum=newsinks.angular_momentum)
                   newsinks_in_code = newsinks
                   self.sink_particles.add_sinks(SinkParticles(newsinks_in_code,
                                                               looping_over="sources"))
                   self.sink_particles.synchronize_to(self.code.dm_particles)
                   
               if nmerge>0:
                   print "nmerg found: ",nmerge,
               print "...done"
