#----------------------------------------------------------------------
# Copyright (c) 2014 Raytheon BBN Technologies
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

import datetime
from dateutil import parser as du_parser, tz as du_tz
import optparse
import os
import subprocess
import sys
import tempfile
import sfa.trust.certificate
import sfa.trust.credential
from xml.dom.minidom import *

# Routine to validate that a speaks-for credential 
# says what it claims to say:
# It is a signed credential wherein the signer S is attesting to the
# ABAC statement:
# S.speaks_for(S)<-T
# Or "S says that T speaks for S"

# Simple XML helper functions

# Find the text associated with first child text node
def findTextChildValue(root):
    for child in root.childNodes:
        if child.nodeName == "#text":
            return str(child.nodeValue)
    return None

# Find first child with given name
def findChildNamed(root, name):
    for child in root.childNodes:
        if child.nodeName == name:
            return child
    return None

# Pull user URN from certificate object
def extract_urn_from_cert(cert):
    data = cert.get_data('subjectAltName')
    data_parts = data.split(', ')
    for data_part in data_parts:
        if data_part.startswith('URI:urn:publicid'):
            return data_part[4:]
    return None

# Write a string to a tempfile, returning name of tempfile
def write_to_tempfile(str):
    str_fd, str_file = tempfile.mkstemp()
    os.write(str_fd, str)
    os.close(str_fd)
    return str_file

# Get list of certs in given directory
def get_certs_in_directory(dir):
    files = os.listdir(dir)
    certs = [sfa.trust.certificate.Certificate(filename=os.path.join(dir, file)) \
                 for file in files]
    return certs

# Pull the keyid (sha1 hash of the bits of the cert public key) from given cert
def get_cert_keyid(cert):
    
    # Write cert to tempfile
    cert_file = write_to_tempfile(cert)

    # Pull the public key out as pem
    # openssl x509 -in cert.pem -pubkey -noout > key.pem
    cmd = ['openssl', 'x509', '-in', cert_file, '-pubkey', '-noout']
    pubkey_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    pubkey_proc.wait()
    pubkey = pubkey_proc.stdout.read()
    pubkey_fd, pubkey_file = tempfile.mkstemp()
    os.write(pubkey_fd, pubkey)
    os.close(pubkey_fd)
    
    # Pull out the bits
    # openssl asn1parse -in key.pem -strparse 18 -out key.der
    derkey_fd, derkey_file = tempfile.mkstemp()
    os.close(derkey_fd)
    cmd = ['openssl', 'asn1parse', '-in', pubkey_file, '-strparse', \
               '18', '-out', derkey_file]
    subprocess.call(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    

    # Get the hash
    # openssl sha1 key.der
    cmd = ['openssl', 'sha1', derkey_file]
    sha_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                                stderr=subprocess.PIPE)
    sha_proc.wait()
    output = sha_proc.stdout.read()
    parts = output.split(' ')
    keyid = parts[1].strip()

    os.unlink(cert_file)
    os.unlink(pubkey_file)
    os.unlink(derkey_file)

    return keyid

# Pull the cert out of a list of certs in a PEM formatted cert string
def grab_toplevel_cert(cert):
    start_label = '-----BEGIN CERTIFICATE-----'
    start_index = cert.find(start_label) + len(start_label)
    end_label = '-----END CERTIFICATE-----'
    end_index = cert.find(end_label)
    first_cert = cert[start_index:end_index]
    pieces = first_cert.split('\n')
    first_cert = "".join(pieces)
    return first_cert

# Validate that the given speaks-for credential represents the
# statement User.speaks_for(User)<-Tool for the given user and tool certs
# and was signed by the user
# Return: 
#   Boolean indicating whether the given credential 
#      is not expired 
#      is verified by xmlsec1
#      is trusted by given set of trusted roots
#      is an ABAC credential
#      was signed by the user associated with the speaking_for_urn
#      must say U.speaks_for(U)<-T ("user says that T may speak for user")
#  String user certificate of speaking_for user if the above tests succeed
#      (None otherwise)
#  Error message indicating why the speaks_for call failed ("" otherwise)
def verify_speaks_for(cred, tool_cert, speaking_for_urn, \
                          trusted_roots):

    # Parse XML representation of credential
    cred_doc = parseString(cred)
    root = cred_doc.childNodes[0] # signedCredential

    # Extract signer cert from the credential
    cert_nodes = root.getElementsByTagName('X509Certificate')
    if len(cert_nodes) == 0:
        return False, None, "Invalid ABAC credential: No X509 cert"
    user_cert_text = findTextChildValue(cert_nodes[0])
    user_cert = \
        '-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n' % \
        user_cert_text

    user_keyid = get_cert_keyid(user_cert)
    tool_keyid = get_cert_keyid(tool_cert)

    user_cert_object = sfa.trust.certificate.Certificate(string=user_cert)
    user_urn = extract_urn_from_cert(user_cert_object)

    head_elts = root.getElementsByTagName('head')
    if len(head_elts) != 1: 
        return False, None, "Invalid ABAC credential: No head element"
    head_elt = head_elts[0]

    principal_keyid_elts = head_elt.getElementsByTagName('keyid')
    if len(principal_keyid_elts) != 1: 
        return False, None, "Invalid ABAC credential: No head principal element"
    principal_keyid_elt = principal_keyid_elts[0]
    principal_keyid = findTextChildValue(principal_keyid_elt)

    role_elts = head_elt.getElementsByTagName('role')
    if len(role_elts) != 1: 
        return False, None, "Invalid ABAC credential: No role element"
    role = findTextChildValue(role_elts[0])

    tail_elts = root.getElementsByTagName('tail')
    if len(tail_elts) != 1: 
        return False, None, "Invalid ABAC credential: No tail element" 
    subject_keyid_elts = tail_elts[0].getElementsByTagName('keyid')
    if len(subject_keyid_elts) != 1: 
        return False, None, "Invalid ABAC credential: No tail subject element"
    subject_keyid = findTextChildValue(subject_keyid_elts[0])

    credential_elt = findChildNamed(root, 'credential')
    cred_type_elt = findChildNamed(credential_elt, 'type')
    cred_type = findTextChildValue(cred_type_elt)

    expiration = root.getElementsByTagName('expires')[0]
    expiration_value = expiration.childNodes[0].nodeValue
    expiration_time = du_parser.parse(expiration_value)
    current_time = datetime.datetime.now(du_tz.tzutc())

    # Now tests that this is a valid credential

    # Credential has not expired
    if expiration_time < current_time:
        return False, None, "ABAC Credential expired"

    # Credential must pass xmlsec1 verify
    cred_file = write_to_tempfile(cred)
    xmlsec1_args = ['xmlsec1', '--verify', cred_file]
    proc = subprocess.Popen(xmlsec1_args, stderr=subprocess.PIPE)
    proc.wait()
    output = proc.returncode
    os.unlink(cred_file)
    if output != 0:
        return False, None, "ABAC credentaial failed to xmlsec1 verify"

    # Must be ABAC
    if cred_type != 'abac':
        return False, None, "Credential not of type ABAC"
    # Must say U.speaks_for(U)<-T
    if user_keyid != principal_keyid or \
            tool_keyid != subject_keyid or \
            role != ('speaks_for_%s' % user_keyid):
        return False, None, "ABAC statement doesn't assert U.speaks_for(U)<-T"

    # URN of signer from cert must match URN of 'speaking-for' argument
    if user_urn != speaking_for_urn:
        return False, None, "User URN doesn't match speaking_for URN"

    # User certificate must validate against trusted roots
    try:
        user_cert_object.verify_chain(trusted_roots)
    except Exception:
        return False, None, "User cert doesn't validaate against trusted roots"

    return True, user_cert, ""

# Determine if this is a speaks-for context. If so, validate
# And return either the tool_cert (not speaks-for or not validated)
# or the user cert (validated speaks-for)
# credentials is a list of GENI-style credentials:
#    [{'geni_type' : geni_type, 
#      'geni_value : cred_value, 
#      'geni_version' : version}]
# caller_cert is the raw X509 cert string
# options is the dictionary of API-provided options
# trusted_roots is a list of Certificate objects from the system
#   trusted_root directory
def determine_speaks_for(credentials, caller_cert, options, \
                             trusted_roots):
    if 'geni_speaking_for' in options:
        speaking_for_urn = options['geni_speaking_for']
        for cred in credentials:
            if type(cred) == dict:
                if cred['geni_type'] != 'geni_abac': continue
                cred_value = cred['geni_value']
            elif isinstance(cred, sfa.trust.credential.Credential):
                if isinstance(cred, sfa.trust.credential.ABACCredential):
                    cred_value = cred.get_xml()
                else:
                    continue
            else:
                if cred.find('abac') < 0: continue
                cred_value = cred
            is_valid_speaks_for, user_cert, msg = \
                verify_speaks_for(cred_value,
                                  caller_cert, speaking_for_urn, \
                                      trusted_roots)
            if is_valid_speaks_for:
                return user_cert # speaks-for
    return caller_cert # Not speaks-for

def create_speaks_for(tool_cert_file, user_cert_file, \
                          user_key_file, ma_cert_file, cred_filename):
    tool_cert = \
        sfa.trust.certificate.Certificate(filename=tool_cert_file)
    tool_urn = extract_urn_from_cert(tool_cert)
    user_cert = \
        sfa.trust.certificate.Certificate(filename=user_cert_file)
    user_urn = extract_urn_from_cert(user_cert)

    header = '<?xml version="1.0" encoding="UTF-8"?>'
    signature_block = \
        '<signatures>\n' + \
	'<Signature xmlns="http://www.w3.org/2000/09/xmldsig#" xml:id="Sig_ref0">\n' + \
        '<SignedInfo>\n' + \
        '<CanonicalizationMethod Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"/>\n' + \
        '<SignatureMethod Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1"/>\n' + \
        '<Reference URI="#ref0">\n' + \
        '<Transforms>\n' + \
        '<Transform Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"/>\n' + \
        '</Transforms>\n' + \
        '<DigestMethod Algorithm="http://www.w3.org/2000/09/xmldsig#sha1"/>\n' + \
        '<DigestValue/>\n' + \
        '</Reference>\n' + \
        '</SignedInfo>\n' + \
        '<SignatureValue/>\n' + \
        '<KeyInfo>\n' + \
        '<KeyValue>\n' + \
        '<RSAKeyValue>\n' + \
        '<Modulus/>\n' + \
        '<Exponent/>\n' + \
        '</RSAKeyValue>\n' + \
        '</KeyValue>\n' + \
        '<X509Data>\n' + \
        '<X509Certificate/>\n' + \
        '<X509SubjectName/>\n' + \
        '<X509IssuerSerial/>\n' + \
        '</X509Data>\n' + \
        '</KeyInfo>\n' + \
	'</Signature>\n' + \
        '</signatures>'
    template = header + '\n' + \
        '<signed-credential>\n' + \
        '<credential xml:id="ref0">\n' + \
        '<type>abac</type>\n' + \
        '<serial/>\n' +\
        '<owner_gid/>\n' + \
        '<target_gid/>\n' + \
        '<uuid/>\n' + \
        '<expires>%s</expires>' +\
        '<abac>\n' + \
        '<rt0>\n' + \
        '<version>%s</version>\n' + \
        '<head>\n' + \
        '<ABACprincipal><keyid>%s</keyid></ABACprincipal>\n' +\
        '<role>speaks_for_%s</role>\n' + \
        '</head>\n' + \
        '<tail>\n' +\
        '<ABACprincipal><keyid>%s</keyid></ABACprincipal>\n' +\
        '</tail>\n' +\
        '</rt0>\n' + \
        '</abac>\n' + \
        '</credential>\n' + \
        signature_block + \
        '</signed-credential>\n'


    credential_duration = datetime.timedelta(days=365)
    expiration = datetime.datetime.now(du_tz.tzutc()) + credential_duration
    version = "1.1"

    user_cert = open(user_cert_file).read()
    tool_cert = open(tool_cert_file).read()
    user_keyid = get_cert_keyid(user_cert)
    tool_keyid = get_cert_keyid(tool_cert)
    unsigned_cred = template % (expiration, version, \
                                    user_keyid, user_keyid, tool_keyid)
    unsigned_cred_fd, unsigned_cred_filename = tempfile.mkstemp()
#    print "UCF = %s" % unsigned_cred_filename
    os.write(unsigned_cred_fd, unsigned_cred)
    os.close(unsigned_cred_fd)

    # Now sign the file with xmlsec1
    # xmlsec1 --sign --privkey-pem privkey.pem,cert.pem 
    # --output signed.xml tosign.xml
    pems = "%s,%s,%s" % (user_key_file, user_cert_file, ma_cert_file)
    cmd = ['xmlsec1',  '--sign',  '--privkey-pem', pems, 
           '--output', cred_filename, unsigned_cred_filename]

#    print " ".join(cmd)
    sign_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    sign_proc.wait()
    sign_proc_output = sign_proc.stdout.read()
    if sign_proc_output == None:
        print "OUTPUT = %s" % sign_proc_output
    else:
        print "Created ABAC creadential %s speaks_for %s in file %s" % \
            (tool_urn, user_urn, cred_filename)
    os.unlink(unsigned_cred_filename)

# Test procedure
if __name__ == "__main__":

    parser = optparse.OptionParser()
    parser.add_option('--cred_file', 
                      help='Name of credential file')
    parser.add_option('--tool_cert_file', 
                      help='Name of file containing tool certificate')
    parser.add_option('--user_urn', 
                      help='URN of speaks-for user')
    parser.add_option('--user_cert_file', 
                      help="filename of x509 certificate of signing user")
    parser.add_option('--ma_cert_file', 
                      help="filename of x509 certificate of MA that created user cert")
    parser.add_option('--user_key_file', 
                      help="filename of private key of signing user")
    parser.add_option('--trusted_roots_directory', 
                      help='Directory of trusted root certs')
    parser.add_option('--create',
                      help="name of file of ABAC speaksfor cred to create")
                      
    options, args = parser.parse_args(sys.argv)


    if options.create and options.user_cert_file and options.user_key_file \
            and options.ma_cert_file:
        create_speaks_for(options.tool_cert_file, options.user_cert_file, \
                              options.user_key_file, options.ma_cert_file, \
                              options.create)
        sys.exit()



    cred_file = options.cred_file
    tool_cert_file = options.tool_cert_file
    user_urn = options.user_urn
    trusted_roots_directory = options.trusted_roots_directory
    trusted_roots = [sfa.trust.certificate.Certificate(filename=os.path.join(trusted_roots_directory, file)) \
                         for file in os.listdir(trusted_roots_directory) \
                         if file.endswith('.pem') and file != 'CATedCACerts.pem']

    cred = open(cred_file).read()
    tool_cert = open(tool_cert_file).read()

    vsf, user_cert,msg = verify_speaks_for(cred, tool_cert, user_urn, \
                                trusted_roots)
    print 'VERIFY_SPEAKS_FOR = %s' % vsf
    if vsf:
        print "USER_CERT = %s" % user_cert

    creds = [{'geni_type' : 'geni_abac', 
              'geni_value' : cred, 
              'geni_version' : '1'}]
    cert = determine_speaks_for(creds, \
                                    tool_cert, \
                                    {'geni_speaking_for' : user_urn}, \
                                    trusted_roots)
    print "CERT URN = %s" % extract_urn_from_cert(sfa.trust.certificate.Certificate(string=cert))

                                 



