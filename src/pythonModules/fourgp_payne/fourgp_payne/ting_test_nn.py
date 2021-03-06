# -*- coding: utf-8 -*-

import os
import logging
from multiprocessing import Pool

import numpy as np
from scipy.optimize import curve_fit
import scipy.optimize as op


# -----------------------------------------------------------------------
# define sigmoid function
def sigmoid_def(z):
    return 1.0 / (1.0 + np.exp(-z))


# ---------------------------------------------------------------------------
# define function to perform testing step in batch
def fit_spectrum(params):
    spec_no, num_labels, Y_u_all, Y_u_all_err, censor_mask, x_min, x_max, w_array_0, w_array_1, w_array_2, b_array_0, b_array_1, b_array_2, s2 = params

    # Fudge an offset due to Payne spiking at the left edge of wav. range - NO LONGER NEEDED so set to 0
    fudge_offset = 0

    # Deal with pixels which are nan    
    spectrum = Y_u_all[:, spec_no][censor_mask][fudge_offset:]
    #spectrum_errors = np.sqrt(1./Y_u_all_err[:, spec_no][censor_mask][fudge_offset:]) # we need sigma here, not 1/sigma^2

    adjusted_ivar = Y_u_all_err[:, spec_no]/(1. + Y_u_all_err[:, spec_no] * s2)
    spectrum_errors = np.sqrt(1.0/adjusted_ivar)[censor_mask][fudge_offset:]

    bad_pixels = np.isnan(spectrum * spectrum_errors)
    spectrum[bad_pixels] = 1.
    spectrum_errors[bad_pixels] = 9999.


    # ===========================================================================
    # fit best models
    def fit_func(input_param, *labels):
        predict_flux = w_array_2 * sigmoid_def(np.sum(w_array_1 * (sigmoid_def(np.dot(
            w_array_0, labels) + b_array_0)), axis=1) + b_array_1) \
                       + b_array_2
    
        # perform radial velocity shift
        # f_interp = interpolate.interp1d(wavelength_template, predict_flux,
        #                                 bounds_error=False, kind="linear", fill_value="extrapolate")
        # return f_interp(wavelength_template + labels[-1] * wavelength_template / 10 ** 5)

        return predict_flux[censor_mask][fudge_offset:]


    p0_test = np.zeros(num_labels)
    
    # set bounds
    bounds = np.zeros((num_labels, 2))
    bounds[:, 0] = -0.5
    bounds[:, 1] = 0.5

    '''
    kwds = {
        "f": fit_func,
        "xdata": None,
        "ydata": spectrum,
        "sigma": spectrum_errors,
        "absolute_sigma": True,
        "p0": p0_test,

        # These get passed through to leastsq:
        #"Dfun": Dfun,
        "col_deriv": True,
        "ftol": 7./3 - 4./3 - 1, # Machine precision.
        "xtol": 7./3 - 4./3 - 1, # Machine precision.
        "gtol": 0.0,
        "maxfev": 100000, # MAGIC
        "epsfcn": None,
        "factor": 0.1, # Smallest step size available for gradient approximation
        "diag": 1.0/(x_max-x_min)
    }
    '''


    try:
        popt, pcov = curve_fit(fit_func, [spec_no], spectrum,
                               p0=p0_test,
                               sigma=spectrum_errors,
                               absolute_sigma=True, bounds=bounds.T)
        #popt, pcov = curve_fit(**kwds)
        uncertainties = np.sqrt(np.diag(pcov))
    except RuntimeError:
        logging.info("!!! Fitting failed")
        popt = np.zeros(num_labels) - 9999.
        uncertainties = np.zeros(num_labels) - 9999.

    return np.concatenate([popt, uncertainties])

def test_nn(payne_status, threads, num_labels, test_spectra, test_spectra_errors, censors):
    # set number of threads per CPU
    os.environ['OMP_NUM_THREADS'] = '{:d}'.format(1)

    # =====================================================================
    # number of processor
    num_CPU = threads

    # ======================================================================
    # testing spectra

    Y_u_all = test_spectra.T
    Y_u_all_err = test_spectra_errors.T

    # ======================================================================
    # load NN results
    w_array_0 = payne_status["w_array_0"]
    w_array_1 = payne_status["w_array_1"]
    w_array_2 = payne_status["w_array_2"]
    b_array_0 = payne_status["b_array_0"]
    b_array_1 = payne_status["b_array_1"]
    b_array_2 = payne_status["b_array_2"]
    s2 = payne_status["s2"]
    x_min = payne_status["x_min"][:num_labels]
    x_max = payne_status["x_max"][:num_labels]

    # =======================================================================
    # make spectroscopic mask

    # if desired, bodge some of the errors to be huge in order to create a mask

    # ============================================================================
    # fit spectra
    params = [num_labels, Y_u_all, Y_u_all_err, censors['[Fe/H]'], x_min, x_max, w_array_0, w_array_1, w_array_2, b_array_0, b_array_1, b_array_2, s2]

    #print(np.sqrt(1./Y_u_all_err[:, 0]))
    #print(np.sqrt(s2))

    # Fitting in parallel
    
    recovered_results = np.array(fit_spectrum([0]+params)).T

    # Fitting in serial
    # recovered_results = []
    # for i in range(Y_u_all.shape[1]):
    #     recovered_results.append(fit_spectrum([i]+params))
    # recovered_results = np.array(recovered_results).T

    # -------------------------------------------------------------------------------
    # initiate chi^2
    chi2 = []
    results = []
    uncertainties = []

    # loop over all spectra
    j = 0
    #for j in range(recovered_results.shape[1]):

    labels = recovered_results[:num_labels]
    ind_invalid = (labels < -100.)
    labels = (labels + 0.5) * (x_max - x_min) + x_min
    labels[ind_invalid] = -999.
    results.append(labels)

    uncert = recovered_results[num_labels:]
    uncert = (uncert) * (x_max - x_min)
    uncertainties.append(uncert)

    predict_flux = w_array_2 * sigmoid_def(np.sum(w_array_1 * (sigmoid_def(np.dot(
        w_array_0, recovered_results[:num_labels]) + b_array_0)), axis=1) + b_array_1) \
                   + b_array_2

    # radial velocity
    # f_interp = interpolate.interp1d(wavelength_template, predict_flux,
    #                                 bounds_error=False, kind="linear", fill_value="extrapolate")
    # predict_flux = f_interp(wavelength_template \
    #                         + recovered_results[-1, j] * wavelength_template / 10 ** 5)
    chi2.append(np.mean((predict_flux - Y_u_all[:, j]) ** 2 * (Y_u_all_err[:, j])))

    if False:
        import matplotlib
        # matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig = plt.figure(figsize=(12, 8), dpi=200)
        plt.plot(Y_u_all[:, j][censors['[Fe/H]']], color='black')
        plt.plot(predict_flux[censors['[Fe/H]']], color='red')
        plt.show()
    chi2 = np.array(chi2)

    # ----------------------------------------------------------------------------
    # rescale back to original values


    # save array
    return {
        'results': np.array(results).T,
        'uncertainties': np.array(uncertainties).T,
        'chi2': chi2,
        'num_pix': np.sum(Y_u_all_err[:, 0] != 999.)
    }
