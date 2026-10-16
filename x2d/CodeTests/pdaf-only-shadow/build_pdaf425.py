"""离线生成 X2D 4.2.0 / 425 区域测量候选，不访问相机。"""
import argparse
import hashlib
import io
import json
import shutil
import subprocess
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from elftools.elf.elffile import ELFFile

HERE = Path(__file__).resolve().parent
STOCK_SHA = "feef8a8dc3a27395e47232c2b25a5da7a7ab335922fbb527e637c439e35bcec7"
FUNCTIONS = (
    "pdaf_type3_stats_lib_create", "pdaf_type3_stats_lib_calc",
    "pdaf_type3_stats_lib_get_results", "calculate_pdaf_stat",
    "extract_pdaf_pixels", "process_configuration", "get_sensor_specifics",
    "set_sensor_specifics",
)


def build(root, output, cc):
    root=root.resolve()
    output=output.resolve()
    if output==root or root in output.parents:
        raise ValueError("输出不能写入固件输入树")
    if output.exists():
        raise ValueError("输出目录必须尚不存在，避免覆盖原始证据")
    data = (root / "lib64/libaaa.so").read_bytes()
    if hashlib.sha256(data).hexdigest() != STOCK_SHA:
        raise ValueError("仅接受第一代 X2D 4.2.0 原厂 libaaa.so")
    elf = ELFFile(io.BytesIO(data))
    if elf["e_machine"] != "EM_AARCH64":
        raise ValueError("固件架构不匹配")
    symbols = {s.name: s for s in elf.get_section_by_name(".dynsym").iter_symbols()}

    def read(va, size):
        for seg in elf.iter_segments():
            if seg["p_type"] == "PT_LOAD" and seg["p_vaddr"] <= va and va+size <= seg["p_vaddr"]+seg["p_filesz"]:
                offset=seg["p_offset"]+va-seg["p_vaddr"]
                return data[offset:offset+size]
        raise ValueError("ELF 读取越界")

    # Bind packing, single-ROI restriction, source-plane read, and output ABI.
    checks = {
        0xd93f4: ("ldr", "x23, [x9, w0, sxtw #3]"),
        0xd9544: ("madd", "x13, x24, x10, x23"),
        0xd9564: ("str", "w14, [x13, #8]"),
        0xd956c: ("str", "w14, [x13, #0x30]"),
        0xcbe48: ("cmp", "w8, #2"),
        0xcbe4c: ("b.lt", "#0xcbf2c"),
        0xcae14: ("ldr", "x5, [x1]"),
        0xd9a48: ("stur", "w8, [x27, #-4]"),
        0xd9a50: ("str", "w8, [x27]"),
        0xd9a60: ("strb", "w8, [x27, #8]"),
        0xd9b34: ("strb", "w10, [x19, #0x6fd]"),
    }
    md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
    for va, expected in checks.items():
        ins=next(md.disasm(read(va,4),va))
        if (ins.mnemonic,ins.op_str)!=expected:
            raise ValueError("指令锚点不匹配: "+hex(va))
    output.mkdir(parents=True,exist_ok=False)
    header=["/* 自动生成：仅用于版本绑定，不随共享源码交付。 */",
            "struct p425_guard { unsigned long long va; unsigned int size; const unsigned char *bytes; };"]
    records=[]
    for i,name in enumerate(FUNCTIONS):
        s=symbols[name]; raw=read(s["st_value"],s["st_size"])
        header.append("static const unsigned char guard_%d[]={%s};" % (i,",".join(str(b) for b in raw)))
        records.append({"name":name,"va":s["st_value"],"size":len(raw),"sha256":hashlib.sha256(raw).hexdigest()})
    # Also bind all three sampling descriptors used by the planner.
    raw=read(0x1b2a08,252)
    header.append("static const unsigned char guard_geometry[]={%s};" % ",".join(str(b) for b in raw))
    header.append("static const struct p425_guard p425_guards[]={")
    header += ["{%d,%d,guard_%d}," % (r["va"],r["size"],i) for i,r in enumerate(records)]
    header += ["{0x1b2a08,252,guard_geometry},", "};",
               "#define P425_GUARD_COUNT 9u", "#define P425_CALC_VA 0xd93c0u",
               "#define P425_CONTEXT_SLOT 0xa6b5e8u"]
    (output/"pdaf425_guards.h").write_text("\n".join(header)+"\n")
    compiler=shutil.which(cc)
    if not compiler:
        raise ValueError("缺少 clang")
    imports=set(); libraries=[]
    for name in ("libc.so","libdl.so"):
        libdata=(root/"lib64"/name).read_bytes()
        target=output/name; target.write_bytes(libdata); libraries.append(str(target))
        libelf=ELFFile(io.BytesIO(libdata))
        imports.update(s.name for s in libelf.get_section_by_name(".dynsym").iter_symbols() if s["st_shndx"]!="SHN_UNDEF")
    target=output/"libx2d_pdaf425_measure.so"
    subprocess.run([compiler,"--target=aarch64-linux-gnu","-fuse-ld=lld","-O2","-g0",
                    "-shared","-fPIC","-nostdlib","-fno-builtin","-fno-stack-protector",
                    "-mno-outline-atomics","-Wall","-Wextra","-Werror","-I"+str(output),
                    "-Wl,--no-undefined","-Wl,-z,noexecstack","-Wl,-z,relro","-Wl,-z,now",
                    str(HERE/"pdaf425_core.c"),str(HERE/"pdaf425_capture.c"),
                    str(HERE/"pdaf425_stream_adapter.c"),str(HERE/"pdaf425_native.c"),*libraries,
                    "-o",str(target)],check=True)
    outdata=target.read_bytes(); outelf=ELFFile(io.BytesIO(outdata))
    undefined={s.name for s in outelf.get_section_by_name(".dynsym").iter_symbols() if s.name and s["st_shndx"]=="SHN_UNDEF"}
    if outelf["e_machine"]!="EM_AARCH64" or undefined-imports:
        raise ValueError("目标 ELF / 导入不匹配")
    if any((s["p_flags"]&3)==3 for s in outelf.iter_segments()):
        raise ValueError("存在 RWX 区域")
    report={"model":"X2D 100C first generation","firmware":"4.2.0","libaaa_sha256":STOCK_SHA,
            "candidate_sha256":hashlib.sha256(outdata).hexdigest(),"guards":records,
            "zone_count":425,"grid":[25,17],"calls_per_frame":425,"imports":sorted(undefined),
            "compiled":True,"device_tested":False,"phase_row_snapshot_copier":True,
            "producer_adapter_core":True,"producer_callback_registered":False,"producer_capture_adapter":False,
            "active_autofocus_consumer":False,"installable":False,
            "status":"独立进程测量核心；未接入相机帧生产端或镜头控制，不是425点对焦升级安装包"}
    (output/"pdaf425-build.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"compiled":True,"bytes":len(outdata),"zone_count":425,"device_tested":False,"installable":False}))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--system-root",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--cc",default="clang")
    args=p.parse_args(); build(args.system_root,args.output,args.cc)
