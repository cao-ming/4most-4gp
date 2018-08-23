#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-

"""
This python package provides a wrapper for functions provided by the 4MOST Facility Simulator, 4FS.
"""

import logging
from numpy import RankWarning
from warnings import simplefilter

from .fourfs import FourFS

__version__ = "release-2019-09-01-01"

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # TODO: Remove this when stable.

handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-8s] %(message)s"))
logger.addHandler(handler)

simplefilter("ignore", RankWarning)
simplefilter("ignore", RuntimeWarning)


