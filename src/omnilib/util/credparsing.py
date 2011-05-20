#!/usr/bin/python

#----------------------------------------------------------------------
# Copyright (c) 2011 Raytheon BBN Technologies
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and/or hardware specification (the "Work") to
# deal in the Work without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Work, and to permit persons to whom the Work
# is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Work.
#
# THE WORK IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE WORK OR THE USE OR OTHER DEALINGS
# IN THE WORK.
#----------------------------------------------------------------------
"""
   Utilities to parse credentials
"""

import dateutil.parser
import logging
import traceback
import xml.dom
import xml.dom.minidom as md

def get_cred_exp(logger, credString):
    '''Parse the given credential in GENI AM API XML format to get its expiration time and return that'''
    
    # Don't fully parse credential: grab the expiration from the string directly
    credexp = 0

    if credString is None:
        # failed to get a credential string. Can't check
        return credexp

    try:
        doc = md.parseString(credString)
        signed_cred = doc.getElementsByTagName("signed-credential")

        # Is this a signed-cred or just a cred?
        if len(signed_cred) > 0:
            cred = signed_cred[0].getElementsByTagName("credential")[0]
        else:
            cred = doc.getElementsByTagName("credential")[0]
        expirnode = cred.getElementsByTagName("expires")[0]
        if len(expirnode.childNodes) > 0:
            credexp = dateutil.parser.parse(expirnode.childNodes[0].nodeValue)
    except Exception, exc:
        logger.error("Failed to parse credential for expiration time: %s", exc)
        logger.debug(traceback.format_exc())

    return credexp

