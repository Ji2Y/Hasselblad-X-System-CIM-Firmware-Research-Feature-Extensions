"""X2D II 1.3.16.2 产品标识与开机资源离线检查。

读取显式指定的原厂 system/vendor 解包树和 exMCU 文件，写本地报告与 PNG。
依赖 pyelftools 及一代目录的通用 Qt RCC 读取器；不使用一代固件地址。
不运行固件，不访问相机，不修改固件输入或设备身份。
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "x2d/tools/firmware-analysis"))
from qt_rcc_resources import resources
from elftools.elf.elffile import ELFFile


HASHES = {
    "backend": "7d393c1b0cfecca355b7ca07d357003c25e16fecf8e111a1e03b311c07ab72ab",
    "gui": "b1b643cb36176cd5a49129dd9bb2be480aa045a96ed1c35c30a779ab5af0801b",
    "system": "a7554605d7d9bcde6e87a050522a4f154eaa056bbe4abc4545a8df9cd1022039",
    "prodconfig": "c2b6e86122cc6286dd998b46638b3063bea30d8c85ede83182cd4cd072a217a0",
    "logo": "03fe95b65e39db203061b8f9d367a6f184d8c71bd9f5c7dd67b27ce0b1105576",
    "mcu": "3e23ad78b1b5cef9321f8f02aac272e740164b7f49bd1d4c7f5b37e1978db1af",
}


def read_va(elf, address, size):
    for seg in elf.iter_segments():
        if seg["p_type"] == "PT_LOAD" and seg["p_vaddr"] <= address and address + size <= seg["p_vaddr"] + seg["p_filesz"]:
            offset = address - seg["p_vaddr"]
            return seg.data()[offset:offset + size]
    raise ValueError("ELF 地址不在文件载荷范围内")


def version_enums(elf):
    words = struct.unpack("<75I", read_va(elf, 0x457870, 300))
    strings_raw = read_va(elf, 0x457ad8, 608)
    count = struct.unpack_from("<I", strings_raw)[0] // 8
    strings = []
    for i in range(count):
        offset, length = struct.unpack_from("<II", strings_raw, i * 8)
        strings.append(strings_raw[offset:offset + length].decode())
    if words[0] != 12 or words[8:10] != (2, 14):
        raise ValueError("Qt Version 元数据布局不匹配")
    result = {}
    for i in range(words[8]):
        name, _, _, length, offset = words[words[9] + i * 5:words[9] + i * 5 + 5]
        result[strings[name]] = {strings[words[offset + j * 2]]: words[offset + j * 2 + 1]
                                 for j in range(length)}
    if result["ProductID"].get("X2DM2") != 6:
        raise ValueError("二代产品枚举不匹配")
    return result


def logo_preview(raw):
    header, payload = raw.split(b";", 1)
    match = re.fullmatch(rb"width:(\d+) height:(\d+) offset-x:(\d+) offset-y:(\d+) format:(\d+)", header)
    if not match:
        raise ValueError("Logo 头格式不匹配")
    width, height, x, y, kind = map(int, match.groups())
    if (width, height, x, y, kind) != (1024, 768, 0, 0, 2) or len(payload) != width * height * 3 // 2:
        raise ValueError("Logo 几何或载荷不匹配")
    luma = payload[:width * height]
    chroma = payload[width * height:]
    if set(chroma) != {128} or (min(luma), max(luma)) != (16, 235):
        raise ValueError("本工具的灰度预览仅支持此中性色度 Logo")
    # 亮度 16...235 映射到显示灰度 0...255，保持原始几何。
    gray = bytes(round((value - 16) * 255 / 219) for value in luma)
    rows = b"".join(b"\0" + gray[row * width:(row + 1) * width] for row in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")
    return png, {"header": header.decode(), "width": width, "height": height,
                 "payload_bytes": len(payload), "luma_range": [16, 235], "chroma_value": 128,
                 "preview_file": "logo-luma-preview.png", "preview_sha256": hashlib.sha256(png).hexdigest()}


def inspect(system, vendor, mcu, output):
    output = output.resolve()
    for source in (system.resolve(), vendor.resolve()):
        if output == source or source in output.parents:
            raise ValueError("输出不得写入原厂输入目录")
    paths = {"backend": system / "lib64/weston/eagle-backend.so",
             "gui": system / "bin/camera-gui", "system": system / "bin/camera-system",
             "prodconfig": system / "bin/prodconfig-tool", "logo": vendor / "logo.bin", "mcu": mcu}
    raw = {key: path.read_bytes() for key, path in paths.items()}
    actual = {key: hashlib.sha256(data).hexdigest() for key, data in raw.items()}
    if actual != HASHES:
        raise ValueError("输入不是本轮锁定的 X2D II 1.3.16.2 文件")
    with paths["system"].open("rb") as handle:
        enums = version_enums(ELFFile(handle))
    with paths["gui"].open("rb") as handle:
        items = list(resources(ELFFile(handle)))
    if len(items) != 1112 or any(item["content"] is None for item in items):
        raise ValueError("GUI 资源清单未完整解析")
    png, logo = logo_preview(raw["logo"])
    pattern = re.compile(r"logo|startup|splash|earth|explorer|moon|variant|boot", re.I)
    mcu_paths = [m.group().decode() for m in re.finditer(rb"qrc:/[^\x00\r\n]{1,160}", raw["mcu"])]
    report = {
        "model": "X2D II 100C", "firmware": "1.3.16.2",
        "verification": "static offline only", "device_access": False,
        "input_sha256": actual, "logo": logo,
        "version_enums": enums,
        "x2d2_hardware_ids": {name: value for name, value in enums["HardwareID"].items()
                               if name.startswith("Hardware_X2DM2")},
        "gui_resource_count": len(items),
        "gui_image_resource_count": sum(bool(re.search(r"\.(png|jpg|jpeg|bmp|svg|webp)$", item["path"], re.I)) for item in items),
        "gui_brand_startup_named_resources": [item["path"] for item in items if pattern.search(item["path"])],
        "mcu_qrc_path_count": len(mcu_paths),
        "mcu_brand_startup_named_resources": [path for path in mcu_paths if pattern.search(path)],
        "identity_tokens": {}, "filesystem_inventory": {},
        "limitations": [
            "Hardware revisions are not evidence of retail special editions.",
            "ShellColor is a byte field; supported color values and branding mapping were not established.",
            "The presence of logo.bin does not by itself establish its complete boot loading path.",
            "No encrypted bootarea/normal payload or every unnamed MCU image was decoded.",
            "Absence of named variant resources does not prove no future or separate firmware has them.",
        ],
    }
    for key in ("backend", "system", "prodconfig", "gui"):
        report["identity_tokens"][key] = {}
        for token in ("Identity/SuVariant", "su_variant", "Identity/ShellColor", "Identity/SuModel"):
            report["identity_tokens"][key][token] = any(token.encode(enc) in raw[key] for enc in ("ascii", "utf-16le", "utf-16be"))
    for label, root in (("system", system), ("vendor", vendor)):
        files = [p for p in root.rglob("*") if p.is_file()]
        report["filesystem_inventory"][label] = {
            "files": len(files),
            "named_images": [str(p.relative_to(root)) for p in files if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".svg", ".webp")],
            "named_startup_assets": [str(p.relative_to(root)) for p in files if pattern.search(p.name)],
        }
    output.mkdir(parents=True, exist_ok=True)
    (output / "logo-luma-preview.png").write_bytes(png)
    (output / "startup-variant-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (output / "gui-resource-inventory.json").write_text(json.dumps([{key: value for key, value in item.items() if key != "content"} for item in items], indent=2) + "\n")
    print("6 X2DM2 hardware IDs, 1112 GUI resources, 1 vendor Logo decoded; offline only")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-root", type=Path, required=True)
    parser.add_argument("--vendor-root", type=Path, required=True)
    parser.add_argument("--mcu", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inspect(args.system_root, args.vendor_root, args.mcu, args.output)


if __name__ == "__main__":
    main()
