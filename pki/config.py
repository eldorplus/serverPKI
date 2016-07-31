
from pathlib import Path

class Pathes(object):
    """
    Definition of path config variables
    """
    
    home = Path('/var/pki_op/productive_CA').resolve()       # adjust
    
    db = home / 'db'
    ca_cert = db / 'ca_cert.pem'
    ca_key = db / 'ca_key.pem'
    le_account = db / 'account.json'    
    work = home / 'work'
    work_tlsa = work / 'TLSA'
    
    tlsa_dns_master = ''
    dns_key = db / 'dns'
    
    
    # required convention: zone_file_root/example.com/example.com.zone
    
    zone_file_root = Path('/usr/local/etc/namedb/master/signed')
    zone_file_include_name = 'acme_challenges.inc'
    
    
class X509atts(object):
    """
    Definition of fixed X.509 cert attributes
    """
    names = {   'C':    'DE',
                'L':    'Frankfurt am Main',
                'O':    'LECHNER-RAU',
                'CN':   'Lechner-Rau internal CA'
            }
    
    extensions = {
    
                }
    
    lifetime = 375                         # 1 year
    bits = 2048


# Database accounts
dbAccounts = {  'pki_dev':  {'dbHost':       'db1.in.chaos1.de',
                            'dbPort':         '2222',
                            'dbUser':         'pki_op',
                            'dbDatabase':     'pki_op',
                            'dbSearchPath':   'pki,dd,public'}}

SSH_CLIENT_USER_NAME = 'root'

LE_SERVER = 'https://acme-v01.api.letsencrypt.org'
##LE_SERVER = 'https://acme-staging.api.letsencrypt.org'

# subjects in table Subjects:

SUBJECT_LOCAL_CA = 'Local CA'
LOCAL_CA_BITS = 4096
LOCAL_CA_LIFETIME = 3680

SUBJECT_LE_CA = 'Lets Encrypt CA'


# do we need his:  ??
DEBUG = True

def debugging(arg):
    global DEBUG
    DEBUG = arg
