"""
Copyright (C) 2015-2020  Axel Rau <axel.rau@chaos1.de>

This file is part of serverPKI.

serverPKI is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Foobar is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with serverPKI.  If not, see <http://www.gnu.org/licenses/>.
"""

# schedule module of serverPKI

#--------------- imported modules --------------
from datetime import datetime, timedelta, date
from email.mime.text import MIMEText
import smtplib
import sys

from functools import total_ordering
from postgresql import driver as db_conn

from serverPKI.config import Pathes, SSH_CLIENT_USER_NAME, PRE_PUBLISH_TIMEDELTA
from serverPKI.config import LOCAL_ISSUE_MAIL_TIMEDELTA
from serverPKI.config import MAIL_RELAY, MAIL_SENDER, MAIL_RECIPIENT
from serverPKI.cert import Certificate
from serverPKI.certinstance import CertInstance
from serverPKI.certdist import deployCerts, distribute_tlsa_rrs
from serverPKI.issue_LE import issue_LE_cert
from serverPKI.utils import sld, sli, sln, sle
from serverPKI.utils import shortDateTime, update_state_of_instance
from serverPKI.utils import options as opts

#---------------  prepared SQL queries for query instances  --------------

q_query_state_and_dates = """
    SELECT id, state, not_before, not_after
        FROM Certinstances
        WHERE certificate = $1
        ORDER BY id
"""

to_be_deleted = set()
to_be_mailed = []

# ------------------- public ENUMS ------------------
from enum import Enum, unique, auto
@unique
class Action(Enum):
    issue = auto()
    prepublish = auto()
    distribute = auto()
    expire = auto()
    archive = auto()
    delete = auto()


ma = Action.distribute



# #---------------  public functions  --------------


def scheduleCerts(db: db_conn, cert_metas: list) -> None:
    """
    Schedule state transitions and do related actions of CertInstances
    :param db: Open Database connection
    :param cert_metas: list of Cerificate instances to act on
    :return:
    """

    global ps_delete, to_be_deleted

    def issue(cm):
        if cm.cert_type == 'local':
            return None
        if opts.check_only:
            sld('Would issue {}.'.format(cm.name))
            return
        if not cm.disabled:
            sli('Requesting issue from LE for {}'.format(cm.name))
            return issue_LE_cert(cm)                                        ##FIXME##
            
    def prepublish(cm: Certificate, active_ci: CertInstance, new_ci: CertInstance):
        if opts.check_only:
            sld('Would prepublish {} {}.'.format(active_ci.row_id, new_ci.row_id))
            return
        active_TLSA = cm.TLSA_hash(active_ci.row_id)                        ##FIXME##
        prepublishing_TLSA = cm.TLSA_hash(new_ci.row_id)
        sli('Prepublishing {}:{}:{}'.
                                format(cm.name, active_ci.row_id, new_ci.row_id))
        distribute_tlsa_rrs(cm, active_TLSA, prepublishing_TLSA)            ##FIXME##
        new_ci.state = 'prepublished'
        cm.save_instance(new_ci)
            
    def distribute(cm, ci, state):
        if opts.check_only:
            sld('Would distribute {}.'.format(ci.row_id))
            return
        sli('Distributing {}:{}'.
            format(cm.name, ci.row_id))
        cm_dict = {cm.name: cm}
        try:
            deployCerts(cm_dict, ci, allowed_states=(state,))
        except Exception:
            sln('Skipping distribution of cert {} because {} [{}]'.format(
                                            cm.name,
                                            sys.exc_info()[0].__name__,
                                            str(sys.exc_info()[1])))
               
    def expire(cm, ci):
        if opts.check_only:
            sld('Would expire {}.'.format(ci.id))
            return
        sli('State transition from {} to EXPIRED of {}:{}'.
                                format(ci.state, cm.name, ci.row_id))
        ci.state = 'expired'
        cm.save_instance(ci)

    def archive(cm, ci):
        if opts.check_only:
            sld('Would archive {}.'.format(ci.row_id))
            return
        sli('State transition from {} to ARCHIVED of {}:{}'.
                                format(ci.state, cm.name, ci.row_id))
        ci.state = 'archived'
        cm.save_instance(ci)

    for cm in cert_metas:

        sld('{} {} ------------------------------'.format(
                                        cm.name,
                                        'DISABLED' if cm.disabled else ''))
        if cm.subject_type == 'CA': continue

        issued_ci = None
        prepublished_ci = None
        deployed_ci = None
        
        surviving = _find_to_be_deleted(cm)

        if not surviving:
            ci = issue(cm)
            if id: distribute(cm, ci, 'issued')
            continue
        
        for ci in surviving:
            if ci.state == 'expired':
                archive(cm, ci)
                continue
            if datetime.utcnow() >= (ci.not_after + timedelta(days=1)):
                if ci.state != 'deployed':
                    expire(cm, ci)
                continue
            elif ci.state == 'issued': issued_ci = ci
            elif ci.state == 'prepublished': prepublished_ci = ci
            elif ci.state == 'deployed': deployed_ci = ci
            else: assert(ci.state in ('issued', 'prepublished', 'deployed', ))
            
        if deployed_ci and issued_ci: # issued too old to replace deployed in future?
            if issued_ci.not_after < ( deployed_ci.not_after +
                                        LOCAL_ISSUE_MAIL_TIMEDELTA):
                to_be_deleted |= set((issued_ci,))   # yes: mark for delete
                issued_ci = None
                                    # request issue_mail if near to expiration
        if (deployed_ci
            and cm.cert_type == 'local'
            and not cm.authorized_until
            and datetime.utcnow() >= (deployed_ci.not_after -
                                            LOCAL_ISSUE_MAIL_TIMEDELTA)):
            to_be_mailed.append(cm)
            sld('schedule.to_be_mailed: ' + str(cm))

        if cm.disabled:
            continue
            
                                    # deployed cert expired or no cert deployed?
        if (not deployed_ci) or \
                (datetime.utcnow() >= deployed_ci.not_after - timedelta(days=1)):
            distributed = False
            sld('scheduleCerts: no deployed cert or deployed cert '
                            'expired {}'.format(str(deployed_ci)))
            if prepublished_ci:      # yes - distribute prepublished
                distribute(cm, prepublished_ci.id, 'prepublished')
                distributed = True
            elif issued_ci:          # or issued cert?
                distribute(cm, issued_ci.id, 'issued') # yes - distribute it
                distributed = True
            if deployed_ci:
                expire(cm, deployed_ci)  # and expire deployed cert
            if not distributed:
                id = issue(cm)
                if id: distribute(cm, id, 'issued')
            continue
        
        if cm.cert_type == 'local':
            continue                # no TLSAs with local certs
                                    # We have an active LE cert deployed
        if datetime.utcnow() >= \
            (deployed_ci.not_after - PRE_PUBLISH_TIMEDELTA):
                                    # pre-publishtime reached?
            ci = issued_ci
            if prepublished_ci:      # yes: TLSA already pre-published?
                continue            # yes
            elif not issued_ci:      # do we have a cert handy?
                id = issue(cm) # no: create one
                if not id:
                    sln('Failed to issue cert for prepublishing of {}'.format(cm.name))
                    continue
                ci = CertInstance(id, None, None, None)
            sld('scheduleCerts will call prepublish with deployed_ci={}, i={}'.format(
                                str(deployed_ci), str(ci)))
            prepublish(cm, deployed_ci, ci) # and prepublish it
    
    # end for name in cert_names
    
    if opts.check_only:
        sld('Would delete and mail..')
        return
    for ci in to_be_deleted:
        sld('Deleting {}'.format(ci.row_id))
        result = cm.delete_instance(ci)
        if result != 1:
            sln('Failed to delete cert instance {}'.format(ci.id))

    if to_be_mailed:
        
        body = str('Following local Certificates must be issued prior to {}:\n'.
            format(date.today()+LOCAL_ISSUE_MAIL_TIMEDELTA))
            
        for cert_meta in to_be_mailed:
            body += str('\t{} \t{}'.format(cert_meta.name,
                                '[DISABLED]' if cert_meta.disabled else ''))
            cert_meta.update_authorized_until(datetime.utcnow())
        
        msg = MIMEText(body)
        msg['Subject'] = 'Local certificate issue reminder'
        msg['From'] = MAIL_SENDER
        msg['To'] = MAIL_RECIPIENT
        s = smtplib.SMTP(MAIL_RELAY)
        s.send_message(msg)
        s.quit()

        
#---------------  private functions  --------------

def _find_to_be_deleted(cm: Certificate) -> set:
    """
    Create set of CertInstances to be deleted.
    Keep most recent active Certinstance in state prepublished and deployed.
    If only active in state issued and expired, keep theese.
    :param cm: Certificate to act on
    :return: Set of Certinstances to be deleted
    """

    surviving = set()

    if cm.cert_instances == 0: return None
    for ci in cm.cert_instances:
         sld('{:04} Issued {}, expires: {}, state {}\t{}'.format(
                                                ci.row_id,
                                                shortDateTime(ci.not_before),
                                                shortDateTime(ci.not_after),
                                                ci.state,
                                                cm.name)
        )

        if ci.state in ('reserved', 'archived'):
            to_be_deleted.add(ci)
        else:
            surviving.add(ci)
        
    sld('Before state loop: ' + str([i.__str__() for i in surviving]))
    for state in ('issued', 'prepublished', 'deployed', 'expired',):
        ci_list = []
        for ci in surviving:
            if ci.state == state:
                ci_list.append(ci)
        ci_list.sort()
        s = set(ci_list[:-1])    # most recent instance survives
        surviving -= s          # remove other instances from surviving set
        to_be_deleted |= s      # add other instances to to_be_deleted set
        sld('{}: {}'.format(state, str([i.__str__() for i in ci_list])))
     
    sld('to_be_deleted : {}'.format(str([i.__str__() for i in to_be_deleted])))
    sld('surviving : {}'.format(str([i.__str__() for i in surviving])))
    sld('---------------------------------------------------------------')
    
    return surviving
