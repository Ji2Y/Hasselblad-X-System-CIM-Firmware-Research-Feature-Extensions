"""版本锁定的二代完整对焦策略依赖核对；纯离线，不安装或执行固件。"""
import argparse
import hashlib
import io
import json
import re
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from elftools.elf.elffile import ELFFile

FIRST_SHA='feef8a8dc3a27395e47232c2b25a5da7a7ab335922fbb527e637c439e35bcec7'
SECOND_SHA='7d6164eccc734de7087bb778ee72f17a0b3ccf6c0d1f20092c7ebe74a86574ba'
CONFIG_SHA='e4f965ed8634c0e14d418d4f57131243d7ea197b8abea2a84d9ee0f934d2ed9e'
PRODUCER_SHA='e56012e2a60a1d96d998d754b2fcb253382f9205c6f12ec530025af9cad5476f'
ROOTS=('_exec_pdaf_afs_process','_exec_pdaf_afc_process','afc_ctrl_process',
       'get_pdaf_type2_align_lens_pos','pdaf_type2_run')


class Image:
    def __init__(self,path,expected):
        self.data=path.read_bytes()
        if hashlib.sha256(self.data).hexdigest()!=expected:
            raise ValueError('固件基线不匹配: '+path.name)
        self.elf=ELFFile(io.BytesIO(self.data))
        if self.elf['e_machine']!='EM_AARCH64': raise ValueError('架构不匹配')
        symbols=list(self.elf.get_section_by_name('.dynsym').iter_symbols())
        self.exports={s.name:s for s in symbols if s.name and s['st_shndx']!='SHN_UNDEF'}
        self.referenced_names={s.name for s in symbols if s.name}
        self.names={s['st_value']:s.name for s in symbols if s['st_value']}
        plt=self.elf.get_section_by_name('.plt')
        reloc=self.elf.get_section_by_name('.rela.plt')
        if plt and reloc:
            for i,r in enumerate(reloc.iter_relocations()):
                self.names[plt['sh_addr']+32+16*i]=symbols[r['r_info_sym']].name
        self.md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)

    def read(self,address,size):
        for s in self.elf.iter_segments():
            if s['p_type']=='PT_LOAD' and s['p_vaddr']<=address and address+size<=s['p_vaddr']+s['p_filesz']:
                off=s['p_offset']+address-s['p_vaddr']
                return self.data[off:off+size]
        raise ValueError('ELF 读取越界')

    def instructions(self,address,size):
        return list(self.md.disasm(self.read(address,size),address))


def audit(first_root,second_root):
    first=Image(first_root/'lib64/libaaa.so',FIRST_SHA)
    second=Image(second_root/'lib64/libaaa.so',SECOND_SHA)
    producer=Image(first_root/'lib64/camera/plugins/stream_filter/libdcam_pdaf_stream_filter.so',PRODUCER_SHA)
    evidence={}
    for name in ROOTS:
        symbol=second.exports[name]
        instructions=second.instructions(symbol['st_value'],symbol['st_size'])
        calls=[]; indirect=[]
        for ins in instructions:
            if ins.mnemonic=='bl':
                va=int(ins.op_str[1:],16); called=second.names.get(va)
                calls.append({'at':hex(ins.address),'target_va':hex(va),'symbol':called,
                              'same_name_export_in_first':bool(called and called in first.exports),
                              'referenced_in_first_dynsym':bool(called and called in first.referenced_names)})
            elif ins.mnemonic=='blr': indirect.append(hex(ins.address))
        evidence[name]={'va':hex(symbol['st_value']),'size':symbol['st_size'],
                        'first_same_name_export':name in first.exports,
                        'calls':calls,'indirect_calls':indirect,
                        'not_exported_by_first_libaaa':sorted({c['symbol'] for c in calls if c['symbol'] and not c['same_name_export_in_first']}),
                        'not_referenced_by_first_libaaa':sorted({c['symbol'] for c in calls if c['symbol'] and not c['referenced_in_first_dynsym']})}
    alignment=second.instructions(0x185f08,0x98)
    at=next(i for i in alignment if i.address==0x185f24)
    if at.mnemonic!='bl' or second.names.get(int(at.op_str[1:],16))!='get_pdaf_type2_align_lens_pos':
        raise ValueError('二代位置对齐接口不匹配')
    checkpoints={0x2058:'duss_hal_mem_map',0x20fc:'duss_hal_mem_sync_ext',
                 0x21dc:'dji_pdaf_type3_stats_calculate',0x21ec:'looper_message_wait',
                 0x2284:'dji_pdaf_type3_stats_get_results'}
    verified=[]
    for address,name in checkpoints.items():
        ins=producer.instructions(address,4)[0]
        if ins.mnemonic!='bl' or producer.names.get(int(ins.op_str[1:],16))!=name:
            raise ValueError('一代生产调用链不匹配: '+hex(address))
        verified.append({'at':hex(address),'symbol':name})
    # The copier covers every native mode-1 source offset, not an invented pair.
    descriptor=first.read(0x1b2a08+168,84)
    import struct
    lengths=struct.unpack_from('<4h',descriptor,0x48)
    offsets=[struct.unpack_from('<6h',descriptor,0x18+12*i)[:lengths[i]] for i in range(4)]
    if lengths!=(3,3,3,3) or sorted(v for row in offsets for v in row)!=list(range(12)):
        raise ValueError('相位行快照未覆盖原厂取样地址')
    cfg=(second_root/'etc/aaa/af/af_imx861.json').read_bytes()
    if hashlib.sha256(cfg).hexdigest()!=CONFIG_SHA: raise ValueError('二代配置不匹配')
    text=cfg.decode()
    match=re.search(r'afc_ctrl_alg_cfg\s*:\s*\[(.*?)\]',text,re.S)
    if not match: raise ValueError('二代 AFC 算法配置缺失')
    algorithms=[int(v) for v in re.findall(r'\d+',re.sub(r'//[^\n]*','',match.group(1)))]
    if algorithms!=[1,0,0,1]:raise ValueError('二代融合选择不匹配')
    configs=[{'line':n,'text':line.strip()} for n,line in enumerate(text.splitlines(),1)
             if re.match(r'\s*(pd_type|pd_mode|stats_frame_delay_vs_lens|low_lattency_afc_enable|afc_interval_time_ms|fusion_enable|master_algo_type|slave_algo_type|backup_algo_type)\s*:',line)]
    return {'source_firmware':'X2D II 1.3.16.2','target_firmware':'X2D 4.2.0',
            'method':'离线函数直接调用、对齐助手、原厂生产链及配置核对',
            'functions':evidence,'producer_calls':verified,
            'producer_return_pc':'0x21e0','source_offsets_by_channel':offsets,
            'second_configuration':configs,'afc_algorithms':algorithms,
            'same_symbol_name_proves_abi_compatibility':False,
            'symbol_comparison_scope':'两份 libaaa 的 dynsym；未导出或未引用不能单独证明系统依赖库缺失',
            'same_zone_count_proves_compatibility':False,
            'full_strategy_ready':False,'device_tested':False,'camera_writes':False,
            'unimplemented_contracts':['原厂回调注册和可靠帧所有权验证','425 区域实测有效性及实时预算',
                'Type3 结果到二代 Type2/mesh 输入的语义适配','与相位帧对应的镜头位置/时序参考',
                'AF-S 状态与命令确认','AF-C 控制器上下文和连续预测','对象/ROI 追踪输入',
                '无 ToF 输入的融合与失效路径'],
            'scope_limit':'一代缺少二代雷达输入；无雷达策略适配和完整原样移植必须区别。'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--first-root',required=True,type=Path)
    p.add_argument('--second-root',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    args.output=args.output.resolve()
    for source in (args.first_root.resolve(),args.second_root.resolve()):
        if args.output==source or source in args.output.parents:
            p.error('输出不能写入固件输入树')
    if args.output.exists():
        p.error('输出文件必须尚不存在，避免覆盖证据')
    report=audit(args.first_root,args.second_root)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'producer_calls_verified':len(report['producer_calls']),
                     'roots_audited':len(report['functions']),
                     'missing_root_exports':[n for n,v in report['functions'].items() if not v['first_same_name_export']],
                     'full_strategy_ready':False},ensure_ascii=False))
