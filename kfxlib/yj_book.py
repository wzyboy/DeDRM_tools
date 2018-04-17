from __future__ import (unicode_literals, division, absolute_import, print_function)

import os
import posixpath
import traceback
import sys

from .ion import (
            add_shared_symbol_table, LocalSymbolTable, report_local_symbol_tables)
from .kfx_container import (KfxContainer, MAX_KFX_CONTAINER_SIZE)
from .kpf_book import KpfBook
from .kpf_container import (
            KpfContainer)
from .misc import (
            DataFile, exception_string, hex_string, KFXDRMError, temp_file_cleanup)
from .yj_container import YJFragmentList
from .yj_metadata import (BookMetadata, YJ_Metadata)
from .yj_position_location import BookPosLoc
from .yj_structure import BookStructure
from .yj_symbol_catalog import (
            DICTIONARY_RULE_SET_SYMBOLS, PLUGIN_MANIFEST_SYMBOLS, SYSTEM_SYMBOL_TABLE, YJ_SYMBOLS)

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

add_shared_symbol_table(SYSTEM_SYMBOL_TABLE)
add_shared_symbol_table(YJ_SYMBOLS)
add_shared_symbol_table(PLUGIN_MANIFEST_SYMBOLS)
add_shared_symbol_table(DICTIONARY_RULE_SET_SYMBOLS)

class YJ_Book(BookStructure, BookPosLoc, BookMetadata, KpfBook):
    def __init__(self, file, log, credentials=[], pure=False, metadata=None, approximate_pages=None, is_netfs=False):
        self.datafile = DataFile(file)
        self.log = log
        self.credentials = credentials
        self.pure = pure
        self.desired_metadata = metadata
        self.desired_approximate_pages = approximate_pages
        self.is_netfs = is_netfs

        self.reported_errors = set()
        self.symtab = LocalSymbolTable(self.log, "YJ_symbols")
        self.fragments = YJFragmentList()
        self.is_kpf_prepub = self.is_dictionary = False
        self.kpf_container = None

    def final_actions(self):
        report_local_symbol_tables()
        temp_file_cleanup()

    def convert_to_single_kfx(self):
        self.decode_book()

        if self.is_dictionary:
            raise Exception("Cannot serialize dictionary as KFX container")

        if self.is_kpf_prepub:
            raise Exception("Cannot serialize KPF as KFX container without fix-up")

        result = KfxContainer(self.log, self, fragments=self.fragments).serialize()

        if len(result) > MAX_KFX_CONTAINER_SIZE:
            self.log.warning("KFX container created may be too large for some devices (%d bytes)" % len(result))
            pass

        self.final_actions()
        return result

    def convert_to_epub(self, epub_version="2.0"):
        from .yj_to_epub import EPUB
        self.decode_book()
        result = EPUB(self, self.log, epub_version).epub_data
        self.final_actions()
        return result

    def get_metadata(self):

        self.locate_book_datafiles()

        for datafile in self.container_datafiles:
            try:
                container = self.get_container(datafile, ignore_drm=True)
                if container is None:
                    continue

                container.deserialize(ignore_drm=True)
                self.fragments.extend(container.get_fragments())

            except Exception as e:
                self.log.warning("Failed to extract content from %s: %s" % (datafile.name, unicode(e)))
                continue

            if self.has_metadata() and self.has_cover_data():
                break

        if not self.has_metadata():
            raise Exception("Failed to locate a KFX container with metadata")

        return YJ_Metadata().get_from_book(self)

    def convert_to_kpf(self, app_name=None, timeout_sec=None, tail_logs=False, do_prep=True, prep_only=False):
        from .generate_kpf import convert_nonyj_to_kpf

        if not self.datafile.is_real_file:
            raise Exception("Cannot create KPF from stream")

        return convert_nonyj_to_kpf(self.datafile.name, self.log, app_name, timeout_sec, tail_logs, do_prep, prep_only)

    def decode_book(self):
        if self.fragments:
            return

        self.locate_book_datafiles()
        yj_containers = []

        for datafile in self.container_datafiles:
            self.log.info("Processing container: %s" % datafile.name)
            container = self.get_container(datafile)
            container.deserialize(pure=self.pure)
            yj_containers.append(container)

        for container in yj_containers:
            self.fragments.extend(container.get_fragments())

        if self.is_kpf_prepub and not self.pure:
            self.fix_kpf_prepub_book()

        if True:
            self.check_consistency()

        if not self.pure:
            if self.desired_metadata is not None:
                self.desired_metadata.set_to_book(self)

            if self.desired_approximate_pages is not None and self.desired_approximate_pages >= 0:
                try:
                    self.create_approximate_page_list(self.desired_approximate_pages)
                except Exception as e:
                    self.log.error("Exception creating approximate page numbers: %s" % exception_string(e))
                    traceback.print_exc(file=sys.stdout)

        try:
            self.report_features_and_metadata(unknown_only=False)
        except Exception as e:
            self.log.error("Exception checking book features and metadata: %s" % exception_string(e))
            traceback.print_exc(file=sys.stdout)

        self.check_fragment_usage(rebuild=not self.pure, ignore_extra=False)
        self.check_symbol_table(rebuild=not self.pure)

        self.final_actions()

    def locate_book_datafiles(self):
        self.container_datafiles = []

        if self.datafile.ext in [
                    ".azw8", ".kdf", ".kfx", ".kpf"]:

            self.container_datafiles.append(self.datafile)

        elif self.datafile.ext in [
                    ".kfx-zip"]:

            with self.datafile.as_ZipFile() as zf:
                    for info in zf.infolist():
                        self.check_located_file(info.filename, zf.read(info), self.datafile)

        else:
            raise Exception("Unknown file type. Must be kfx, kfx-zip, or kpf.")

        if not self.container_datafiles:
            raise Exception("No KFX containers found. This book is not in KFX format.")

        self.container_datafiles = sorted(self.container_datafiles)

    def locate_files_from_dir(self, directory, match=None):

        for dirpath, dirnames, filenames in os.walk(directory):
            for fn in filenames:
                if (not match) or match == fn:
                    self.check_located_file(os.path.join(dirpath, fn))

    def check_located_file(self, name, data=None, parent=None):
        basename = posixpath.basename(name.replace("\\", "/"))
        ext = os.path.splitext(basename)[1]

        if ext in [".azw", ".azw8", ".azw9", ".kdf", ".kfx", ".kfxi", ".kpf", ".md", ".res", ".yj"]:
            self.container_datafiles.append(DataFile(name, data, parent))

    def get_container(self, datafile, ignore_drm=False):

        data = datafile.get_data()
        if data.startswith(KpfContainer.kpf_signature) or data.startswith(KpfContainer.kdf_signature):
            self.kpf_container = KpfContainer(self.log, self, datafile, is_netfs=self.is_netfs)
            return self.kpf_container

        if data.startswith(KfxContainer.signature):
            return KfxContainer(self.log, self, datafile)

        if data.startswith(KfxContainer.drm_signature):

            if ignore_drm:
                return None

            raise KFXDRMError("Book container %s has DRM and cannot be converted" % datafile.name)

        if data[0x3c:0x3c+8] == b"BOOKMOBI":
            raise Exception("File format is MOBI (not KFX) for %s" % datafile.name)

        raise Exception("Unable to determine KFX container type of %s (%s)" % (datafile.name, hex_string(data[:8])))

