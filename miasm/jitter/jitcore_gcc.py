#-*- coding:utf-8 -*-

import os
import tempfile
import ctypes
import _ctypes
import platform
import sysconfig
from subprocess import check_call
from distutils.sysconfig import get_python_inc
from miasm.jitter import Jitgcc
from miasm.jitter.jitcore_cc_base import JitCore_Cc_Base, gen_core

is_win = platform.system() == "Windows"

class JitCore_Gcc(JitCore_Cc_Base):
    "JiT management, using a C compiler as backend"

    def __init__(self, ir_arch, bin_stream):
        super(JitCore_Gcc, self).__init__(ir_arch, bin_stream)
        self.exec_wrapper = Jitgcc.gcc_exec_block

    def deleteCB(self, offset):
        """Free the state associated to @offset and delete it
        @offset: gcc state offset
        """
        flib = None
        if is_win:
            flib = _ctypes.FreeLibrary
        else:
            flib = _ctypes.dlclose
        flib(self.states[offset]._handle)
        del self.states[offset]

    def load_code(self, label, fname_so):
        lib = ctypes.cdll.LoadLibrary(fname_so)
        func = getattr(lib, self.FUNCNAME)
        addr = ctypes.cast(func, ctypes.c_void_p).value
        offset = self.ir_arch.loc_db.get_location_offset(label)
        self.offset_to_jitted_func[offset] = addr
        self.states[offset] = lib

    def add_block(self, block):
        """Add a bloc to JiT and JiT it.
        @block: block to jit
        """
        block_hash = self.hash_block(block)
        ext = sysconfig.get_config_var('EXT_SUFFIX')
        if ext is None:
            ext = ".so" if not is_win else ".pyd"
        fname_out = os.path.join(self.tempdir, "%s%s" % (block_hash, ext))

        if not os.access(fname_out, os.R_OK | os.X_OK):
            func_code = self.gen_c_code(block)

            # Create unique C file
            fdesc, fname_in = tempfile.mkstemp(suffix=".c")
            os.write(fdesc, func_code.encode())
            os.close(fdesc)

            # Create unique SO file
            fdesc, fname_tmp = tempfile.mkstemp(suffix=ext)
            os.close(fdesc)

            inc_dir = ["-I%s" % inc for inc in self.include_files]
            libs = ["%s" % lib for lib in self.libs]
            args = [
                "cc" if not is_win else "gcc",
                "-O3",
                "-shared",
                "-fPIC",
                fname_in,
                "-o",
                fname_tmp
            ] + inc_dir + libs
            check_call(args)

            # Move temporary file to final file
            try:
                os.rename(fname_tmp, fname_out)
            except WindowsError as e:
                # On Windows, os.rename works slightly differently than on
                # Linux; quoting the documentation:
                # "On Unix, if dst exists and is a file, it will be replaced
                # silently if the user has permission.  The operation may fail
                # on some Unix flavors if src and dst are on different
                # filesystems.  If successful, the renaming will be an atomic
                # operation (this is a POSIX requirement).  On Windows, if dst
                # already exists, OSError will be raised even if it is a file;
                # there may be no way to implement an atomic rename when dst
                # names an existing file."
                # [Error 183] Cannot create a file when that file already exists
                if e.winerror != 183:
                    raise
                os.remove(fname_tmp)
            os.remove(fname_in)

        self.load_code(block.loc_key, fname_out)

    @staticmethod
    def gen_C_source(ir_arch, func_code):
        c_source = ""
        c_source += "\n".join(func_code)

        c_source = gen_core(ir_arch.arch, ir_arch.attrib) + c_source
        c_source = "#define PARITY_IMPORT\n#include <Python.h>\n" + c_source
        return c_source

    def _get_ext(self):
        return ".so" if not is_win else ".pyd"
