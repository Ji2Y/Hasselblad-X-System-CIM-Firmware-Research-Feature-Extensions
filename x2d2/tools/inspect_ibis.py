"""X2D II 1.3.16.2 IBIS 经纬度补偿通路离线审计。

只读三个锁定的原厂 ELF；不加载固件、不执行 ibistool、不访问相机。
复用 inspect_afs 导出的通用 ELF / APS2 读取器，依赖 capstone。
输出选定函数反汇编、调用和 vtable 重定位，不反推控制器补偿效果。
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct

from inspect_afs import LockedElf


HASHES = {
    'bin/camera-service': '51b9e02f8bfebf388be8dfa163c8e512bee19aeb8ae37a6712727ccc6f26a52d',
    'bin/phocus': '18277451dd784610ea67561f55db7caf10073e29ae434122172715092e6b77fb',
    'bin/ibistool': '12e33a659960db53ec54cd47784e02a750bf96f82b26c0df4df4629c65432450',
}

FUNCTIONS = {
    'bin/camera-service': (
        '_ZN16CameraObjectImpl18doSet_gps_positionERK4QMapI7QString8QVariantERK12QDBusMessage',
        '_ZN11IbisControl18setGpsCompensationEffRK14QSharedPointerI19MessageNotificationE',
        '_ZN4Ibis18setGpsCompensationEff',
        '_ZN4Ibis18getGpsCompensationEv',
        '_ZN29IbisSetGpsCompensationMessageC1Eff',
        '_ZN29IbisGetGpsCompensationMessageC1Ev',
        '_ZN18IbisResponseParser28parseGpsCompensationResponseERK14QSharedPointerI11IbisRequestERfS5_',
        '_ZN4Ibis11sendMessageENSt3__110unique_ptrI16DussEventMessageNS0_14default_deleteIS2_EEEE',
        '_ZN15IbisCtrlMessageC2ERK7QStringNS_8SubCmdIdEtb',
    ),
    'bin/phocus': (
        '_ZN15CameraProxyDbus16set_gps_positionERK4QMapI7QString8QVariantEiP7QObject',
        '_ZN15CameraProxyDbus18doSet_gps_positionERK4QMapI7QString8QVariantE',
    ),
    'bin/ibistool': (
        '_ZN25SetGpsCompensationCommand7executeERK18QCommandLineParser',
        '_ZN25GetGpsCompensationCommand7executeERK18QCommandLineParser',
        '_ZN29IbisSetGpsCompensationMessageC1Eff',
        '_ZN29IbisGetGpsCompensationMessageC1Ev',
    ),
}


def inspect(root, output):
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

    root, output = root.resolve(), output.resolve()
    if output == root or root in output.parents:
        raise ValueError('输出不能写入固件输入目录')
    report = {
        'model': 'X2D II 100C', 'firmware': '1.3.16.2',
        'verification': 'static offline only', 'device_access': False,
        'inputs': {}, 'functions': {}, 'ibis_vtable': {},
        'limits': [
            'No firmware code or ibistool command is executed.',
            'Mobile app source and IBIS controller internal formula are not decoded.',
            'Four-hour validity is documented by the official FAQ, not established by this audit.',
            'No measured stabilization performance, missing-GPS fallback or stop count is inferred.',
        ],
    }
    listings = {}
    for relative, expected in HASHES.items():
        raw = (root / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f'非锁定的二代固件输入：{relative}')

        class IbisElf(LockedElf):
            EXPECTED_SHA256 = expected

        elf = IbisElf(raw)
        symbols = {s['name']: s for s in elf.symbol_records('.symtab') if s['section']}
        names = {s['value']: s['name'] for s in symbols.values() if s['type'] == 2}
        plt = elf.named['.plt'][3]
        rela = elf.section_data(elf.named['.rela.plt'])
        if len(rela) % 24:
            raise ValueError('PLT 重定位不完整')
        for index in range(len(rela) // 24):
            _, info, _ = struct.unpack_from('<QQq', rela, index * 24)
            names[plt + 32 + index * 16] = elf.dynamic[info >> 32]['name']
        report['inputs'][relative] = {'sha256': expected, 'bytes': len(raw)}
        records, listing = {}, []
        md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
        for name in FUNCTIONS[relative]:
            symbol = symbols[name]
            start, size = symbol['value'], symbol['size']
            instructions = list(md.disasm(elf.read(start, size), start))
            if sum(item.size for item in instructions) != size:
                raise ValueError(f'未完整反汇编：{name}')
            record = {'va': hex(start), 'bytes': size, 'direct_calls': [], 'indirect_calls': []}
            listing.append(f'\n{name} @ {start:#x} ({size} bytes)')
            for instruction in instructions:
                target_name = ''
                if instruction.mnemonic in ('bl', 'b'):
                    target = int(instruction.op_str.removeprefix('#'), 16)
                    target_name = names.get(target, '')
                    if instruction.mnemonic == 'bl':
                        record['direct_calls'].append({
                            'at': hex(instruction.address), 'target': hex(target), 'name': target_name,
                        })
                elif instruction.mnemonic == 'blr':
                    record['indirect_calls'].append(hex(instruction.address))
                listing.append(f'{instruction.address:08x} {instruction.mnemonic:8s} '
                               f'{instruction.op_str} {target_name}'.rstrip())
            records[name] = record
        report['functions'][relative] = records
        listings[Path(relative).name + '-disassembly.txt'] = '\n'.join(listing) + '\n'

        if relative == 'bin/camera-service':
            vtable = symbols['_ZTV4Ibis']['value']
            for offset, name in (
                (0xe8, '_ZN4Ibis18setGpsCompensationEff'),
                (0xf0, '_ZN4Ibis18getGpsCompensationEv'),
                (0xf8, '_ZNK4Ibis13isInitializedEv'),
                (0x100, '_ZNK4Ibis8isLinkUpEv'),
            ):
                address = vtable + 16 + offset
                matches = [r for r in elf.relocations if r[0] == address]
                if len(matches) != 1:
                    raise ValueError('缺少唯一 vtable 重定位')
                _, info, addend = matches[0]
                if info != 1027 or addend != symbols[name]['value']:
                    raise ValueError('vtable 目标与锁定版本不符')
                report['ibis_vtable'][hex(offset)] = {
                    'slot_va': hex(address), 'target_va': hex(addend), 'target': name,
                    'relocation': 'R_AARCH64_RELATIVE',
                }
            setter = records[FUNCTIONS[relative][0]]
            if not any(c['at'] == '0x1f78f4' and c['target'] == '0x21bd80'
                       for c in setter['direct_calls']):
                raise ValueError('经纬度 setter 的直接调用不符')
            report['coordinate_payload_evidence'] = {
                'constructor_va': '0x2f5998',
                'latitude_store': '0x2f5a1c: stur s9, [sp, #1]',
                'longitude_store': '0x2f5a20: stur s8, [sp, #5]',
                'format': 'operation byte + two little-endian IEEE754 float32 coordinates',
                'note': 'Observed coordinate subpayload has no compass heading or expiration field.',
            }

    output.mkdir(parents=True, exist_ok=True)
    (output / 'ibis-gps-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    for name, text in listings.items():
        (output / name).write_text(text)
    count = sum(map(len, FUNCTIONS.values()))
    print(f'{len(HASHES)} locked ELF inputs; {count} functions; 4 vtable slots; offline only')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    inspect(arguments.firmware_root, arguments.output)


if __name__ == '__main__':
    main()
