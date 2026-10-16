"""主机替身验证调度、边界和结果完整性；不验证原厂相位算法。"""
import ctypes as C
import os
from pathlib import Path
import struct
import shlex
import shutil
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
U8=C.c_ubyte


class ROI(C.Structure):
    _fields_=[("x",C.c_ushort),("y",C.c_ushort),("width",C.c_ushort),("height",C.c_ushort)]


class Frame(C.Structure):
    _fields_=[("raw",C.POINTER(U8)),("bytes",C.c_ulonglong),
              ("frame_id",C.c_ulonglong),("config",U8*170)]


class Record(C.Structure):
    _fields_=[("roi",ROI),("native",U8*13),("usable",U8)]


class Result(C.Structure):
    _fields_=[("frame_id",C.c_ulonglong),("elapsed_us",C.c_ulonglong),
              ("completed",C.c_uint),("usable",C.c_uint),("complete",C.c_uint),
              ("records",Record*425)]


Calculate=C.CFUNCTYPE(C.c_int,C.c_void_p,C.POINTER(Frame),C.POINTER(U8),C.POINTER(U8))
Clock=C.CFUNCTYPE(C.c_ulonglong,C.c_void_p)
Same=C.CFUNCTYPE(C.c_int,C.c_void_p,C.POINTER(Frame))
Lease=C.CFUNCTYPE(C.c_int,C.c_void_p,C.c_ulonglong)


class Backend(C.Structure):
    _fields_=[("user",C.c_void_p),("calculate",Calculate),("clock_us",Clock),("same_frame",Same)]


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler=shlex.split(os.environ.get('CC','clang'))
        if not compiler or not shutil.which(compiler[0]):
            raise unittest.SkipTest('A C11 compiler is required for the 425-region host checks')
        cls.tmp=tempfile.TemporaryDirectory()
        library=Path(cls.tmp.name)/"core.dylib"
        subprocess.run([*compiler,"-std=c11","-Wall","-Wextra","-Werror","-O1",
                        "-shared","-fPIC",str(HERE/"pdaf425_core.c"),str(HERE/"pdaf425_capture.c"),"-o",str(library)],check=True)
        cls.lib=C.CDLL(str(library))
        cls.lib.p425_plan.argtypes=[C.POINTER(Frame),C.POINTER(ROI)]
        cls.lib.p425_process.argtypes=[C.POINTER(Frame),C.POINTER(Backend),C.c_ulonglong,C.POINTER(Result)]
        cls.lib.p425_capture_index2.argtypes=[C.POINTER(U8),C.c_ulonglong,C.POINTER(U8),C.c_ulonglong,
                                             C.POINTER(U8),C.c_ulonglong,C.c_void_p,Lease,C.POINTER(Frame)]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.raw=(U8*1)()  # Stub never reads raw data; not a firmware input.
        self.frame=Frame(C.cast(self.raw,C.POINTER(U8)),3968*1248*2,91)
        for i in range(170): self.frame.config[i]=(i*13+7)%256
        self.frame.config[0]=1
        self.frame.config[0xa8]=1
        self.frame.config[0xa9]=1
        for offset,value in [(5,3888),(7,1248)]:
            self.frame.config[offset:offset+2]=struct.pack('<H',value)
        self.calls=[]; self.tick=100; self.fail_at=None; self.changed_at=None
        self.nan_at=None; self.disabled_at=None; self.global_invalid_at=None

        def calculate(_user,f,cfg,out):
            index=len(self.calls)
            self.calls.append(bytes(cfg[:170]))
            if index==self.fail_at: return -1
            status=0 if index==self.global_invalid_at else 1
            C.memmove(out,struct.pack("<I",status),4)
            phase=float("nan") if index==self.nan_at else index+0.25
            record=struct.pack("<ffIB",phase,float(index),23,0 if index==self.disabled_at else 1)
            C.memmove(C.addressof(out.contents)+8,record,len(record))
            return 0

        def clock(_user):
            self.tick+=10
            return self.tick

        def same(_user,_f):
            return int(self.changed_at is None or len(self.calls)<self.changed_at)

        self.callbacks=(Calculate(calculate),Clock(clock),Same(same))
        self.backend=Backend(None,*self.callbacks)

    def run_core(self,budget=1000000):
        result=Result()
        status=self.lib.p425_process(C.byref(self.frame),C.byref(self.backend),budget,C.byref(result))
        return status,result

    def test_tiles_cover_sample_lattice_exactly_once(self):
        for selector,width,stride,height,x,dx,y,dy,columns in [
            (0,11760,11760,8842,57,12,147,210,970),
            (1,3888,3968,1248,3,4,7,30,970),
            (2,11664,11776,1248,0,12,7,30,972)]:
            self.frame.config[0xa8]=selector; self.frame.bytes=stride*height*2
            self.frame.config[5:7]=struct.pack('<H',width)
            self.frame.config[7:9]=struct.pack('<H',height)
            plan=(ROI*425)()
            self.assertEqual(self.lib.p425_plan(C.byref(self.frame),plan),0)
            covered=set()
            for r in plan:
                self.assertEqual((r.x-x)%dx,0); self.assertEqual((r.y-y)%dy,0)
                xs=(r.x-x)//dx; ys=(r.y-y)//dy
                count_x=r.width//dx; count_y=r.height//dy+1
                self.assertGreaterEqual(count_x,38); self.assertGreaterEqual(count_y,2)
                cells={(a,b) for a in range(xs,xs+count_x) for b in range(ys,ys+count_y)}
                self.assertFalse(cells & covered); covered.update(cells)
            self.assertEqual(covered,{(a,b) for a in range(columns) for b in range(42)})

    def test_all_425_native_results_retained_in_order(self):
        status,result=self.run_core()
        self.assertEqual((status,result.completed,result.complete,result.usable),(0,425,1,425))
        self.assertEqual(result.frame_id,91)
        self.assertEqual(len(self.calls),425)
        for i,r in enumerate(result.records):
            self.assertEqual(struct.unpack("<f",bytes(r.native[:4]))[0],i+0.25)

    def test_only_roi_slots_changed_and_single_roi_enabled(self):
        original=bytes(self.frame.config)
        self.run_core()
        for cfg in self.calls:
            self.assertEqual(cfg[:0x3b],original[:0x3b])
            self.assertEqual(cfg[0x95:],original[0x95:])
            self.assertEqual([cfg[0x3b+j*9] for j in range(10)],[1]+[0]*9)
        self.assertEqual(bytes(self.frame.config),original)

    def test_truncated_raw_frame_rejected_before_native_call(self):
        self.frame.bytes-=2
        status,result=self.run_core()
        self.assertEqual((status,result.complete,len(self.calls)),(-1,0,0))

    def test_unverified_sensor_mode_and_lens_segment_rejected(self):
        self.frame.config[0xa8]=3
        self.assertEqual(self.run_core()[0],-1)
        self.frame.config[0xa8]=1; self.frame.config[0xa9]=2
        self.assertEqual(self.run_core()[0],-1)

    def test_frame_dimensions_must_match_verified_descriptor(self):
        self.frame.config[5:7]=struct.pack('<H',11664)
        self.assertEqual(self.run_core()[0],-1)
        self.assertFalse(self.calls)

    def test_timeout_does_not_publish_complete_grid(self):
        status,result=self.run_core(budget=80)
        self.assertEqual(status,-3)
        self.assertEqual(result.complete,0)
        self.assertLess(result.completed,425)

    def test_backend_failure_preserves_partial_status(self):
        self.fail_at=24
        status,result=self.run_core()
        self.assertEqual((status,result.completed,result.complete),(-2,24,0))

    def test_frame_change_rejected_after_callback(self):
        self.changed_at=7
        status,result=self.run_core()
        self.assertEqual((status,result.completed,result.complete),(-4,6,0))

    def test_nan_disabled_and_invalid_native_results_not_usable(self):
        self.nan_at=9; self.disabled_at=20; self.global_invalid_at=30
        status,result=self.run_core()
        self.assertEqual((status,result.complete,result.usable),(0,1,422))
        for i in (9,20,30): self.assertEqual(result.records[i].usable,0)

    def test_clock_failure_rejected(self):
        callback=Clock(lambda _user:0)
        self.backend.clock_us=callback
        status,result=self.run_core()
        self.assertEqual((status,result.complete,len(self.calls)),(-2,0,0))

    def test_sparse_snapshot_covers_all_native_phase_addresses(self):
        size=11776*1248*2
        source=(U8*size)(); storage=(U8*size)(); frame=Frame()
        cfg=(U8*170)(); cfg[0]=1; cfg[0xa8]=2; cfg[0xa9]=1; cfg[0x11]=1
        cfg[1:5]=struct.pack('<I',91); cfg[5:7]=struct.pack('<H',11664); cfg[7:9]=struct.pack('<H',1248)
        # Mark first/last samples of every copied row, plus locations that must
        # not be copied (stride padding and an ordinary row).
        for y in range(42):
            start=(7+y*30)*11776*2
            source[start]=y+1; source[start+11664*2-1]=200-y
            source[start+11664*2]=99
        source[0]=88
        lease=Lease(lambda _owner,number:int(number==91))
        status=self.lib.p425_capture_index2(source,size,cfg,91,storage,size,None,lease,C.byref(frame))
        self.assertEqual(status,0); self.assertEqual(frame.bytes,size)
        for y in range(42):
            start=(7+y*30)*11776*2
            self.assertEqual((storage[start],storage[start+11664*2-1]),(y+1,200-y))
            self.assertEqual(storage[start+11664*2],0)
        self.assertEqual(storage[0],0)
        # Capture output is directly accepted by the 425-region planner.
        self.assertEqual(self.lib.p425_plan(C.byref(frame),(ROI*425)()),0)

    def test_capture_rejects_overlap_wrong_frame_and_lost_lease(self):
        size=11776*1248*2
        source=(U8*size)(); storage=(U8*size)(); frame=Frame()
        cfg=(U8*170)(); cfg[0]=1;cfg[0xa8]=2;cfg[0xa9]=1;cfg[0x11]=1
        cfg[1:5]=struct.pack('<I',91);cfg[5:7]=struct.pack('<H',11664);cfg[7:9]=struct.pack('<H',1248)
        valid=Lease(lambda _owner,_number:1)
        self.assertEqual(self.lib.p425_capture_index2(source,size,cfg,91,source,size,None,valid,C.byref(frame)),-1)
        self.assertEqual(self.lib.p425_capture_index2(source,size,cfg,92,storage,size,None,valid,C.byref(frame)),-1)
        calls=[0]
        def lost(_owner,_number):
            calls[0]+=1
            return int(calls[0]<10)
        callback=Lease(lost)
        self.assertEqual(self.lib.p425_capture_index2(source,size,cfg,91,storage,size,None,callback,C.byref(frame)),-4)
        self.assertFalse(frame.raw);self.assertEqual(frame.bytes,0)


if __name__=="__main__": unittest.main()
