"""X2D II 1.3.16.2 显示配置与 LUT 离线检查。

只读显式指定的固件输入，只写本地 JSON / 反汇编；不加载原厂代码。
依赖 capstone、已有 inspect_lidar.disassemble 和通用 LockedElf 读取器。
固件及第三方依赖未随本工具提供。rcam 排列不按 cube_r 解码。
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from inspect_lidar import LockedElf, disassemble


HASHES = {
    'lib64/weston/eagle-backend.so': '7d393c1b0cfecca355b7ca07d357003c25e16fecf8e111a1e03b311c07ab72ab',
    'etc/dispalgo/ab_evf.json': '044ee87ade81974cd98d7a94c8c039a29a9e66423b11f126ced80b2aebf4ebb4',
    'etc/dispalgo/ab_evf_pb.json': '757f47bbcdad5ca4b06b1a5e1fe4ebab6c9e23d0484564122b614b07736f4c09',
    'etc/dispalgo/ab_mp.json': 'a8a75ba7f876ac44d7573cdaa5da8a39aadccacc463027b6b00b48624147f2e1',
    'etc/dispalgo/ab_mp_pb.json': '83a3b01284e1301081092289dcb409bc6b9c0e017fdec6faa9c1c400692f8ec1',
    'etc/dispalgo/cm_evf_lv_sdr_fastpre.bin': '6c20d6358e66ec7d6298c32bb6ec0cb42412a1241e51f3d7f958a595b6be00a3',
    'etc/dispalgo/cm_evf_lv_sdr_fastpre.json': '052252d86772c42e66adfebd1676e3939bde4508b7c52bf5c1cee9178d020901',
    'etc/dispalgo/cm_evf_lv_ui.bin': 'ddbeb709eed7d47edca50ff5ac00e3f04fa50a1e56caee11386699728e789acc',
    'etc/dispalgo/cm_evf_lv_ui.json': '6426842719887df66d55e77b26f85af0c9899a4d2e5dbcd41a64336485449cb9',
    'etc/dispalgo/cm_evf_pb_fastpre.bin': '784c9de37898797c7d50cf5d9e5792617dfbe7a469891e408719c4754df1b463',
    'etc/dispalgo/cm_evf_pb_fastpre.json': '37b8c24152d6d2db562ca349a640ea32ae79a22adb4bbf6e7de5f033c26e8efa',
    'etc/dispalgo/cm_evf_pb_hdr.bin': '7ddf9d2b1233c92082cc270b14d4c50cf88e8d34ded5d7fee03810c61dcd0837',
    'etc/dispalgo/cm_evf_pb_hdr.json': '8daad1dc979da889ca40d7efe93e3acbbd97f3d2eaa79bef91a91a14175a3f2b',
    'etc/dispalgo/cm_evf_pb_hdr_thumb.bin': '6c1ffd83d415a1a82c86a30333e713057b542d1642fc6fcd80229230fdd6e82b',
    'etc/dispalgo/cm_evf_pb_hdr_thumb.json': '4f35785ea2f9191f86b5f11013af494e3cdaa08f159addee90035914a5b7478e',
    'etc/dispalgo/cm_evf_pb_sdr.bin': '0531824a4157b46bd758e38fdb2d283e94df58db8de7d184dee20fca1c03ee20',
    'etc/dispalgo/cm_evf_pb_sdr.json': 'bea8bdc1419f8b5fc285899a686b95f728baef77fc9e2174bd20932acd24f2d3',
    'etc/dispalgo/cm_evf_pb_ui.bin': 'eef527cc3efe1887bb1d5c51e639807c108cc5bb439c064e95d01bec7262e3b5',
    'etc/dispalgo/cm_evf_pb_ui.json': '80108078c3f28195cd6d0f8c10d48dae6580ffb44de8c70189ee87a443db7bf5',
    'etc/dispalgo/cm_mp_lv_sdr_fastpre.bin': 'a5e25c10f8ec066adca7ad08a4e2e870c08ab9688745666ec5ba02d2eb5c2bf1',
    'etc/dispalgo/cm_mp_lv_sdr_fastpre.json': '8a4381dab9510d56d6b8c3072fb6c560faf8dd79142d9d93ff946edc7ff9f1b1',
    'etc/dispalgo/cm_mp_lv_ui.bin': '564b7634e6f8dc512a037e7574ae6b1bd60eaa007ee531bded999ba19314b5ad',
    'etc/dispalgo/cm_mp_lv_ui.json': '4ba707807dc68ba89bb4fbf2525d776d6b318b0b3a6ad8545b447b99016fc3f9',
    'etc/dispalgo/cm_mp_pb_fastpre.bin': 'e2f6e266b4bb8e3bc3e70f69d40c39e9b0a76d4c7a219564b4f4b4282ea0cdf5',
    'etc/dispalgo/cm_mp_pb_fastpre.json': '3c193b01b1aa61c797632c70366e4441a66b46df9bac0fe72cbf2bbddc75adfa',
    'etc/dispalgo/cm_mp_pb_hdr.bin': 'ed2c7a876eb060e2179ee596fedd9e9dc6c5779b095079c436164455196a38d0',
    'etc/dispalgo/cm_mp_pb_hdr.json': '3c8a78fe6fae3e1a30f7a4ca12d0ff0557be7724137f4505e223732b943ebcd4',
    'etc/dispalgo/cm_mp_pb_hdr_thumb.bin': 'bb44bcba60a7e2660efb63a5cfb23ea22f5ad7da67014f291871bbb6b002d5b8',
    'etc/dispalgo/cm_mp_pb_hdr_thumb.json': 'b8dcf9ea4e2bf5ee1b703249d092d5a67f04bbc75c2be0e5503b07e7a67307ad',
    'etc/dispalgo/cm_mp_pb_sdr.bin': '197817efae19968d67e8b875cd4a78aafbd28bd59b55d988bb3c8d2f01268a94',
    'etc/dispalgo/cm_mp_pb_sdr.json': 'a3a92a814a3bd603b5037be83d8f624ece13ee8889f00582bd7b89de8df0c35f',
    'etc/dispalgo/cm_mp_pb_ui.bin': '2e8a3fd4fcb9dfe980ad85ce5223a248f3cc98273e3b481f6ea73f999e815fd6',
    'etc/dispalgo/cm_mp_pb_ui.json': '2db0cd8a12c5241ad263c0e9eb85c05ea1bbb291804e1133aa778622dc12d06f',
}

FUNCTIONS = (
    '_Z15initDispAlgoVopP8EagleVop',
    '_ZN21DispAlgoAutoBacklight14lazyLoadParamsEv',
    '_ZN21DispAlgoAutoBacklight9calculateEP15_dss10_iq_reg_t',
    '_Z28dss10_bright_control_algo_swP15_dss10_iq_reg_tP30_dss10_bright_control_result_s',
    '_ZN21DispAlgoAutoBacklight6updateEv',
    '_ZN11DispAlgoHal22setPanelHighBrightnessEabt',
    '_ZN23DispAlgoColorMgmtInterp10initParamsEv',
    '_ZN23DispAlgoColorMgmtInterp12parseLutFileEv',
    '_ZN23DispAlgoColorMgmtInterp16getLutsForInterpEd',
    '_ZN23DispAlgoColorMgmtInterp11workingLoopEv',
    '_ZN23DispAlgoColorMgmtInterp19updateDisplayStatusE18dispAlgoStatusItemPv',
    '_ZN20DispAlgoLutProcessor17interpolateLinearER11DispAlgoLutS1_S1_d',
    '_ZN20DispAlgoLutProcessor17calculateLutBytesERK15DispAlgoLutType',
    '_ZNK11DispAlgoLut4getFEiiiPfS0_S0_',
    '_ZN11DispAlgoHal12setRcamTdLutEaPvma',
    '_ZN13EagleVopPlane8set3dLutEPvi',
    '_ZN11EagleOutput16updateBrightnessEib',
)


def compact(value):
    if isinstance(value, dict):
        return {key: compact(item) for key, item in value.items()}
    if isinstance(value, list):
        if len(value) > 12:
            return {'count': len(value), 'first': value[:5], 'last': value[-5:]}
        return [compact(item) for item in value]
    return value


def inspect(root, output):
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

    root, output = root.resolve(), output.resolve()
    if output == root or root in output.parents:
        raise ValueError('输出不能写入固件输入目录')
    inputs = {name: (root / name).read_bytes() for name in HASHES}
    for name, raw in inputs.items():
        if hashlib.sha256(raw).hexdigest() != HASHES[name]:
            raise ValueError(f'非锁定的二代 1.3.16.2 输入：{name}')

    class DisplayElf(LockedElf):
        EXPECTED_SHA256 = HASHES['lib64/weston/eagle-backend.so']

    elf = DisplayElf(inputs['lib64/weston/eagle-backend.so'])
    report = {
        'model': 'X2D II 100C', 'firmware': '1.3.16.2',
        'verification': 'static / offline only', 'device_access': False,
        'inputs': {name: {'sha256': HASHES[name], 'bytes': len(raw)}
                   for name, raw in inputs.items()},
        'brightness_configs': {}, 'color_configs': {},
        'limits': [
            'Configuration values are not measured panel luminance or menu slider positions.',
            'Runtime overrides, driver internals and panel NVM were not read.',
            'Neutral cube nodes are raw code values, not measured emitted color.',
            'No physical gray-level input spacing is inferred for width 28.',
            'No rcam layout decoding, camera connection or firmware modification.',
        ],
    }
    for name, raw in inputs.items():
        if not name.endswith('.json'):
            continue
        config = json.loads(raw)
        if Path(name).name.startswith('ab_'):
            report['brightness_configs'][name] = compact(config)
            continue
        width, channels = config['lut_width'], config['lut_channels']
        if config['lut_data_type'] != 'int' or channels != 3:
            raise ValueError('未支持的 LUT 类型')
        byte_depth = (config['lut_bit_depth'] + 7) // 8
        table_bytes = width ** 3 * channels * byte_depth
        lut_path = config['lut_file'].lstrip('/')
        lut = inputs[lut_path]
        if byte_depth != 2 or len(lut) != table_bytes * config['param_count']:
            raise ValueError('LUT 长度或存储宽度不匹配')
        if len(config['param_list']) != config['param_count']:
            raise ValueError('锚点数不匹配')
        item = {'config': config, 'table_bytes': table_bytes, 'tables': []}
        for index, anchor in enumerate(config['param_list']):
            block = lut[index * table_bytes:(index + 1) * table_bytes]
            record = {'anchor': anchor, 'sha256': hashlib.sha256(block).hexdigest()}
            values = struct.unpack('<' + str(len(block) // 2) + 'H', block)
            record['stored_range'] = [min(values), max(values)]
            if max(values) >= 1 << config['lut_bit_depth']:
                raise ValueError('LUT 码值超出声明位宽')
            if config['lut_format'] == 'cube_r':
                record['neutral_nodes'] = [
                    {'index': k, 'rgb': struct.unpack_from(
                        '<3H', block, k * (width * width + width + 1) * 6)}
                    for k in range(width)
                ]
                if record['neutral_nodes'][0]['rgb'] != (0, 0, 0):
                    raise ValueError('黑节点与本轮证据不符')
            item['tables'].append(record)
        report['color_configs'][name] = item

    rodata = elf.section_data(elf.named['.rodata'])
    report['backend_rodata_mura_strings'] = [m.group().decode() for m in
        re.finditer(rb'[ -~]{4,}', rodata) if re.search(rb'mura', m.group(), re.I)]
    report['functions'], listing = disassemble(elf, FUNCTIONS, Cs(CS_ARCH_ARM64, CS_MODE_ARM))
    ui = report['color_configs']['etc/dispalgo/cm_mp_lv_ui.json']['tables']
    report['rear_lv_ui_duplicate_anchors'] = [
        [item['anchor'] for item in ui if item['sha256'] == sha]
        for sha in dict.fromkeys(item['sha256'] for item in ui)
    ]
    if report['rear_lv_ui_duplicate_anchors'] != [[30, 180, 327], [591, 800, 1000]]:
        raise ValueError('UI 表重复分组与锁定版本证据不符')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'display-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (output / 'display-disassembly.txt').write_text('\n'.join(listing) + '\n')
    print(f'{len(HASHES)} locked inputs, {len(FUNCTIONS)} functions, '
          f'{len(report["color_configs"])} LUT banks; offline only')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    inspect(args.firmware_root, args.output)


if __name__ == '__main__':
    main()
