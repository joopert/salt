# -*- coding: utf-8 -*-
'''
 Beacon to announce via Bonjour (zeroconf)
'''

# Import Python libs
from __future__ import absolute_import
import atexit
import logging
import select
import time

# Import 3rd Party libs
try:
    import pybonjour
    HAS_PYBONJOUR = True
except ImportError:
    HAS_PYBONJOUR = False

log = logging.getLogger(__name__)

__virtualname__ = 'bonjour_announce'

LAST_GRAINS = {}
SD_REF = None


def __virtual__():
    if HAS_PYBONJOUR:
        return __virtualname__
    return False


def _close_sd_ref():
    '''
    Close the SD_REF object if it isn't NULL
    For use with atexit.register
    '''
    global SD_REF
    if SD_REF:
        SD_REF.close()
        SD_REF = None


def _register_callback(sdRef, flags, errorCode, name, regtype, domain):  # pylint: disable=unused-argument
    if errorCode != pybonjour.kDNSServiceErr_NoError:
        log.error('Bonjour registration failed with error code {0}'.format(errorCode))


def __validate__(config):
    '''
    Validate the beacon configuration
    '''
    if not isinstance(config, dict):
        return False, ('Configuration for bonjour_announcement '
                       'beacon must be a dictionary')
    elif not all(x in list(config.keys()) for x in ('servicetype', 'port', 'txt')):
        return False, ('Configuration for bonjour_announce beacon '
                       'must contain servicetype, port and txt items')
    return True, 'Valid beacon configuration'


def beacon(config):
    '''
    Broadcast values via zeroconf

    If the announced values are static, it is adviced to set run_once: True
    (do not poll) on the beacon configuration.

    The following are required configuration settings:
        'servicetype': The service type to announce.
        'port': The port of the service to announce.
        'txt': The TXT record of the service being announced as a dict.
               Grains can be used to define TXT values using the syntax:
                   grains.<grain_name>
               or:
                   grains.<grain_name>[i]
               where i is an integer representing the index of the grain to
               use. If the grain is not a list, the index is ignored.

    The following are optional configuration settings:
        'servicename': Set the name of the service. Will use the hostname from
                       __grains__['host'] if not set.
        'reset_on_change': If true and there is a change in TXT records
                           detected, it will stop announcing the service and
                           then restart announcing the service. This
                           interruption in service announcement may be
                           desirable if the client relies on changes in the
                           browse records to update its cache of the TXT
                           records.
                           Defaults to False.
        'reset_wait': The number of seconds to wait after announcement stops
                      announcing and before it restarts announcing in the
                      case where there is a change in TXT records detected
                      and 'reset_on_change' is True.
                      Defaults to 0.
        'copy_grains': If set to True, it will copy the grains passed into
                       the beacon when it backs them up to check for changes
                       on the next iteration. Normally, instead of copy, it
                       would use straight value assignment. This will allow
                       detection of changes to grains where the grains are
                       modified in-place instead of completely replaced.
                       In-place grains changes are not currently done in the
                       main Salt code but may be done due to a custom
                       plug-in.
                       Defaults to False.

    Example Config

    .. code-block:: yaml

       beacons:
         bonjour_announce:
           run_once: True
           servicetype: _demo._tcp
           port: 1234
           txt:
             ProdName: grains.productname
             SerialNo: grains.serialnumber
             Comments: 'this is a test'
    '''
    ret = []
    changes = {}
    txt = {}

    global LAST_GRAINS
    global SD_REF

    _validate = __validate__(config)
    if not _validate[0]:
        log.warning('Beacon {0} configuration invalid, '
                    'not adding. {1}'.format(__virtualname__, _validate[1]))
        return ret

    if 'servicename' in config:
        servicename = config['servicename']
    else:
        servicename = __grains__['host']

    for item in config['txt']:
        if config['txt'][item].startswith('grains.'):
            grain = config['txt'][item][7:]
            grain_index = None
            square_bracket = grain.find('[')
            if square_bracket != -1 and grain[-1] == ']':
                grain_index = int(grain[square_bracket+1:-1])
                grain = grain[:square_bracket]

            grain_value = __grains__.get(grain, '')
            if isinstance(grain_value, list):
                if grain_index is not None:
                    grain_value = grain_value[grain_index]
                else:
                    grain_value = ','.join(grain_value)
            txt[item] = grain_value
            if LAST_GRAINS and (LAST_GRAINS.get(grain, '') != __grains__.get(grain, '')):
                changes[str('txt.' + item)] = txt[item]
        else:
            txt[item] = config['txt'][item]

        if not LAST_GRAINS:
            changes[str('txt.' + item)] = txt[item]

    if changes:
        txt_record = pybonjour.TXTRecord(items=txt)
        if not LAST_GRAINS:
            changes['servicename'] = servicename
            changes['servicetype'] = config['servicetype']
            changes['port'] = config['port']
            SD_REF = pybonjour.DNSServiceRegister(
                name=servicename,
                regtype=config['servicetype'],
                port=config['port'],
                txtRecord=txt_record,
                callBack=_register_callback)
            atexit.register(_close_sd_ref)
            ready = select.select([SD_REF], [], [])
            if SD_REF in ready[0]:
                pybonjour.DNSServiceProcessResult(SD_REF)
        elif config.get('reset_on_change', False):
            SD_REF.close()
            SD_REF = None
            reset_wait = config.get('reset_wait', 0)
            if reset_wait > 0:
                time.sleep(reset_wait)
            SD_REF = pybonjour.DNSServiceRegister(
                name=servicename,
                regtype=config['servicetype'],
                port=config['port'],
                txtRecord=txt_record,
                callBack=_register_callback)
            ready = select.select([SD_REF], [], [])
            if SD_REF in ready[0]:
                pybonjour.DNSServiceProcessResult(SD_REF)
        else:
            txt_record_raw = str(txt_record).encode('utf-8')
            pybonjour.DNSServiceUpdateRecord(
                SD_REF,
                RecordRef=None,
                flags=0,
                rdata=txt_record_raw)

        ret.append({'tag': 'result', 'changes': changes})

    if config.get('copy_grains', False):
        LAST_GRAINS = __grains__.copy()
    else:
        LAST_GRAINS = __grains__

    return ret
