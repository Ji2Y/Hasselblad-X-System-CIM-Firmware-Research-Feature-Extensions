"""X2D II 1.3.16.2 LiDAR 离线检查：只读固件，写本地分析产物。

依赖本目录 inspect_afs 的版本锁定 ELF/APS2 读取器及 capstone。
不加载固件动态库，不连接设备，不执行原厂测试脚本。
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from inspect_afs import AAA_SHA256, CONFIG_SHA256, LockedElf, audit


FUNCTIONS = (
    "_cteate_tof_lib_impl", "tof_lib_init", "tof_lib_run",
    "tof_dtof_ads6401_init", "tof_dtof_ads6401_statistics",
    "tof_dtof_ads6401_get_stat_cfg", "tof_dtof_ads6401_run",
    "tof_dtof_ads6401_set_lens_prams_impl",
    "tof_dtof_ads6401_set_intri_impl", "tof_dtof_ads6401_set_extri_impl",
    "process_tof_AB_frame", "_tof_roi_blend_list", "_tof_blend",
    "tof_distance_stable", "lens_ctrl_get_tof_lens_cfg_params",
    "lens_ctrl_get_lens_pos_by_dist_lut", "get_pos_by_dis_calib",
    "get_pos_by_dis_calib_fl", "afc_ctrl_save_peak_info",
    "afc_ctrl_process", "afc_fusion_ctrl_get_status",
    "af_hybrid_hasselblad_policy_stage_start",
    "af_hybrid_hasselblad_policy_stage_dir",
    "af_hybrid_hasselblad_policy_stage_peak",
    "af_hybrid_hasselblad_policy_stage_check_peak",
    "af_hybrid_hasselblad_policy_stage_goto_peak",
    "cdaf_scene_get_afc_score",
)

INPUTS = (
    "lib64/libaaa.so", "etc/aaa/af/af_imx861.json",
    "etc/aaa/af/af_ads6401.json", "etc/aaa/af_config.fbs",
    "etc/ads6401_hb722.conf", "etc/ads6401_hb722.sp",
    "lib64/camera/plugins/stream_filter/libdcam_x2dii_tof_stream_filter.so",
    "lib/modules/ads6401.ko",
    "lib64/libadaps_swift_decode.so",
    "etc/aaa/af_imx861.bin",
)

STREAM_SHA256 = "48b0855a124b507e429895b075aee6f03b6dca845b52aa1eef414ca504328162"
DECODE_SHA256 = "722984dbfe44ccb154435204b612d1ac5bbd3acbb6644975a0c3ab463836a94c"
SCHEMA_SHA256 = "9bff81b307d6d914be733dca96acaa2384b3c0a5f2a7d69a6c513f2994d2ec4a"
BINARY_CONFIG_SHA256 = "3fbf41bd21bbb115c0f5ac5594e22acfc0be46e3ecaf4f168d7111d8a489f9e4"
STREAM_FUNCTIONS = (
    "_ZN20X2DIITofStreamFilter8onBufferEP16cam_frame_buffer",
    "_ZN20X2DIITofStreamFilter16depthWrapperInitEPv",
    "_ZN20X2DIITofStreamFilter14sendDataToRcamERK26_af_tof_spot_input_data_s_RK8FocusRoi",
)
DECODE_FUNCTIONS = (
    "DepthMapWrapperProcessFrame",
    "_ZN15DepthMapWrapper12processFrameE17WrapperDepthInputP21WrapperDepthCamConfigjP18WrapperDepthOutput",
    "_ZN15DepthMapWrapper16DecodeAndComposeE9FrameModeR17WrapperDepthInputR18WrapperDepthOutput36AdapsParamAndOutForProcessEveryFrame",
)

CONFIG_RANGES = ((18, 49), (102, 164), (1342, 1410), (1441, 1472),
                 (1550, 1641), (1662, 1678), (1844, 1858), (1903, 1933))
LOG_CALLS = {
    "log_mgr_check", "co_thread_get", "co_thread_get_current_co_name_co_id",
    "duss_log_gen_head", "duss_log_print", "log_to_kmsg",
    "duss_log_dump_backtrace", "is_running_in_cam_sil", "fflush", "abort",
    "exit", "__stack_chk_fail", "flow_trace_instance", "flow_trace_init",
    "PerfettoTeHlEmitImpl", "flow_trace_get_process_scoped_flow",
}


def compiled_config(raw, schema):
    """只读取锁定 schema 的选定 FlatBuffers 表、标量和 uint8 / uint32 向量。"""
    if hashlib.sha256(raw).hexdigest() != BINARY_CONFIG_SHA256:
        raise ValueError("二代二进制 AF 配置版本不匹配")
    if hashlib.sha256(schema).hexdigest() != SCHEMA_SHA256:
        raise ValueError("二代 AF schema 版本不匹配")
    text = schema.decode()
    unions = set(re.findall(r"union\s+(\w+)", text))
    formats = {"uint8": "B", "int8": "b", "byte": "b", "uint16": "H",
               "uint32": "I", "int32": "i", "float": "f", "double": "d"}

    def unpack(fmt, offset):
        return struct.unpack_from("<" + fmt, raw, offset)[0]

    def field(position, table, key):
        body = re.search(r"table\s+" + table + r"\s*\{([^}]+)\}", text).group(1)
        fields = []
        for name, kind in re.findall(r"(\w+)\s*:\s*([\w\[\]]+)\s*;", body):
            # FlatBuffers union 字段在二进制中占 type / object 两个槽位。
            if kind in unions:
                fields.append((name + "_type", "uint8"))
            fields.append((name, kind))
        index = next(i for i, item in enumerate(fields) if item[0] == key)
        vtable = position - unpack("i", position)
        entry = 4 + 2 * index
        offset = unpack("H", vtable + entry) if entry < unpack("H", vtable) else 0
        return (position + offset if offset else None), fields[index][1]

    def table(position, kind, key):
        address, child_kind = field(position, kind, key)
        if address is None:
            raise ValueError(f"缺少配置表 {kind}.{key}")
        return address + unpack("I", address), child_kind

    def value(position, kind, key):
        address, field_kind = field(position, kind, key)
        # 本轮选择的标量字段均无显式 schema 默认值，缺省为 0。
        if address is None:
            return 0
        if field_kind in ("[uint8]", "[uint32]"):
            address += unpack("I", address)
            length = unpack("I", address)
            fmt = formats[field_kind[1:-1]]
            return list(struct.unpack_from("<" + str(length) + fmt, raw, address + 4))
        enum = re.search(r"enum\s+" + field_kind + r"\s*:\s*(\w+)", text)
        if enum:
            field_kind = enum.group(1)
        return unpack(formats[field_kind], address)

    def union_table(position, kind, key, expected_kind):
        if value(position, kind, key + "_type") != 1:
            raise ValueError(f"本轮仅支持 {key} 的配置表形式")
        address, _ = table(position, kind, key)
        return address, expected_kind

    root = unpack("I", 0)
    global_params = table(root, "af_params_s", "global")
    algorithms = union_table(*global_params, "af_alg_cfg", "af_alg_cfg_u_d_t")
    features = union_table(*global_params, "af_feature_cfg", "af_feature_cfg_u_d_t")
    tof = table(root, "af_params_s", "tof")
    afc = table(root, "af_params_s", "afc")
    control = table(*afc, "afc_ctrl")
    fusion = table(*control, "fusion_ctrl")
    confidence = table(*tof, "output_confidence")
    pdaf = table(root, "af_params_s", "pdaf")
    pdaf_confidence = table(*pdaf, "output_confidence")
    cdaf = table(root, "af_params_s", "cdaf")
    cdaf_confidence = table(*cdaf, "confidence")
    hybrid = table(root, "af_params_s", "hybrid")
    policy = table(*hybrid, "policy")
    find_dir = table(*policy, "find_dir")
    find_peak = table(*policy, "find_peak")
    goto = table(*policy, "goto_peak")
    refine = union_table(*goto, "enable_alg_mask", "af_alg_cfg_u_d_t")
    mf = table(root, "af_params_s", "mf")
    mf_assistant = union_table(*mf, "mf_assistant", "mf_assist_type_u_cfg_t")
    mf_assist_param = table(*mf, "mf_assist_param")
    result = {
        "global_algorithms": {key: value(*algorithms, key) for key in
                              ("cdaf", "pdaf", "bdaf", "vdaf", "ldaf", "tof")},
        "global_features": {key: value(*features, key) for key in
                            ("af", "afc", "mf", "dmf", "zoom", "dzoom", "zoom_tracking_af", "ir_cut", "aft")},
        "afc_sources": {key: value(*table(*afc, key), "enable") for key in
                        ("cdaf", "pd", "vision", "laser", "bdaf", "tof")},
        "afs_goto_refine": {
            "support_refine_peak": value(*goto, "support_refine_peak"),
            "enabled_algorithms": {key: value(*refine, key) for key in
                                   ("cdaf", "pdaf", "bdaf", "vdaf", "ldaf", "tof")},
        },
        "mf_assistant": {
            "enable": value(*mf_assist_param, "enable"),
            "algorithms": {key: value(*mf_assistant, key) for key in ("bdaf", "tof", "pdaf")},
        },
        "tof": {key: value(*tof, key) for key in (
            "tof_type", "enable_tof_tracking", "mode", "roi_refine", "blend_domain",
            "temporal_filter_type", "mesh_max_row", "mesh_max_col", "invalid_distance",
            "update_timeout_cnt", "near_distance", "stillmode_afs_focus_max_rlt",
        )},
        "afc_ctrl_alg_cfg": value(*control, "afc_ctrl_alg_cfg"),
        "afc_admission": {key: value(*control, key) for key in
                          ("peak_conf_th", "peak_super_conf_th")},
        "afs_admission": {
            "find_dir": {key: value(*find_dir, key) for key in
                         ("get_peak_min_conf", "get_peak_range_min_conf", "confirm_dir_conf")},
            "find_peak": {key: value(*find_peak, key) for key in
                          ("confirm_guess_peak_conf", "confirm_peak_conf")},
        },
        "fusion": {key: value(*fusion, key) for key in (
            "fusion_enable", "master_algo_type", "slave_algo_type", "backup_algo_type",
            "enter_lv_thresh", "fusion_pos_diff_threshold", "fusion_tracking_length",
            "fusion_tracking_valid_cnt_th", "fusion_tracking_keep_cnt_th", "fusion_tracking_std_th",
        )},
        "tof_confidence": {key: value(*confidence, key) for key in (
            "rlt_ok_peak_confidence", "rlt_super_ok_peak_confidence",
            "rlt_ok_dir_confidence", "rlt_super_ok_dir_confidence",
            "rlt_ok_peak_range_confidence", "rlt_super_ok_peak_range_confidence",
        )},
        "pdaf_confidence": {key: value(*pdaf_confidence, key) for key in (
            "rlt_ok_peak_confidence", "rlt_super_ok_peak_confidence",
            "rlt_ok_dir_confidence", "rlt_super_ok_dir_confidence",
            "rlt_ok_peak_range_confidence", "rlt_super_ok_peak_range_confidence",
        )},
        "cdaf_confidence": {key: value(*cdaf_confidence, key) for key in (
            "focus_success_peak_conf", "focus_failed_peak_conf", "full_scan_dir_conf",
        )},
        "mf_pdaf_admission": {key: value(*mf_assist_param, key) for key in (
            "mfa_v2_pdaf_confi_limit_to_peak_confirm",
            "mfa_v2_pdaf_confi_limit_to_range_confirm", "mfa_v2_pdaf_confi_limit_to_idle",
        )},
    }
    if result["afc_ctrl_alg_cfg"] != [1, 0, 0, 1] or result["tof"]["tof_type"] != 4:
        raise ValueError("二进制算法选择与本轮证据不匹配")
    return result


def disassemble(elf, functions, md):
    symbols = {s["name"]: s for s in elf.dynamic if s["section"] and s["type"] == 2}
    names = {s["value"]: s["name"] for s in elf.dynamic if s["section"]}
    plt = elf.named[".plt"][3]
    raw = elf.section_data(elf.named[".rela.plt"])
    if len(raw) % 24:
        raise ValueError("不完整的 PLT 重定位")
    for i in range(len(raw) // 24):
        _, info, _ = struct.unpack_from("<QQq", raw, i * 24)
        names[plt + 32 + 16 * i] = elf.dynamic[info >> 32]["name"]

    records, listing = {}, []
    for name in functions:
        s = symbols[name]
        record = {"va": hex(s["value"]), "bytes": s["size"], "direct_calls": []}
        listing.append(f"\n{name} @ {s['value']:#x}, {s['size']} bytes")
        instructions = list(md.disasm(elf.read(s["value"], s["size"]), s["value"]))
        if sum(i.size for i in instructions) != s["size"]:
            raise ValueError(f"未完整反汇编 {name}")
        for ins in instructions:
            target_name = ""
            if ins.mnemonic in ("bl", "b"):
                target = int(ins.op_str.removeprefix("#"), 16)
                target_name = names.get(target, "")
                if ins.mnemonic == "bl":
                    record["direct_calls"].append({
                        "at": hex(ins.address), "target": hex(target), "name": target_name,
                    })
            listing.append(f"{ins.address:08x}  {ins.mnemonic:8s} {ins.op_str} {target_name}".rstrip())
        record["substantive_calls"] = [c for c in record["direct_calls"] if c["name"] not in LOG_CALLS]
        records[name] = record
    return records, listing


def inspect(root, output):
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

    root, output = root.resolve(), output.resolve()
    if output == root or root in output.parents:
        raise ValueError("分析输出不能位于输入固件目录内")
    inputs = {name: (root / name).read_bytes() for name in INPUTS}
    baseline = audit(inputs[INPUTS[0]], inputs[INPUTS[1]])

    class X2D2Elf(LockedElf):
        EXPECTED_SHA256 = AAA_SHA256

    class StreamElf(LockedElf):
        EXPECTED_SHA256 = STREAM_SHA256

    class DecodeElf(LockedElf):
        EXPECTED_SHA256 = DECODE_SHA256

    elf = X2D2Elf(inputs[INPUTS[0]])
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    report = {
        "model": "X2D II 100C", "firmware": "1.3.16.2",
        "verification": "static offline only", "device_access": False,
        "inputs": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                   for name, data in inputs.items()},
        "baseline": {key: baseline[key] for key in
                     ("instruction_count", "policy_callback_count", "result_jump_table_count")},
        "functions": {}, "dispatch_tables": {},
        "limits": [
            "Direct calls do not establish every indirect call or executed runtime path.",
            "Configuration text is hash-locked; runtime overrides were not read.",
            "Raw 225/900 point statistics, mesh capacity and PDAF areas are different quantities.",
            "No occlusion, glass, sharpness, range or timing experiment was performed.",
        ],
    }
    report["functions"], listing = disassemble(elf, FUNCTIONS, md)
    report["stream_functions"], stream_listing = disassemble(StreamElf(inputs[INPUTS[6]]), STREAM_FUNCTIONS, md)
    report["decode_functions"], decode_listing = disassemble(DecodeElf(inputs[INPUTS[8]]), DECODE_FUNCTIONS, md)
    report["compiled_configuration"] = compiled_config(inputs[INPUTS[9]], inputs[INPUTS[3]])

    for name, base, count in (("tof_init", 0x6cb288, 5), ("tof_run", 0x6cb2d8, 5),
                             ("tof_result", 0x6d223c, 4)):
        report["dispatch_tables"][name] = {
            "va": hex(base),
            "destinations": [hex(base + delta) for delta in
                             struct.unpack("<" + "i" * count, elf.read(base, 4 * count))],
        }
    config_lines = inputs[INPUTS[1]].decode().splitlines()
    excerpt = []
    for start, end in CONFIG_RANGES:
        excerpt.extend(f"{i}: {config_lines[i - 1]}" for i in range(start, end + 1))
    report["configuration_sha256"] = CONFIG_SHA256
    output.mkdir(parents=True, exist_ok=True)
    (output / "lidar-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (output / "lidar-disassembly.txt").write_text("\n".join(listing) + "\n")
    (output / "stream-filter-disassembly.txt").write_text("\n".join(stream_listing) + "\n")
    (output / "decode-disassembly.txt").write_text("\n".join(decode_listing) + "\n")
    (output / "configuration-excerpts.txt").write_text("\n".join(excerpt) + "\n")
    count = len(FUNCTIONS) + len(STREAM_FUNCTIONS) + len(DECODE_FUNCTIONS)
    print(f"{count} functions inspected; {baseline['instruction_count']} baseline instructions checked; offline only")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inspect(args.firmware_root, args.output)


if __name__ == "__main__":
    main()
