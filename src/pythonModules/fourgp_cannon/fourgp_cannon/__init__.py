#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-

import logging
from numpy import RankWarning
from warnings import simplefilter

#from .cannon_instance import \
#    CannonInstance, \
#    CannonInstanceWithContinuumNormalisation, \
#    CannonInstanceWithRunningMeanNormalisation

CannonInstance = CannonInstanceWithContinuumNormalisation = CannonInstanceWithRunningMeanNormalisation = None

from .cannon_instance_release_2018_01_09_1 import \
    CannonInstance_2018_01_09

__version__ = "0.1.0"

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # TODO: Remove this when stable.

handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-8s] %(message)s"))
logger.addHandler(handler)

simplefilter("ignore", RankWarning)
simplefilter("ignore", RuntimeWarning)


