"""Audit the pinned Espressif source path; this is NOT an RF measurement."""
import argparse
import hashlib
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
IDF_COMMIT='87912cd291'
BASE=f'https://raw.githubusercontent.com/espressif/esp-idf/{IDF_COMMIT}/components/bt/host/bluedroid/'
NIMBLE_COMMIT='039d2d62ed97fed632827fd51294f04068b2ca60'
NIMBLE_BASE=f'https://raw.githubusercontent.com/espressif/esp-nimble/{NIMBLE_COMMIT}/'
SOURCES={
    'api/include/api/esp_gap_ble_api.h':[r'ADV_CHNL_37\s*=\s*0x01',r'ADV_CHNL_38\s*=\s*0x02',r'ADV_CHNL_39\s*=\s*0x04',r'esp_ble_adv_channel_t channel_map'],
    'api/esp_gap_ble_api.c':[r'esp_ble_gap_start_advertising',r'arg\.start_adv\.adv_params'],
    'btc/profile/std/gap/btc_gap_ble.c':[r'BTA_DmSetBleAdvParamsAll',r'ble_adv_params->channel_map'],
    'bta/dm/bta_dm_api.c':[r'BTA_DmSetBleAdvParamsAll',r'chnl_map'],
    'bta/dm/bta_dm_act.c':[r'BTM_BleSetAdvParamsAll',r'ble_set_adv_params_all.channel_map'],
    'stack/btm/btm_ble_gap.c':[r'p_cb->adv_chnl_map = chnl_map',r'btsnd_hcic_ble_write_adv_params'],
    'stack/hcic/hciblecmds.c':[r'HCI_BLE_WRITE_ADV_PARAMS',r'UINT8_TO_STREAM\s*\(pp, channel_map\)']
}
NIMBLE_SOURCES={
    'nimble/host/include/host/ble_gap.h':[r'uint8_t channel_map',r'ble_gap_adv_start'],
    'nimble/host/src/ble_gap.c':[r'cmd.chan_map = adv_params->channel_map',r'BLE_HCI_OCF_LE_SET_ADV_PARAMS',r'ble_gap_adv_params_tx\(own_addr_type, direct_addr, adv_params\)'],
    'nimble/host/src/ble_hs_hci.c':[r'ble_hs_hci_wait_for_ack',r'ble_npl_sem_pend']
}


def audit(cache,offline=False):
    cache.mkdir(parents=True,exist_ok=True)
    def source(item):
        base,path,patterns=item;local=cache/(('nimble_' + NIMBLE_COMMIT[:10] if base==NIMBLE_BASE else 'idf_' + IDF_COMMIT)+'_'+path.replace('/','_'));url=base+path
        if not offline:
            with urllib.request.urlopen(url,timeout=60) as response:local.write_bytes(response.read())
        raw=local.read_bytes();text=raw.decode();hits=[]
        for pattern in patterns:
            match=re.search(pattern,text)
            if not match:raise RuntimeError(f'Expected SDK source expression absent: {path}: {pattern}')
            line=text.count('\n',0,match.start())+1
            hits.append({'pattern':pattern,'line':line,'source_line':text.splitlines()[line-1].strip()})
        return {'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'checks':hits}
    items=[(BASE,path,patterns) for path,patterns in SOURCES.items()]+[(NIMBLE_BASE,path,patterns) for path,patterns in NIMBLE_SOURCES.items()]
    with ThreadPoolExecutor(max_workers=4) as ex:results=list(ex.map(source,items))
    firmware=(ROOT/'firmware/libraries/IndoorBLE/src/BluedroidRadio.h').read_text()
    for expression in ('params.channel_map=static_cast<esp_ble_adv_channel_t>(mask)',
                       'esp_ble_gap_start_advertising(&params)',
                       'ESP_GAP_BLE_ADV_START_COMPLETE_EVT',
                       'ESP_GAP_BLE_ADV_STOP_COMPLETE_EVT',
                       'xEventGroupWaitBits'):
        if expression not in firmware:raise RuntimeError('Firmware control-path expression missing: '+expression)
    nimble=(ROOT/'firmware/libraries/IndoorBLE/src/NimbleRadio.h').read_text()
    for expression in ('params.channel_map=mask','ble_gap_adv_start(ownAddressType','ble_gap_adv_stop()','ble_gap_adv_set_data(adv,sizeof(adv))'):
        if expression not in nimble:raise RuntimeError('NimBLE firmware control-path expression missing: '+expression)
    package_evidence=[]
    import zipfile
    for target in ('esp32s3','esp32'):
        archive=ROOT/f'.tools/arduino-downloads/packages/{target}-libs-3.3.7.zip'
        if not archive.exists():continue
        with zipfile.ZipFile(archive) as z:
            cfg_path=next(n for n in z.namelist() if n.endswith('/sdkconfig.h'))
            cfg=z.read(cfg_path).decode()
            backend='NimBLE' if '#define CONFIG_BT_NIMBLE_ENABLED 1' in cfg else 'Bluedroid'
            evidence={'target':target,'sdkconfig_path':cfg_path,'backend':backend,'sdkconfig_sha256':hashlib.sha256(cfg.encode()).hexdigest()}
            if backend=='NimBLE':
                header=z.read(next(n for n in z.namelist() if n.endswith('/host/ble_gap.h')))
                source_header=(cache/('nimble_'+NIMBLE_COMMIT[:10]+'_nimble_host_include_host_ble_gap.h')).read_bytes()
                if header!=source_header:raise RuntimeError('Packaged NimBLE header differs from pinned SDK source')
                evidence['packaged_gap_header_matches_pinned_source']=True
            package_evidence.append(evidence)
    return {'checked_utc':datetime.now(timezone.utc).isoformat(),'sdk':'ESP-IDF 5.5.2 release/v5.5','idf_commit':IDF_COMMIT,'arduino_core':'3.3.7',
            'nimble_submodule_commit':NIMBLE_COMMIT,'package_evidence':package_evidence,
            'scope':'Source/API path only. Does not verify compilation, controller runtime or RF transmission.',
            'result':'PASS','sources':results,'bluedroid_firmware_sha256':hashlib.sha256(firmware.encode()).hexdigest(),
            'nimble_firmware_sha256':hashlib.sha256(nimble.encode()).hexdigest()}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--offline',action='store_true');p.add_argument('--cache',default=str(ROOT/'.tools/sdk-audit'))
    args=p.parse_args();result=audit(Path(args.cache),args.offline)
    target=ROOT/'docs/sdk-channel-audit.json';target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(f"PASS: pinned SDK source mask path. NOT RF verification. Report: {target}")
