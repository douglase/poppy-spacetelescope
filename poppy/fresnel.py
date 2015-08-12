from __future__ import division

import poppy
import numpy as np
import matplotlib.pyplot as plt

import astropy.io.fits as fits
import astropy.units as u

from . import utils

import logging
_log = logging.getLogger('poppy')

try:
    from IPython.core.debugger import Tracer; stop = Tracer()
except:
    pass

from poppy.poppy_core import _PUPIL, _IMAGE, _DETECTOR, _ROTATION, _INTERMED, _FFTW_AVAILABLE



class QuadPhase(poppy.AnalyticOpticalElement):
    '''
    Quadratic phase factor,  q(z)
    suitable for representing a radially-dependent wavefront curvature.

    Parameters
    -----------------
    z : float or astropy.Quantity of type length
        radius of curvature
    planetype : poppy.PlaneType constant
        plane type
    name : string
        Descriptive string name
    reference_wavelength : float
        wavelength
    units : astropy.unit of type length
        Unit to apply to reference wavelength; default is meter


    References
    -------------------
    Lawrence eq. 88

    '''
    def __init__(self,
                 z,
                 planetype = _INTERMED,
                 name = 'Quadratic Wavefront Curvature Operator',
                 reference_wavelength = 2e-6,
                 units=u.m,
                 **kwargs):
        poppy.AnalyticOpticalElement.__init__(self,name=name, planetype=planetype, **kwargs)
        self.z=z
        self.reference_wavelength = reference_wavelength*units

        if  isinstance(z,u.quantity.Quantity):
            self.z_m = (z).to(u.m) #convert to meters.
        else:
            _log.debug("Assuming meters, phase (%.3g) has no units for Optic: "%(z)+self.name)
            self.z_m=z*u.m

    def getPhasor(self, wave):
        """ return complex phasor for the quadratic phase

        Parameters
        ----------
        wave : obj
            a Fresnel Wavefront object
        """

        y, x = wave.coordinates()
        rsqd = (x**2+y**2)*u.m**2
        _log.debug("Applying spherical phase curvature ={0:0.2e}".format(self.z_m))
        _log.debug("Applying spherical lens phase ={0:0.2e}".format(1.0/self.z_m))
        _log.debug("max_rsqd ={0:0.2e}".format(np.max(rsqd)))


        k = 2* np.pi/self.reference_wavelength
        lens_phasor = np.exp(1.j * k * rsqd/(2.0*self.z_m))
        return lens_phasor


class GaussianLens(QuadPhase):
    '''
    Gaussian Lens

    Thin wrapper for QuadPhase

    Parameters
    -----------------
    f_lens : float or astropy.Quantity of type length
        Focal length of this lens
    name : string
        Descriptive string name
    planetype : poppy.PlaneType constant
        plane type
    reference_wavelength : float
        wavelength
    units : astropy.unit of type length
        Unit to apply to reference_wavelength; defaults to meters


    '''
    def __init__(self,
                 f_lens,
                 planetype = _INTERMED,
                 name = 'Gaussian Lens',
                 reference_wavelength = 2e-6,
                 units=u.m,
                 oversample=2,
                 **kwargs):
        QuadPhase.__init__(self,
                 f_lens,
                 planetype =planetype,
                 name = name,
                 reference_wavelength = reference_wavelength,
                 units=units,
                 oversample=oversample,
                 **kwargs)
        if  isinstance(f_lens,u.quantity.Quantity):
            self.fl = (f_lens).to(u.m) #convert to meters.
        else:
            _log.warn("Assuming meters, focal length (%.3g) has no units for Optic: "%(f_lens)+self.name)
            self.fl=f_lens*u.m
        _log.debug("Initialized: "+self.name+", fl ={0:0.2e}".format(self.fl))


class Wavefront(poppy.Wavefront):
    @u.quantity_input(beam_radius=u.m)
    def __init__(self,
                 beam_radius,
                 units=u.m,
                 force_fresnel=True,
                 rayl_factor=2.0,
                 oversample=2,
                 **kwds):
        '''
        Wavefront for Fresnel diffraction calculation.

        This class inherits from and extends the Fraunhofer-domain
        poppy.Wavefront class.


        Parameters:
        --------------------
        beam_radius :
            Radius of the illuminated beam at the initial optical plane.
            I.e. this would be the pupil aperture radius in an entrance pupil.
        units :
            astropy units of input parameters
        rayl_factor:
            Threshold for considering a wave spherical.
        force_fresnel : bool
            If True then the Fresnel propagation will always be used,
            even between planes of type _PUPIL or _IMAGE
            if False the wavefront reverts to standard wavefront propagation for _PUPIL <-> _IMAGE planes
        oversample : float
            Padding factor to apply to the wavefront array, multiplying on top of the beam radius.


        References:
        -------------------
        - Lawrence, G. N. (1992), Optical Modeling, in Applied Optics and Optical Engineering., vol. XI,
            edited by R. R. Shannon and J. C. Wyant., Academic Press, New York.

        - https://en.wikipedia.org/wiki/Gaussian_beam

        - IDEX Optics and Photonics(n.d.), Gaussian Beam Optics,
            [online] Available from:
             https://marketplace.idexop.com/store/SupportDocuments/All_About_Gaussian_Beam_OpticsWEB.pdf

        - Krist, J. E. (2007), PROPER: an optical propagation library for IDL,
           vol. 6675, p. 66750P-66750P-9.
        [online] Available from: http://dx.doi.org/10.1117/12.731179

        - Andersen, T., and A. Enmark (2011), Integrated Modeling of Telescopes, Springer Science & Business Media.

        '''

        #        initialize general wavefront class first,
        #        in Python 3 this will change,
        #        https://stackoverflow.com/questions/576169/understanding-python-super-with-init-methods

        self.units = units
        """Astropy.units for measuring distance"""

        self.w_0 = (beam_radius).to( self.units) #convert to base units.
        """Beam waist radius at initial plane"""
        self.oversample=oversample
        """Oversampling factor for zero-padding arrays"""
        #print(oversample)
        super(Wavefront,self).__init__(diam=beam_radius.to(u.m).value*2.0, oversample=self.oversample,**kwds)

        self.z  =  0*units
        """Current wavefront coordinate along the optical axis"""
        self.z_w0 = 0*units
        """Coordinate along the optical axis of the latest beam waist"""
        self.waists_w0 = [self.w_0.value]
        """ List of beam waist radii, in series as encountered during the course of an optical propagation."""
        self.waists_z = [self.z_w0.value]
        """ List of beam waist distances along the optical axis, in series as encountered during the course of an optical propagation."""
        self.wavelen_m = self.wavelength*u.m #wavelengths should always be in meters
        """ Wavelength as an Astropy.Quantity"""
        self.spherical = False
        """is this wavefront spherical or planar?"""
        self.k = np.pi*2.0/self.wavelength
        """ Wavenumber"""
        self.force_fresnel = force_fresnel
        """Force Fresnel calculation if true, even for cases wher Fraunhofer would work"""
        self.rayl_factor= rayl_factor

        if self.oversample > 1 and not self.ispadded: #add padding for oversampling, if necessary
            self.wavefront = utils.padToOversample(self.wavefront, self.oversample)
            self.ispadded = True
            _log.debug("Padded WF array for oversampling by %dx" % self.oversample)

            self.history.append("    Padded WF array for oversampling by %dx" % self.oversample)
        else:
            _log.debug("Skipping oversampling, oversample < 1 or already padded ")

        if self.oversample < 2:
            _log.warn("Oversampling > 2x suggested for reliable results.")

        # FIXME MP: this self.n attribute appears unnecessary?
        if self.shape[0]==self.shape[1]:
            self.n=self.shape[0]
        else:
            self.n=self.shape

        if self.planetype == _IMAGE:
            raise ValueError("Input wavefront needs to be a pupil plane in units of m/pix. Specify a diameter not a pixelscale.")

    @property
    def z_R(self):
        '''
        Rayleigh distance for the gaussian beam, based on
        current beam waist and wavelength.

        I.e. the distance along the propagation direction from the
        beam waist at which the area of the cross section has doubled.
        The depth of focus is conventionally twice this distance.
        '''

        return np.pi*self.w_0**2/(self.wavelen_m)

    @property
    def divergence(self):
        '''
        Divergence of the gaussian beam

        I.e. the angle between the optical axis and the beam radius at a large distance.
        Angle in radians.
        '''
        return 2*self.wavelen_m/(np.pi*self.w_0)

    @property
    def param_str(self):
        '''
        Formatted string of gaussian beam parameters.
        '''
        string= "w_0:{0:0.3e},".format(self.w_0)+" z_w0={0:0.3e}".format(self.z_w0) +"\n"+\
         "z={0:0.3e},".format(self.z)+" z_R={0:0.3e}".format(self.z_R)
        return string
    @property
    def waists(self):
        '''
        each [z_w_0,w_0] for each waist generated by an optic
        '''
        return np.array([self.waists_z,self.waists_w0])

    def fft(self):
        '''
        Apply normalized forward 2D Fast Fourier Transform to wavefront
        '''
        _USE_FFTW = (poppy.conf.use_fftw and _FFTW_AVAILABLE)
        forward_FFT= pyfftw.interfaces.numpy_fft.fft2 if _USE_FFTW else np.fft.fft2

        if _USE_FFTW:
            #FFTW wisdom could be implemented here.
            _log.debug("Using pyfftw")
            self.wavefront=forward_FFT(self.wavefront, overwrite_input=True,
                                     planner_effort='FFTW_MEASURE',
                                     threads=poppy.conf.n_processes)/self.shape[0]
        else:
            _log.debug("Using numpy FFT")
            self.wavefront=forward_FFT(self.wavefront)/self.shape[0]

    def inv_fft(self):
        '''
        Apply normalized Inverse 2D Fast Fourier Transform to wavefront
        '''
        _USE_FFTW = (poppy.conf.use_fftw and _FFTW_AVAILABLE)
        inverse_FFT= pyfftw.interfaces.numpy_fft.ifft2 if _USE_FFTW else np.fft.ifft2

        if _USE_FFTW:
            #FFTW wisdom could be implemented here.
            self.wavefront=inverse_FFT(self.wavefront, overwrite_input=True,
                                     planner_effort='FFTW_MEASURE',
                                     threads=poppy.conf.n_processes)*self.shape[0]
        else:
            _log.debug("Using numpy FFT")
            self.wavefront=inverse_FFT(self.wavefront)*self.shape[0]

    def R_c(self,z):
        '''
        The gaussian beam radius of curvature as a function of distance z
        '''
        dz=(z-self.z_w0) #z relative to waist
        if dz==0:
            return np.inf
        return dz*(1+(self.z_R/dz)**2)

    def spot_radius(self,z):
        '''
        radius of a propagating gaussian wavefront, at a distance z

        Parameters
        -------------
        z : float
            Distance from the current optical plane
        '''
        return self.w_0 * np.sqrt(1.0 + ((z-self.z_w0)/self.z_R)**2 )

    def fft_coords(self):
        """
        Return Y, X coordinates for this wavefront, in the manner of numpy.indices()

        This function returns the FFT center of the array always. Replaces poppy.wavefront.coordinates().

        Returns
        -------
        Y, X :  array_like
            Wavefront coordinates in either meters or arcseconds for pupil and image, respectively

        """
        y, x = np.indices(self.shape, dtype=float)
        y-= (self.shape[0])/2.
        x-= (self.shape[1])/2.

        xscale=self.pixelscale
        yscale=self.pixelscale

        #x *= xscale
        #y *= yscale
        return y*yscale, x*xscale

    def propagate_direct(self,z):
        '''
        Implements the direct propagation algorithm described in Andersen & Enmark (2011). Works best for far field propagation.
        Not part of the Gaussian beam propagation method.

        Parameters
        ----------
        z :  float
            the distance from the current location to propagate the beam.
        '''

        if  isinstance(z,u.quantity.Quantity):
            z_direct = (z).to(u.m).value #convert to meters.
        else:
            _log.warn("z= {0:0.2e}, has no units, assuming meters ".format(z))
            z_direct=z
        x,y=self.fft_coords()#*self.units
        k=np.pi*2.0/self.wavelen_m.value
        S=self.n*self.pixelscale
        _log.debug("Propagation Parameters: k={0:0.2e},".format(k)+"S={0:0.2e},".format(S)+"z={0:0.2e},".format(z_direct))

        QuadPhase_1st= np.exp(1.0j*k*(x**2+y**2)/(2*z_direct))#eq. 6.68
        QuadPhase_2nd= np.exp(1.0j*k*z_direct)/(1.0j*self.wavelength*z_direct)*np.exp(1.0j*(x**2+y**2)/(2*z_direct))#eq. 6.70

        stage1=self.wavefront*QuadPhase_1st #eq.6.67

        result= np.fft.fftshift(forward_FFT(stage1))*self.pixelscale**2*QuadPhase_2nd  #eq.6.69 and #6.80

        result=np.fft.fftshift(result)

        self.wavefront=result
        self.history.append("Direct propagation to z= {0:0.2e}".format(z))

        return

    def ptp(self,dz):
        ''' Plane-to-Plane Fresnel propagation.

        This function propagates a planar wavefront some distance
        while keeping it planar, yielding a planar output wavefront.
        This is used for propagation entirely within the Rayleigh
        distance of the beam waist.


        Parameters
        ----------
        dz :  float
            the distance from the current location to propagate the beam.

        References
        ----------
        Lawrence eq. 82, 86,87
        '''

        # FIXME MP: should check here to confirm the starting wavefront
        # is indeed planar rather than spherical

        if  isinstance(dz,u.quantity.Quantity):
            z_direct = (dz).to(u.m).value #convert to meters.
        else:
            _log.warn("z= {0:0.2e}, has no units, assuming meters ".format(dz))
            z_direct = dz

        if np.abs(dz) < 1*u.Angstrom:
            _log.debug("Skipping small dz = " + str(dz))
            return

        x,y = self.fft_coords() #meters
        rho = np.fft.fftshift((x/self.pixelscale/2.0/self.oversample)**2 + (y/self.pixelscale/2.0/self.oversample)**2)
        T=-1.0j*np.pi*self.wavelength*(z_direct)*rho #Transfer Function of diffraction propagation eq. 22, eq. 87

        self.fft()

        self.wavefront = self.wavefront*np.exp(T)#eq. 6.68

        self.inv_fft()
        self.z = self.z + dz

        self.history.append("Propagated Plane-to-Plane, dz = " + str(z_direct))

    def wts(self,dz):
        ''' Waist-to-Spherical Fresnel propagation

        This function propagates a planar input wavefront to become a spherical wavefront.
        The starting position should be within the Rayleigh distance of the waist, and the
        ending position will be outside of that. 

        Parameters:
        -----------
        dz :  float
            the distance from the current location to propagate the beam.

        References
        ----------
         Lawrence eq. 83,88
        '''
        #dz = z2-self.z
        _log.debug("Waist to Spherical propagation, dz=" + str(dz))

        # FIXME MP: check for planar input wavefront
        if dz ==0:
            _log.error("Waist to Spherical propagation stopped, no change in distance.")
            return

        self *= QuadPhase(dz, reference_wavelength=self.wavelength)

        if dz > 0:
            self.fft()
        else:
            self.inv_fft()


        self.pixelscale = self.wavelength*np.abs(dz.value)/(self.n*self.pixelscale)
        self.z = self.z + dz
        self.history.append("Propagated Waist to Spherical, dz = " + str(dz))

        # FIXME MP: update self.spherical to be true here?

    def stw(self,dz):
        '''Spherical-to-Waist Fresnel propagation

        This function propagates a spherical wavefront to become a planar wavefront.
        The starting position should be outside the Rayleigh distance of the waist,
        and the ending position will be inside of it. 


        Parameters
        ----------
        dz :  float
            the distance from the current location to propagate the beam.

        References
        ----------
         Lawrence eq. 89
        '''

        # FIXME MP: check for spherical input wavefront
        #dz = z2 - self.z
        _log.debug("Spherical to Waist propagation,dz="+str(dz))

        if dz ==0:
            _log.error("Spherical to Waist propagation stopped, no change in distance.")
            return

        if dz > 0:
            self.fft()
        else:
            self.inv_fft()

        #update to new pixel scale before applying curvature
        self.pixelscale = self.wavelength*np.abs(dz.value)/(self.n*self.pixelscale)
        self *= QuadPhase(dz, reference_wavelength=self.wavelength)
        self.z = self.z + dz
        self.history.append("Propagated Spherical to Waist, dz = " + str(dz))
        #

    def planar_range(self,z):
        '''
        Returns True if the input range z is within the Rayleigh range of the waist.

        Parameters:
        ----------
        z : float
            distance from the beam waist

        '''

        #if np.abs(self.z_w0 - z) < self.z_R:
        #    return True
        #else:
        #    return False
        return np.abs(self.z_w0 - z) < self.z_R

    def propagate_fresnel(self,delta_z,display_intermed=False):
        '''Top-level routine for Fresnel diffraction propagation


        Each spherical wavefront is propagated to a waist and then to the next appropriate plane
         (spherical or planar).

        Parameters
        ----------
        delta_z :  float
            the distance from the current location to propagate the beam.
        display_interm : boolean
             If True, display the complex start, intermediates waist and end surfaces.


        '''
        #self.pad_wavefront()
        z = self.z + delta_z
        if display_intermed:
            plt.figure()
            self.display('both',colorbar=True,title="Starting Surface")

        self.wavefront=np.fft.fftshift(self.wavefront)
        _log.debug("Beginning Fresnel Prop. Waist at z = "+str(self.z_w0))

        if not self.spherical:
            if self.planar_range(z):
                # Plane waves inside planar range:  use plane-to-plane
                _log.debug('Plane to Plane Regime, dz='+str(delta_z))
                _log.debug('Constant Pixelscale: %.2g'%self.pixelscale)
                self.ptp(delta_z)
            else:
                # Plane wave to spherical. First use PTP to the waist, then WTS to Spherical
                _log.debug('Plane to Spherical, inside Z_R to outside Z_R')
                self.ptp(self.z_w0 - self.z)
                if display_intermed:
                    plt.figure()
                    self.display('both',colorbar=True)
                self.wts(z-self.z_w0)
        else:
            if self.planar_range(z):
                # Spherical to plane. First use STW to the waist, then PTP to the desired plane
                _log.debug('Spherical to Plane Regime, outside Z_R to inside Z_R')
                self.stw(self.z_w0 - self.z)
                if display_intermed:
                    plt.figure()
                    self.display('both',colorbar=True,title='Intermediate Waist')
                self.ptp(z-self.z_w0)
            else:
                #Spherical to Spherical. First STW to the waist, then WTS to the desired spherical surface
                _log.debug('Spherical to Spherical, Outside Z_R to waist (z_w0) to outside Z_R')
                _log.debug('Starting Pixelscale: %.2g'%self.pixelscale)
                self.stw(self.z_w0 - self.z)
                _log.debug('Intermediate Pixelscale: %.2g'%self.pixelscale)
                self.pixelscale
                if display_intermed:
                    plt.figure()
                    self.display('both',colorbar=True,title='Intermediate Waist')
                self.wts(z-self.z_w0)
        if display_intermed:
            plt.figure()
            self.display('both',colorbar=True)

        self.wavefront = np.fft.fftshift(self.wavefront)
        self.planetype = _INTERMED
        _log.debug("------ Propagated to plane of type "+str(self.planetype)+" at z = {0:0.2e} ------".format(z))

    def apply_optic(self,optic,z_lens,ignore_wavefront=False):
        '''

        Adds thin lens wavefront curvature to the wavefront
        of focal length f_l and updates the
        Gaussian beam parameters of the wavefront.

        Eventually this should be called by a modified multiply function.

        Parameters
        ----------
        optic : GaussianLens
            An optic
        z_lens : float
            location of lens relative to the wavefront
        ignore_wavefront : boolean
            If True then only gaussian beam propagation parameters will be updated and the wavefront surface will not be calculated.
            Useful for quick calculations of gaussian laser beams

        '''

        #test optic and wavefront have equal oversampling
        assert self.oversample == optic.oversample
        #self.pad_wavefront()
        _log.debug("Pre-Lens Parameters:"+self.param_str)

        zl = (z_lens).to(u.m) #convert to meters.
        new_waist = self.spot_radius(zl)
        _log.debug("Beam radius at"+ str(optic.name)+" ={0:0.2e}".format(new_waist))
        #is the last surface outside the rayleigh distance?
        if np.abs(self.z_w0 - self.z) > self.rayl_factor*self.z_R:
            _log.debug("spherical")
            _log.debug(self.param_str)
            self.spherical = True
            R_input_beam = self.z - self.z_w0
        else:
            R_input_beam = np.inf

        if self.planetype == _PUPIL or self.planetype == _IMAGE:
            #we are at a focus or pupil, so the new optic is the only curvature of the beam
            r_curve = -optic.fl
            _log.debug(" input flat wavefront and "+ str(optic.name) +" has a curvature of ={0:0.2e}".format(r_curve))

        else:
            r_curve = 1.0/(1.0/self.R_c(zl) - 1.0/optic.fl)
            _log.debug(" input curved wavefront "+str(optic.name) +" has a curvature of ={0:0.2e}".format(r_curve))

        #update the wavefront to the post-lens beam waist
        if self.R_c(zl) == optic.fl:
            _log.debug(str(optic.name) +" has a flat output wavefront")
            self.z_w0 = zl
            self.w_0 = new_waist
        else:
            self.z_w0 = -r_curve/(1.0 + (self.wavelen_m*r_curve/(np.pi*new_waist**2))**2) + zl
            self.w_0 = new_waist/np.sqrt(1.0+(np.pi*new_waist**2/(self.wavelen_m*r_curve))**2)
            _log.debug(str(optic.name) +" has a curvature of ={0:0.2e}".format(r_curve))

        _log.debug("Post Optic Parameters:"+self.param_str)

        #check that this Fresnel business is necessary.
        if (not self.force_fresnel) and (self.planetype == _PUPIL or self.planetype ==_IMAGE) \
            and (optic.planetype ==_IMAGE or optic.planetype ==_PUPIL):
            _log.debug("Simple pupil / image propagation, Fresnel unnecessary. \
                       Reverting to Fraunhofer.")
            self.propagateTo(optic)
            return

        if ignore_wavefront:
            return

        if (not self.spherical) and (np.abs(self.z_w0 - zl) < self.z_R):
            _log.debug('Near-field, Plane-to-Plane Propagation.')
            z_eff = optic.fl

        elif (not self.spherical) and (np.abs(self.z_w0 - zl) > self.z_R):
            # find the radius of curvature of the lens output beam
            # curvatures are multiplicative exponentials
            # e^(1/z) = e^(1/x)*e^(1/y) = e^(1/x+1/y) -> 1/z = 1/x + 1/y
            # z = 1/(1/x+1/y) = xy/x+y
            z_eff = 1.0/( 1.0/optic.fl+ 1.0/(self.z-self.z_w0))
            _log.debug('Inside Rayleigh distance to Outside Rayleigh distance.')

            self.spherical = True


            #optic needs new focal length:
        elif (self.spherical) and (np.abs(self.z_w0 - zl) > self.z_R):
            _log.debug('Spherical to Spherical wavefront propagation.')
            _log.debug("1/fl={0:0.4e}".format(1.0/optic.fl))
            _log.debug("1.0/(R_input_beam)={0:0.4e}".format(1.0/R_input_beam))
            _log.debug("1.0/(self.z-self.z_w0)={0:0.4e}".format(1.0/(self.z-self.z_w0)))

            if R_input_beam == 0:
                z_eff = 1.0/( 1.0/optic.fl- 1.0/(R_input_beam))
            if (zl-self.z_w0) ==0:
                z_eff = 1.0/( 1.0/optic.fl+ 1.0/(self.z-self.z_w0))
            else:
                z_eff = 1.0/( 1.0/optic.fl+ 1.0/(self.z-self.z_w0)- 1.0/(R_input_beam))


        elif (self.spherical) and (np.abs(self.z_w0 - zl) < self.z_R):
            _log.debug('Spherical to Planar.')
            z_eff=1.0/( 1.0/optic.fl - 1.0/(R_input_beam) )
            self.spherical=False

        effective_optic = QuadPhase(-z_eff, reference_wavelength=self.wavelength)
        self *= effective_optic

        self.waists_z.append(self.z_w0.value)
        self.waists_w0.append(self.w_0.value)

        #update wavefront location:
        #self.z = zl
        self.planetype = optic.planetype
        _log.debug("------ Optic: "+str(optic.name)+" applied ------")
