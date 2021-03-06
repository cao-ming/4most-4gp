# -*- coding: utf-8 -*-

"""
This python package provides a wrapper for functions provided by the 4MOST Facility Simulator, 4FS.
"""

import os
from os import path as os_path
import numpy as np
import astropy.io.fits as fits
import logging

from fourgp_speclib import Spectrum

from . import config_files

logger = logging.getLogger(__name__)


class FourFS:
    def __init__(self,
                 path_to_4fs="/home/dcf21/iwg7_pipeline/OpSys/ETC",
                 magnitude=14,
                 magnitude_unreddened=False,
                 photometric_band="SDSS_r",
                 snr_list=None,
                 snr_per_pixel=True,
                 snr_definitions=None,
                 run_lrs=True,
                 run_hrs=True,
                 lrs_use_snr_definitions=None,
                 hrs_use_snr_definitions=None,
                 identifier="x"
                 ):
        """
        Instantiate a class for calling 4FS.

        :param path_to_4fs:
            Path to where 4FS binaries can be found.

        :param magnitude:
            The magnitude to normalise this template spectrum to (only relevant for computing exposure times).

        :param photometric_band:
            The photometric band in which the magnitude of this template spectrum is quoted.

        :param magnitude_unreddened:
            Boolean flag, set to True if the magnitude above should be taken as the unreddened magnitude of the star.
            This settings requires metadata fields such as 'A_SDSS_r' to be set in each spectrum's metadata by the
            reddening script, so that we know how many magnitudes each photometric band has been reddened by.

        :param snr_list:
            List of the SNRs that we want 4FS to degrade input spectra to.

        :param snr_per_pixel:
            Boolean flag indicating whether SNRs are quoted per pixel or per Angstrom.

        :param snr_definitions:
            List of ways we define SNR. Each should take the form of a tuple (name,min,max), where we take the median
            SNR per pixel between the specified minimum and maximum wavelengths in Angstrom.

        :param run_lrs:
            Do we want output for 4MOST LRS?

        :param run_hrs:
            Do we want output for 4MOST HRS?

        :param lrs_use_snr_definitions:
            List of three SNR definitions to use for the red, green and blue bands of 4MOST LRS.

        :param hrs_use_snr_definitions:
            List of three SNR definitions to use for the red, green and blue bands of 4MOST HRS.

        :param identifier:
            A string identifier for this 4FS instance. This only matters if we have multiple 4FS instances running
            from a single process, and need to make sure they have separate working directories in </tmp>.
        """
        self.path_to_4fs = path_to_4fs
        self.run_lrs = run_lrs
        self.run_hrs = run_hrs
        self.magnitude = magnitude
        self.magnitude_unreddened = magnitude_unreddened
        self.photometric_band = photometric_band
        self.snr_per_pixel = snr_per_pixel
        self.reference_magnitude = 15.0  # Give all spectra to 4FS normalised to this reference mag in SDSS_r
        self.template_counter = 0
        self.metadata_store = {}

        # Read the list of SNRs that we have been requested to degrade spectra to
        if snr_list is None:
            # Default list
            snr_list = (10, 12, 14, 16, 18, 20, 23, 26, 30, 35, 40, 45, 50, 80, 100, 130, 180, 250)
        self.snr_list = snr_list

        # Read the list of SNR definitions supplied, or default to using a window between 6180 and 6680 A
        if snr_definitions is None:
            snr_definitions = [("MEDIANSNR", 6180, 6680)]

        if lrs_use_snr_definitions is None:
            lrs_use_snr_definitions = ("MEDIANSNR", "MEDIANSNR", "MEDIANSNR")

        if hrs_use_snr_definitions is None:
            hrs_use_snr_definitions = ("MEDIANSNR", "MEDIANSNR", "MEDIANSNR")

        self.lrs_use_snr_definitions = lrs_use_snr_definitions if run_lrs else []
        self.hrs_use_snr_definitions = hrs_use_snr_definitions if run_hrs else []

        if run_lrs:
            assert len(self.lrs_use_snr_definitions) == 3, "Need three SNR definitions, for 4MOST LRS RGB arms."
        if run_hrs:
            assert len(self.hrs_use_snr_definitions) == 3, "Need three SNR definitions, for 4MOST HRS RGB arms."

        self.distinct_snr_definitions = set([i for i in (list(self.lrs_use_snr_definitions) +
                                                         list(self.hrs_use_snr_definitions))
                                             if isinstance(i, str) and len(i) > 0])

        # Create temporary directory
        self.id_string = "4fs_{:d}_{}".format(os.getpid(), identifier)
        self.tmp_dir = os_path.join("/tmp", self.id_string)
        os.system("mkdir -p {}".format(self.tmp_dir))

        # Put standard 4FS configuration files into temporary working directory
        if run_hrs:
            with open(os_path.join(self.tmp_dir, "ETC_input_params_HRS.txt"), "w") as f:
                f.write(config_files.ETC_input_params_HRS)

        if run_lrs:
            with open(os_path.join(self.tmp_dir, "ETC_input_params_LRS.txt"), "w") as f:
                f.write(config_files.ETC_input_params_LRS)

        with open(os_path.join(self.tmp_dir, "rulelist.txt"), "w") as f:
            f.write(config_files.rulelist)
            for snr_definition in snr_definitions:
                f.write("{:<13s} SNR MEDIAN DIV   1.0  {:.1f} {:.1f} NM     1.0    {}\n".
                        format(snr_definition[0], snr_definition[1] / 10., snr_definition[2] / 10.,
                               "PIX" if self.snr_per_pixel else "AA"))

        with open(os_path.join(self.tmp_dir, "ruleset.txt"), "w") as f:
            f.write(config_files.ruleset(snr_list=self.snr_list, snr_definitions=self.distinct_snr_definitions))

        # Extract 4MOST telescope description files
        cwd = os.getcwd()
        os.chdir(self.tmp_dir)
        path_to_telescope_description = os_path.split(os_path.abspath(__file__))[0]
        os.system("tar xvfz {}".format(os_path.join(path_to_telescope_description,
                                                    "4FS_ETC_system_model_latest.tar.gz")))
        os.chdir(cwd)

    def close(self):
        # Remove temporary directory
        os.system("rm -Rf {}".format(self.tmp_dir))

    def make_fits_spectral_template(self,
                                    input_spectrum, input_spectrum_continuum_normalised,
                                    output_filename='test1.fits',
                                    resolution=50000,
                                    continuum_only=False
                                    ):
        """
        Generate a 4FS readable fits template from the Turbospectrum output.
        
        :param input_spectrum:
            Spectrum object that we want to pass through 4FS.
            
        :type input_spectrum:
            Spectrum
            
        :param input_spectrum_continuum_normalised:
            Continuum-normalised version of the Spectrum object that we want to pass through 4FS. This can be null,
            in which case we only produce a flux-normalised spectrum as output.
            
        :type input_spectrum_continuum_normalised:
            Spectrum
            
        :param output_filename:
            Output filename for FITS file we store in our temporary workspace.
            
        :type output_filename:
            str
            
        :param resolution:
            The spectral resolution of the input spectrum, stored in the FITS headers
            
        :type resolution:
            float
        
        :param continuum_only:
            Select whether to output full spectrum, including spectral lines, or just the continuum outline.
            
        :type continuum_only:
            bool
            
        :return:
            None
        """

        # Extract data from input spectra
        wavelength_raster = input_spectrum.wavelengths
        flux = input_spectrum.values

        if input_spectrum_continuum_normalised is not None:
            assert input_spectrum.raster_hash == input_spectrum_continuum_normalised.raster_hash, \
                "Continuum-normalised spectrum needs to have the same wavelength raster as the original."
            continuum_normalised_flux = input_spectrum_continuum_normalised.values

            if not continuum_only:
                data = flux
            else:
                # If we only want continuum, without lines, then divide by continuum_normalised flux
                data = flux / continuum_normalised_flux
        else:
            data = flux

        lambda_min = np.min(wavelength_raster)
        delta_lambda = wavelength_raster[1] - wavelength_raster[0]

        fits_spectrum = Spectrum(wavelengths=wavelength_raster,
                                 values=data,
                                 value_errors=np.zeros_like(wavelength_raster),
                                 metadata={})

        # Renormalise spectrum to a standard R-band magnitude
        magnitude = fits_spectrum.photometry(self.photometric_band)

        if self.magnitude_unreddened:
            magnitude -= input_spectrum.metadata["A_{}".format(self.photometric_band)]

        data *= pow(10, -0.4 * (self.reference_magnitude - magnitude))

        # Turn spectrum into a fits file
        hdu_1 = fits.PrimaryHDU(data)
        hdu_1.header['CRTYPE1'] = "LINEAR  "
        hdu_1.header['CRPIX1'] = 1.0
        hdu_1.header['CRVAL1'] = lambda_min
        hdu_1.header['CDELT1'] = delta_lambda
        hdu_1.header['CUNIT1'] = "Angstrom"
        hdu_1.header['BUNIT'] = "erg/s/cm2/Angstrom"
        hdu_1.header['ABMAG'] = self.reference_magnitude
        if resolution is not None:
            fwhm_res = np.mean(wavelength_raster / resolution)
            hdu_1.header['RESOLUTN'] = fwhm_res

        hdu_list = fits.HDUList([hdu_1])
        hdu_list.writeto(os_path.join(self.tmp_dir, output_filename))
        # np.savetxt(os_path.join(self.tmp_dir, output_filename+".txt"), np.asarray(data))

    def generate_4fs_template_list(self,
                                   spectra_list,
                                   resolution=50000
                                   ):
        """
        Generate 4FS template list from a list of 4GP Spectrum objects

        :param spectra_list:
            A list of the spectra we should pass through 4FS. Each entry in the list should be a list of tuple with
            two entries: (input_spectrum, input_spectrum_continuum_normalised). These reflect the contents of the
            third and second columns of Turbospectrum's ASCII output respectively.

        :type spectra_list:
            (list, tuple) of (list, tuple) of Spectrum objects

        :param resolution:
            The spectral resolution of the input spectrum, stored in the FITS headers

        :type resolution:
            float

        :return:
            The string contents of the template file we wrote for 4FS.
        """

        # Location to write template list to be used for 4FS
        template_list_filename = 'template_list_test.txt'

        # Start writing template list file
        writestr = """\
#OBJECTNAME           FILENAME                                                 RULESET SIZE REDSHIFT MAG  MAG_RANGE
"""

        # Loop over stars we are to process
        star_list = []
        template_number_first = self.template_counter
        for spectra in spectra_list:
            input_spectrum, input_spectrum_continuum_normalised = spectra
            obj_name = input_spectrum.metadata['Starname']
            logger.info("Working on <{}>".format(obj_name))

            # Keep a copy of the metadata on this object, which we put back into the output from 4FS
            self.metadata_store[self.template_counter] = input_spectrum.metadata.copy()

            # Generates the 4FS readable fits files from the output spectra from Turbospectrum
            self.make_fits_spectral_template(
                input_spectrum=input_spectrum,
                input_spectrum_continuum_normalised=input_spectrum_continuum_normalised,
                output_filename='template_{}.fits'.format(self.template_counter),
                resolution=(resolution is not None))

            # Generate a second 4FS-readable template with just the continuum, and no lines. This is used to recover
            # a continuum-normalised spectrum at the end of the process
            if input_spectrum_continuum_normalised is not None:
                self.make_fits_spectral_template(
                    input_spectrum=input_spectrum,
                    input_spectrum_continuum_normalised=input_spectrum_continuum_normalised,
                    output_filename='template_{}_c.fits'.format(self.template_counter),
                    resolution=(resolution is not None),
                    continuum_only=True)

            # Run 4FS using all SNR definitions and all SNR values on this spectrum
            for snr_definition in self.distinct_snr_definitions:
                for snr in self.snr_list:
                    writestr += 'template_{}_SNR{:.1f}_{} {} {} {} {} {} {}\n'.format(
                        self.template_counter,
                        snr, snr_definition,
                        os_path.join(self.tmp_dir, 'template_{}.fits'.format(self.template_counter)),
                        'goodSNR{0:.1f}_{1:s}'.format(snr, snr_definition),
                        '0.0', '0.0', self.reference_magnitude, self.magnitude)

            # Additionally, run 4FS on a continuum-only spectrum at a high SNR of 250
            if input_spectrum_continuum_normalised is not None:
                writestr += 'template_{}_c {} {} {} {} {} {}\n'.format(
                    self.template_counter,
                    os_path.join(self.tmp_dir, 'template_{}_c.fits'.format(self.template_counter)),
                    'goodSNR250c', '0.0', '0.0', self.reference_magnitude, self.magnitude)

            # Populate star_list with the list of FITS files we're expecting 4FS to produce
            for snr in self.snr_list:
                star_list.append('template_{}_SNR{:.1f}'.format(self.template_counter, snr))

            if input_spectrum_continuum_normalised is not None:
                star_list.append('template_{}_c'.format(self.template_counter))

            # Increment template counter
            self.template_counter += 1

        # Write template list to file
        with open(os_path.join(self.tmp_dir, template_list_filename), 'w') as f:
            f.write(writestr)

        # Return the string contents of the template list
        template_number_last = self.template_counter - 1

        return {'template_file': writestr,
                'template_numbers': list(range(template_number_first, template_number_last + 1))
                }

    def combine_spectra(self,
                        template_numbers,
                        path='outdir_LRS/',
                        setup='LRS'
                        ):
        """
        4FS produces three output fits files for both 4MOST's LRS and HRS modes. These contain the three spectra
        arms. However, the Cannon expects all its data in a single unified spectrum. This function stitches the
        three arms into a single data set.

        Combine the multiple fits files from the 4FS into a single ascii file with all arms included.

        NOTE: The point at which one are is favoured over another in the stitching
              process is hardcoded should be changed in future versions.

        :param template_numbers:
            Each spectrum is allocated an ID number by the function `generate_4FS_template_list` above when it is
            prepared for input into 4FS. These ID numbers are also present in the output filenames of the observed
            spectra that 4FS produces. This parameter is a list of the IDs of the spectra we are to post-process.

        :type template_numbers:
            List or tuple of ints

        :param path:
            Set the path to the 4FS output FITS files we are to post-process. This path is relative to `self.tmp_dir`.

        :type path:
            str

        :param setup:
            Set to either (1) 'LRS' - low res or (2) 'HRS' - high res. Specifies the mode in which 4MOST is working.

        :type setup:
            str

        :return :
            A list of 4GP Spectrum objects.
        """

        bands = ("blue", "green", "red")

        if setup == "LRS":
            snr_definitions = self.lrs_use_snr_definitions
        else:
            snr_definitions = self.hrs_use_snr_definitions

        # SNR definitions are red, green, blue. But we index the bands (blue, green, red).
        snr_definitions = snr_definitions[::-1]

        # Extract exposure times from 4FS summary file
        exposure_times = {}
        with open(os_path.join(path, '4FS_ETC_summary.txt')) as f:
            for line in f:
                words = line.split()
                if len(words) < 6:
                    continue

                # First column of data file lists the run number
                try:
                    run_counter = int(words[0])
                except ValueError:
                    continue
                # Sixth column is exposure time in seconds
                if words[5] == "nan":
                    t_exposure = np.nan
                else:
                    t_exposure = float(words[5])
                exposure_times[str(run_counter)] = t_exposure

        # Start extracting spectra from FITS files
        output = {}
        run_counter = 0
        for i in template_numbers:
            output[i] = {}
            for snr in self.snr_list:
                run_counter += 1

                # Load in the three output spectra -- blue, green, red arms
                d = []
                for j, band in enumerate(bands):
                    snr_definition = snr_definitions[j]
                    if (snr_definition is not None) and (len(snr_definition) > 0):
                        fits_data = fits.open(os_path.join(path, 'specout_template_template_{}_SNR{:.1f}_{}_{}_{}.fits'.
                                                           format(i, snr, snr_definitions[j], setup, band)))
                        data = fits_data[2].data
                    else:
                        data = {
                            'LAMBDA': np.zeros(0),
                            'REALISATION': np.zeros(0),
                            'FLUENCE': np.zeros(0),
                            'SKY': np.zeros(0),
                            'SNR': np.zeros(0)
                        }
                    d.append(data)

                # Read the data from the FITS files
                wavelengths = [item['LAMBDA'] for item in d]
                fluxes = [(item['REALISATION'] - item['SKY']) for item in d]
                fluences = [item['FLUENCE'] for item in d]
                snrs = [item['SNR'] for item in d]

                # In 4MOST LRS mode, the wavelengths bands overlap, so we cut off the ends of the bands
                # Stitch arms based on where SNR is best -- hardcoded here may need changed in future versions
                if setup == 'LRS':
                    indices = (
                        np.where(wavelengths[0] <= 5327.7)[0],
                        np.where((wavelengths[1] > 5327.7) & (wavelengths[1] <= 7031.7))[0],
                        np.where(wavelengths[2] > 7031.7)[0]
                    )
                    wavelengths = [item[indices[j]] for j, item in enumerate(wavelengths)]
                    fluxes = [item[indices[j]] for j, item in enumerate(fluxes)]
                    fluences = [item[indices[j]] for j, item in enumerate(fluences)]
                    snrs = [item[indices[j]] for j, item in enumerate(snrs)]

                # Append the three arms of 4MOST together into a single spectrum
                wavelengths_final = np.concatenate(wavelengths)
                fluxes_final = np.concatenate(fluxes)
                # fluences_final = np.concatenate(fluences)
                snrs_final = np.concatenate(snrs)

                # Load continuum spectra
                continuum_filenames = [os_path.join(path, 'specout_template_template_{}_c_{}_{}.fits'.
                                                    format(i, setup, band)) for band in bands]
                have_continuum_version = os.path.exists(continuum_filenames[0])

                if have_continuum_version:
                    d_c = [fits.open(item)[2].data for item in continuum_filenames]

                    # Read the data from the FITS files
                    wavelengths_c = [item['LAMBDA'] for item in d_c]
                    # fluxes_c = [(item['REALISATION'] - item['SKY']) for item in d_c]
                    fluences_c = [item['FLUENCE'] for item in d_c]

                    if setup == 'LRS':
                        indices = (
                            np.where(wavelengths_c[0] <= 5327.7)[0],
                            np.where((wavelengths_c[1] > 5327.7) & (wavelengths_c[1] <= 7031.7))[0],
                            np.where(wavelengths_c[2] > 7031.7)[0]
                        )
                        # wavelengths_c = [item[indices[j]] for j, item in enumerate(wavelengths_c)]
                        # fluxes_c = [item[indices[j]] for j, item in enumerate(fluxes_c)]
                        fluences_c = [item[indices[j]] for j, item in enumerate(fluences_c)]

                    # Combine everything into one set of arrays to be saved
                    # wavelengths_final_c = np.concatenate(wavelengths_c)

                    fluxes_final_c = np.concatenate([fluence_c * max(fluence) / max(fluence_c)
                                                     for fluence, fluence_c in zip(fluences, fluences_c)
                                                     if len(fluence) > 0])

                    # Do continuum normalisation
                    normalised_fluxes_final = fluxes_final / fluxes_final_c

                    # Remove bad pixels
                    # Any pixels where flux > 2 or flux < 0 get reset to zero for other downstream codes
                    normalised_fluxes_final[
                        np.where((normalised_fluxes_final > 2.0) | (normalised_fluxes_final <= 0.00))[0]] = 0

                # Turn data into a 4GP Spectrum object
                metadata = self.metadata_store[i]

                # Add metadata about 4FS settings
                metadata['continuum_normalised'] = 0
                metadata['SNR'] = float(snr)
                metadata['SNR_per'] = "pixel" if self.snr_per_pixel else "A"
                metadata['magnitude'] = float(self.magnitude)
                metadata['exposure'] = exposure_times.get(str(run_counter), np.nan)

                if (snr_definitions[0] == snr_definitions[1]) and (snr_definitions[1] == snr_definitions[2]):
                    metadata['snr_definition'] = snr_definitions[0]
                else:
                    metadata['snr_definition'] = ",".join(snr_definitions)

                # Insert spectrum into library
                spectrum = Spectrum(wavelengths=wavelengths_final,
                                    values=fluxes_final,
                                    value_errors=fluxes_final / snrs_final,
                                    metadata=metadata.copy())

                if have_continuum_version:
                    metadata['continuum_normalised'] = 1
                    spectrum_continuum_normalised = Spectrum(wavelengths=wavelengths_final,
                                                             values=normalised_fluxes_final,
                                                             value_errors=normalised_fluxes_final / snrs_final,
                                                             metadata=metadata.copy())
                else:
                    spectrum_continuum_normalised = None

                output[i][snr] = {
                    "spectrum": spectrum,
                    "spectrum_continuum_normalised": spectrum_continuum_normalised
                }

        return output

    def process_spectra(self, spectra_list, resolution=50000):
        # Generate input configuration files for 4FS
        template_information = self.generate_4fs_template_list(spectra_list=spectra_list,
                                                               resolution=resolution)

        # Find the 4FS binary
        fourfs_command = os_path.join(self.path_to_4fs, "4FS_ETC")
        assert os_path.exists(fourfs_command), "Could not find 4FS binary!"

        # Switching into our temporary working directory where 4FS can find all its input files
        cwd = os.getcwd()
        os.chdir(self.tmp_dir)

        # Make sure there aren't any old 4FS outputs lying around
        os.system("rm -Rf outdir_LRS outdir_HRS")

        # Run 4FS
        if self.run_lrs:
            os.system("{} PARAM_FILENAME=ETC_input_params_LRS.txt > lrs_output.log 2>&1".format(fourfs_command))
        if self.run_hrs:
            os.system("{} PARAM_FILENAME=ETC_input_params_HRS.txt > hrs_output.log 2>&1".format(fourfs_command))

        # Stitched 4MOST wavebands together
        output = {}
        for mode, active in (("LRS", self.run_lrs), ("HRS", self.run_hrs)):
            if active:
                stitched_spectra = self.combine_spectra(template_numbers=template_information['template_numbers'],
                                                        path="outdir_{}".format(mode),
                                                        setup=mode
                                                        )
                output[mode] = stitched_spectra

        # Make sure there aren't any old FITS files lying around
        os.system("rm -Rf template*.fits")

        # Switch back into the user's cwd
        os.chdir(cwd)

        # Return output spectra to user
        return output
