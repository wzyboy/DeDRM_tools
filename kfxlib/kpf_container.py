from __future__ import (unicode_literals, division, absolute_import, print_function)

import os
import cStringIO

try:
    import apsw
    have_apsw = True
except:
    import sqlite3
    have_apsw = False

from .ion import (
        ion_type, IonAnnotation, IonBLOB, IonInt, IonList, IonSExp, IonString, IonStruct, IS, SYSTEM_SYMBOL_TABLE)
from .ion_binary import (Deserializer, IonBinary)
from .misc import (
        DataFile, hex_string, json_deserialize, json_serialize, KFXDRMError, natural_sort_key, temp_filename)
from .version import __version__
from .yj_container import (
        ROOT_FRAGMENT_TYPES,
        CONTAINER_FORMAT_KPF, YJContainer, YJFragment, YJFragmentList)

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

DEBUG = False
RETAIN_KDX_ID_ANNOT_IF_PURE = False

DICTIONARY_RULES_FILENAME = "DictionaryRules.ion"

class KpfContainer(YJContainer):
    kpf_signature = b"\x50\x4B\x03\x04"
    kdf_signature = b"SQLite format 3\0"
    db_timeout = 30

    def __init__(self, log, book, datafile, is_netfs=False):
        YJContainer.__init__(self, log, book, datafile=datafile)
        self.is_netfs = is_netfs

    def deserialize(self, pure=False, ignore_drm=False):
        self.ignore_drm = ignore_drm
        self.fragments = YJFragmentList()

        self.kpf_datafile = self.kdf_datafile = None
        self.file_creator = self.creator_version = ""

        if self.datafile.is_zipfile():
            self.kpf_datafile = self.datafile

            with self.kpf_datafile.as_ZipFile() as zf:
                for info in zf.infolist():
                    ext = os.path.splitext(info.filename)[1]
                    if ext == ".kdf":
                        self.kdf_datafile = DataFile(info.filename, zf.read(info), self.kpf_datafile)

                    elif ext == ".kdf-journal":
                        if len(zf.read(info)) > 0:
                            raise Exception("kdf-journal is not empty in %s" % self.kpf_datafile.name)

                    elif ext == ".kcb":
                        kcb = json_deserialize(zf.read(info))
                        kcb_metadata = kcb.get("metadata", {})
                        self.file_creator = kcb_metadata.get("tool_name", "")
                        self.creator_version = kcb_metadata.get("tool_version", "")

            if self.kdf_datafile is None:
                raise Exception("Failed to locate KDF within %s" % self.datafile.name)

        else:
            self.kdf_datafile = self.datafile

        unwrapped_kdf_datafile = self.remove_sqlite_fingerprint_file_wrapper(self.kdf_datafile)

        db_filename = (unwrapped_kdf_datafile.name if unwrapped_kdf_datafile.is_real_file and not self.is_netfs else
                        temp_filename("kdf", unwrapped_kdf_datafile.get_data()))

        if have_apsw:
            if natural_sort_key(apsw.sqlitelibversion()) < natural_sort_key("3.8.2"):
                raise Exception("SQLite version 3.8.2 or later is necessary in order to use a WITHOUT ROWID table. Found version %s" %
                            apsw.sqlitelibversion())

            conn = apsw.Connection(db_filename)
        else:
            if sqlite3.sqlite_version_info < (3, 8, 2):
                raise Exception("SQLite version 3.8.2 or later is necessary in order to use a WITHOUT ROWID table. Found version %s" %
                            sqlite3.sqlite_version)

            conn = sqlite3.connect(db_filename, KpfContainer.db_timeout)

        cursor = conn.cursor()

        sql_list = cursor.execute("SELECT sql FROM sqlite_master WHERE type='table';").fetchall()
        schema = set([x[0] for x in sql_list])

        self.fragments = YJFragmentList()

        CAPABILITIES_SCHEMA = "CREATE TABLE capabilities(key char(20), version smallint, primary key (key, version)) without rowid"
        if CAPABILITIES_SCHEMA in schema:
            schema.remove(CAPABILITIES_SCHEMA)
            capabilities = cursor.execute("SELECT * FROM capabilities;").fetchall()

            if capabilities:
                format_capabilities = [IonStruct(IS("$492"), key, IS("$5"), version) for key,version in capabilities]
                self.fragments.append(YJFragment(ftype="$593", value=format_capabilities))
        else:
            self.log.error("KPF database is missing the 'capabilities' table")

        dictionary_index_terms = set()
        first_head_word = ""
        INDEX_INFO_SCHEMA = ("CREATE TABLE index_info(namespace char(256), index_name char(256), property char(40), "
                        "primary key (namespace, index_name)) without rowid")

        if INDEX_INFO_SCHEMA in schema:

            schema.remove(INDEX_INFO_SCHEMA)
            self.book.is_dictionary = True
            for namespace, index_name, property in cursor.execute("SELECT * FROM index_info;"):
                if namespace != "dictionary" or property != "yj.dictionary.term":
                    self.log.warning("unexpected index_info: namespace=%s, index_name=%s, property=%s" % (namespace, index_name, property))

                table_name = "index_%s_%s" % (namespace, index_name)
                index_schema = ("CREATE TABLE %s ([%s] char(256),  id char(40), "
                                "primary key ([%s], id)) without rowid") % (table_name, property, property)

                if index_schema in schema:
                    schema.remove(index_schema)
                    num_entries = 0
                    index_words = set()
                    index_kfx_ids = set()

                    for dictionary_term, kfx_id in cursor.execute("SELECT * FROM %s;" % table_name):

                        num_entries += 1
                        dictionary_index_terms.add((dictionary_term, IS(kfx_id)))
                        index_words.add(dictionary_term)
                        index_kfx_ids.add(kfx_id)

                        if dictionary_term < first_head_word or not first_head_word:
                            first_head_word = dictionary_term

                    self.log.info("Dictionary %s table has %d entries with %d terms and %d definitions" % (
                            table_name, num_entries, len(index_words), len(index_kfx_ids)))

                else:
                    self.log.error("KPF database is missing the '%s' table" % table_name)

        self.eid_symbol = {}
        KFXID_TRANSLATION_SCHEMA = "CREATE TABLE kfxid_translation(eid INTEGER, kfxid char(40), primary key(eid)) without rowid"
        if KFXID_TRANSLATION_SCHEMA in schema:

            schema.remove(KFXID_TRANSLATION_SCHEMA)
            for eid, kfx_id in cursor.execute("SELECT * FROM kfxid_translation;"):
                self.eid_symbol[eid] = self.create_local_symbol(kfx_id)

        self.max_eid_in_sections = None
        FRAGMENTS_SCHEMA = "CREATE TABLE fragments(id char(40), payload_type char(10), payload_value blob, primary key (id))"
        if FRAGMENTS_SCHEMA in schema:
            schema.remove(FRAGMENTS_SCHEMA)

            for id in ["$ion_symbol_table", "max_id"]:
                row = cursor.execute("SELECT payload_value FROM fragments WHERE id = ? AND payload_type = 'blob';", (id,)).fetchone()
                if row is not None:
                    payload_data = self.prep_payload_blob(row[0])
                    if payload_data is None:
                        pass
                    elif id == "$ion_symbol_table":
                        self.book.symtab.creating_yj_local_symbols = True
                        sym_import = IonBinary(self.log, self.book.symtab, import_symbols=True).deserialize_annotated_value(
                                payload_data, expect_annotation="$3")
                        self.book.symtab.creating_yj_local_symbols = False
                        if DEBUG: self.log.info("kdf symbol import = %s" % json_serialize(sym_import))
                        self.fragments.append(YJFragment(sym_import))
                        break
                    else:
                        max_id = IonBinary(self.log, self.book.symtab).deserialize_single_value(payload_data)
                        if DEBUG: self.log.info("kdf max_id = %d" % max_id)
                        self.book.symtab.clear()
                        self.book.symtab.import_shared_symbol_table("YJ_symbols", max_id=max_id - len(SYSTEM_SYMBOL_TABLE.symbols))
                        self.fragments.append(YJFragment(self.book.symtab.create_import()))

            for id, payload_type, payload_value in cursor.execute("SELECT * FROM fragments;"):

                if payload_type == "blob":

                    payload_data = self.prep_payload_blob(payload_value)

                    if id in ["max_id", "$ion_symbol_table"] or payload_data is None:
                        pass

                    elif not payload_data.startswith(IonBinary.signature):
                        self.fragments.append(YJFragment(ftype="$417", fid=self.create_local_symbol(id),
                                value=IonBLOB(payload_data)))

                    elif id == "max_eid_in_sections":

                        self.max_eid_in_sections = IonBinary(self.log, self.book.symtab).deserialize_single_value(payload_data)
                        if self.book.is_dictionary:

                            pass
                        else:
                            self.log.warning("Unexpected max_eid_in_sections for non-dictionary: %d" % self.max_eid_in_sections)

                    elif len(payload_data) == len(IonBinary.signature):
                        if id != "book_navigation":
                            self.log.warning("Ignoring empty %s fragment" % id)

                    else:
                        value = IonBinary(self.log, self.book.symtab).deserialize_annotated_value(payload_data)

                        if (not isinstance(value, IonAnnotation)) or len(value.annotations) != 1:
                            raise Exception("KDF fragment should have one annotation: %s" % repr(value))

                        ftype = value.annotations[0]

                        if ftype in ROOT_FRAGMENT_TYPES:        # shortcut when symbol table unavailable
                            fid = None
                        else:
                            fid = self.create_local_symbol(id)

                        self.fragments.append(YJFragment(ftype=ftype, fid=fid, value=self.deref_kfx_ids(value.value)))

                elif payload_type == "path":
                    resource_data = self.get_resource_data(unicode(payload_value))
                    if resource_data is not None:

                        self.fragments.append(YJFragment(ftype="$417",
                                    fid=self.create_local_symbol(id), value=IonBLOB(resource_data)))

                else:
                    self.log.error("Unexpected KDF payload_type=%s, id=%s, value=%s" % (payload_type, id, payload_value))
        else:
            self.log.error("KPF database is missing the 'fragments' table")

        FRAGMENT_PROPERTIES_SCHEMA = ("CREATE TABLE fragment_properties(id char(40), key char(40), value char(40), "
                        "primary key (id, key, value)) without rowid")
        if FRAGMENT_PROPERTIES_SCHEMA in schema:
            schema.remove(FRAGMENT_PROPERTIES_SCHEMA)

            for id, key, value in cursor.execute("SELECT * FROM fragment_properties;"):

                pass

        GC_FRAGMENT_PROPERTIES_SCHEMA = ("CREATE TABLE gc_fragment_properties(id varchar(40), key varchar(40), "
                    "value varchar(40), primary key (id, key, value)) without rowid")
        if GC_FRAGMENT_PROPERTIES_SCHEMA in schema:
            schema.remove(GC_FRAGMENT_PROPERTIES_SCHEMA)
            self.log.info("Found gc_fragment_properties table")

        GC_REACHABLE_SCHEMA = ("CREATE TABLE gc_reachable(id varchar(40), primary key (id)) without rowid")
        if GC_REACHABLE_SCHEMA in schema:
            schema.remove(GC_REACHABLE_SCHEMA)
            self.log.info("Found gc_reachable table")

        if len(schema) > 0:
            for s in list(schema):
                self.log.warning("Unexpected KDF database schema: %s" % s)

        cursor.close()
        conn.close()

        self.book.is_kpf_prepub = True
        book_metadata_fragment = self.fragments.get("$490")
        if book_metadata_fragment is not None:
            for cm in book_metadata_fragment.value.get("$491", {}):
                if cm.get("$495", "") == "kindle_title_metadata":
                    for kv in cm.get("$258", []):
                        if kv.get("$492", "") in ["ASIN", "asset_id", "cde_content_type", "content_id"]:
                            self.book.is_kpf_prepub = False
                            break
                    break

        self.fragments.append(YJFragment(ftype="$270", value=IonStruct(
            IS("$587"), "kfxlib-%s" % __version__,
            IS("$588"), self.file_creator + ("-" + self.creator_version if self.creator_version else ""),
            IS("$161"), CONTAINER_FORMAT_KPF)))

    def prep_payload_blob(self, data):
        data = cStringIO.StringIO(data).read()

        if not data.startswith(IonBinary.drmion_signature):
            return data

        if self.ignore_drm:
            return None

        raise KFXDRMError("Book container has DRM and cannot be converted")

    def create_local_symbol(self, symbol):
        return self.book.create_local_symbol(symbol)

    def get_resource_data(self, filename, report_missing=True):
        try:
            resource_datafile = self.kdf_datafile.relative_datafile(filename)
            return resource_datafile.get_data()
        except:
            if report_missing:
                self.log.error("Missing resource in KPF file: %s" % filename)

            return None

    def remove_sqlite_fingerprint_file_wrapper(self, datafile):

        FINGERPRINT_SIGNATURE = b"\xfa\x50\x0a\x5f"

        data = datafile.get_data()
        sqlite_header = Deserializer(data)

        signature = sqlite_header.unpack("16s")
        if signature != self.kdf_signature:
            self.log.error("Unexpected SQLite file signature: %s" % hex_string(signature))
            return datafile

        page_size = sqlite_header.unpack(">H")
        if page_size == 1:
            page_size = 65536

        if page_size != 1024:

            self.log.error("Unexpected SQLite page size: %d" % page_size)

        fingerprint_len = page_size
        fingerprint_offset = page_size
        fingerprinted_frame_len = page_size * 1024

        if (len(data) < fingerprint_offset + fingerprint_len or
                data[fingerprint_offset:fingerprint_offset + len(FINGERPRINT_SIGNATURE)] != FINGERPRINT_SIGNATURE):
            return datafile

        fingerprint_count = 0

        while len(data) >= fingerprint_offset + fingerprint_len:
            fingerprint = Deserializer(data[fingerprint_offset:fingerprint_offset + fingerprint_len])
            remainder = data[fingerprint_offset + fingerprint_len:]

            signature = fingerprint.extract(4)
            if signature != FINGERPRINT_SIGNATURE:
                self.log.error("Unexpected fingerprint signature at 0x%x, page size %d: %s" % (
                                fingerprint_offset, page_size, hex_string(signature)))
                return datafile

            header = fingerprint.extract(5)
            if header != b"\x01\x00\x00\x40\x20":
                self.log.warning("Unexpected fingerprint header at 0x%x, page size %d: %s" % (
                                fingerprint_offset, page_size, hex_string(header)))

            data = data[:fingerprint_offset] + remainder
            fingerprint_count += 1
            fingerprint_offset += fingerprinted_frame_len

        self.log.info("Removed %d KDF SQLite file fingerprint(s)" % fingerprint_count)

        return DataFile(datafile.name + "-unwrapped", data)

    def deref_kfx_ids(self, data):

        def process(data):
            data_type = ion_type(data)

            if data_type is IonAnnotation:
                if data.annotations[0] == "$598":
                    val = data.value
                    val_type = ion_type(val)

                    if val_type is IonString:
                        return self.create_local_symbol(val)
                    elif val_type is IonInt:
                        value = self.eid_symbol.get(val)
                        if value is not None:
                            return value
                        else:
                            self.log.error("Undefined kfx_id annotation eid: %d" % val)
                    else:
                        self.log.error("Unexpected data type for kfx_id annotation: %s" % val_type)

                    return val

                process(data.value)

            if data_type is IonList or data_type is IonSExp:
                for i,val in enumerate(list(data)):
                    new_val = process(val)
                    if new_val is not None:
                        data.pop(i)
                        data.insert(i, new_val)

            if data_type is IonStruct:
                for key,val in data.items():
                    new_val = process(val)
                    if new_val is not None:
                        data[key] = new_val

            return None

        if not (RETAIN_KDX_ID_ANNOT_IF_PURE and self.book.pure):
            process(data)

        return data

