from __future__ import (unicode_literals, division, absolute_import, print_function)

import copy
import hashlib

from .ion import (IonBLOB, IonAnnotation, IonStruct, IS)
from .ion_binary import (Deserializer, IonBinary, Serializer)
from .misc import (hex_string, json_deserialize, json_serialize_compact, type_name)
from .yj_container import (CONTAINER_FORMAT_KFX_MAIN, CONTAINER_FORMAT_KFX_METADATA,
            CONTAINER_FORMAT_KFX_ATTACHABLE, YJContainer, YJFragment, YJFragmentList,
            CONTAINER_FRAGMENT_TYPES, ROOT_FRAGMENT_TYPES, RAW_FRAGMENT_TYPES)
from .yj_symbol_catalog import SYSTEM_SYMBOL_TABLE

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

DEBUG = False

MAX_KFX_CONTAINER_SIZE = 16*1024*1024

DEFAULT_COMPRESSION_TYPE = 0
DEFAULT_DRM_SCHEME = 0

KFX_MAIN_CONTAINER_FRAGMENT_IDNUMS = {
    259,
    260,
    538,
    }

KFX_METADATA_CONTAINER_FRAGMENT_IDNUMS = {
    258,
    419,
    490,
    585,
    }

KFX_ATTACHABLE_CONTAINER_FRAGMENT_IDNUMS = {
    417,
    }

class KfxContainer(YJContainer):
    signature = b"CONT"
    drm_signature = IonBinary.drmion_signature
    version = 2
    allowed_versions = {1, 2}
    min_length = 18
    default_chunk_size = 4096

    def __init__(self, log, book, datafile=None, fragments=None):
        YJContainer.__init__(self, log, book, datafile=datafile, fragments=fragments)

    def deserialize(self, pure=False, ignore_drm=False):

        self.doc_symbols = None
        self.format_capabilities = None
        self.container_info = None
        self.entities = []
        self.fragments = YJFragmentList()

        data = self.datafile.get_data()

        if len(data) < KfxContainer.min_length:
            raise Exception("Container is too short (%d bytes)" % len(data))

        header = Deserializer(data)
        signature = header.unpack("4s")
        version = header.unpack("<H")
        header_len = header.unpack("<L")

        if signature != KfxContainer.signature:
            pdb_creator = data[64:68]
            if pdb_creator in [b"MOBI", b"CONT"]:
                raise Exception("Found a PDB %s container. This book is not in KFX format." % pdb_creator.decode("utf8"))

            raise Exception("Container signature is incorrect (%s)" % hex_string(signature))

        if version not in KfxContainer.allowed_versions:
            self.log.warning("Container version is incorrect (%d)" % version)

        if header_len < KfxContainer.min_length:
            raise Exception("Container header is too short (%d)" % header_len)

        container_info_offset = header.unpack(b"<L")
        container_info_length = header.unpack(b"<L")

        container_info_data = data[container_info_offset:container_info_offset + container_info_length]
        container_info = IonBinary(self.log, self.book.symtab).deserialize_single_value(container_info_data)
        if DEBUG: self.log.debug("container info:\n%s" % repr(container_info))

        container_id = container_info.pop("$409")

        compression_type = container_info.pop("$410", DEFAULT_COMPRESSION_TYPE)
        if compression_type != DEFAULT_COMPRESSION_TYPE:
            self.log.error("Unexpected bcComprType in container %s info: %s" % (container_id, repr(compression_type)))

        drm_scheme = container_info.pop("$411", DEFAULT_DRM_SCHEME)
        if drm_scheme != DEFAULT_DRM_SCHEME:
            self.log.error("Unexpected bcDRMScheme in container %s info: %s" % (container_id, repr(drm_scheme)))

        doc_symbol_offset = container_info.pop("$415", None)
        doc_symbol_length = container_info.pop("$416", 0)
        if doc_symbol_length:
            doc_symbol_data = data[doc_symbol_offset:doc_symbol_offset + doc_symbol_length]
            self.doc_symbols = IonBinary(self.log, self.book.symtab, import_symbols=False).deserialize_annotated_value(
                    doc_symbol_data, expect_annotation="$3")
            if DEBUG: self.log.debug("Document symbols:\n%s" % repr(self.doc_symbols))

            for sym_import in self.doc_symbols.value["$6"]:
                if "$8" in sym_import:
                    sym_import["$8"] -= len(SYSTEM_SYMBOL_TABLE.symbols)

            self.book.symtab.create_symbol_table("$3", self.doc_symbols.value)

        chunk_size = container_info.pop("$412", 0)
        if chunk_size != KfxContainer.default_chunk_size:
            self.log.warning("Unexpected bcChunkSize in container %s info: %d" % (chunk_size, container_id))

        if version > 1:
            format_capabilities_offset = container_info.pop("$594", None)
            format_capabilities_length = container_info.pop("$595", 0)
            if format_capabilities_length:
                format_capabilities_data = data[format_capabilities_offset:format_capabilities_offset + format_capabilities_length]
                self.format_capabilities = IonBinary(self.log, self.book.symtab).deserialize_annotated_value(
                    format_capabilities_data, expect_annotation="$593")
                if DEBUG: self.log.debug("Format capabilities:\n%s" % repr(self.format_capabilities))

        type_idnums = set()
        index_table_offset = container_info.pop("$413", None)
        index_table_length = container_info.pop("$414", 0)
        if index_table_length:
            entity_table = Deserializer(data[index_table_offset:index_table_offset + index_table_length])

            while len(entity_table):
                id_idnum = entity_table.unpack("<L")
                type_idnum = entity_table.unpack("<L")
                entity_offset = entity_table.unpack("<Q")
                entity_len = entity_table.unpack("<Q")

                type_idnums.add(type_idnum)

                entity_start = header_len + entity_offset
                if DEBUG: self.log.debug("Container entity: id=%d type=%d len=%d" % (
                                id_idnum, type_idnum, entity_len))

                if entity_start + entity_len > len(data):
                    raise Exception("Container (%d bytes) is not large enough for entity end (offset %d)" % (
                                len(data), entity_start + entity_len))

                self.entities.append(KfxContainerEntity(self.log, self.book.symtab, id_idnum, type_idnum,
                            serialized_data=data[entity_start:entity_start + entity_len], pure=pure))

        if len(container_info):
            self.log.error("container_info has extra data: %s" % repr(container_info))

        payload_sha1 = hex_string(sha1(data[header_len:]), sep="").encode("ascii")

        kfxgen_package_version = ""
        kfxgen_application_version = ""

        kfxgen_info_data = data[container_info_offset + container_info_length:header_len]
        kfxgen_info_json = (kfxgen_info_data.replace(b"key :",b"\"key\":").replace(b"key:",b"\"key\":")
                            .replace(b"value:",b"\"value\":").replace(chr(27), b""))

        try:
            kfxgen_info = json_deserialize(kfxgen_info_json)
        except:
            self.log.info("Exception decoding json: %s" % kfxgen_info_json)
            raise

        for info in kfxgen_info:
            key = info.pop("key")
            value = info.pop("value")

            if key in {"appVersion", "kfxgen_application_version"}:
                kfxgen_application_version = value

            elif key in {"buildVersion", "kfxgen_package_version"}:
                kfxgen_package_version = value

            elif key == "kfxgen_payload_sha1":
                if value != payload_sha1:
                    self.log.error("Incorrect kfxgen_payload_sha1 in container %s: %s should be %s" % (
                            container_id, value, payload_sha1))

            elif key == "kfxgen_acr":
                if value != container_id:
                    self.log.error("Unexpected kfxgen_acr in container %s: %s" % (container_id, value))

            else:
                self.log.error("kfxgen_info has unknown key: %s = %s" % (key, value))

            if len(info):
                self.log.error("kfxgen_info has extra data: %s" % repr(self.log, info))

        if type_idnums & KFX_MAIN_CONTAINER_FRAGMENT_IDNUMS:
            container_format = CONTAINER_FORMAT_KFX_MAIN
        elif (type_idnums & KFX_METADATA_CONTAINER_FRAGMENT_IDNUMS) or (doc_symbol_length > 0):
            container_format = CONTAINER_FORMAT_KFX_METADATA
        elif type_idnums & KFX_ATTACHABLE_CONTAINER_FRAGMENT_IDNUMS:
            container_format = CONTAINER_FORMAT_KFX_ATTACHABLE
        else:
            self.log.error("Cannot determine KFX container type of %s" % container_id)
            container_format = "KFX unknown"

        self.container_info = IonAnnotation([IS("$270")], IonStruct(
                IS("$409"), container_id,
                IS("$412"), chunk_size,
                IS("$410"), compression_type,
                IS("$411"), drm_scheme,
                IS("$587"), kfxgen_application_version,
                IS("$588"), kfxgen_package_version,
                IS("$161"), container_format,
                IS("$5"), version,
                IS("$181"), [[e.type_idnum, e.id_idnum] for e in self.entities]))

        self.container_id = container_id

    def get_fragments(self):
        if not self.fragments:

            for data in [self.doc_symbols, self.container_info, self.format_capabilities]:
                if data is not None:
                    self.fragments.append(YJFragment(data))

            for entity in self.entities:
                self.fragments.append(entity.deserialize())

        return self.fragments

    def serialize(self):

        container_id = None
        kfxgen_package_version = ""
        kfxgen_application_version = ""
        doc_symbols = None
        format_capabilities = None

        container_cnt = format_capabilities_cnt = ion_symbol_table_cnt = container_entity_map_cnt = 0

        for fragment in self.get_fragments():
            if fragment.ftype == "$270":
                container_cnt += 1
                container_id = fragment.value.get("$409", "")
                kfxgen_application_version = fragment.value.get("$587", "")
                kfxgen_package_version = fragment.value.get("$588", "")

            elif fragment.ftype == "$593":
                format_capabilities_cnt += 1
                format_capabilities = fragment

            elif fragment.ftype == "$3":
                ion_symbol_table_cnt += 1
                doc_symbols = fragment

                doc_symbols = YJFragment(doc_symbols.annotations, value=copy.deepcopy(doc_symbols.value))
                for sym_import in doc_symbols.value["$6"]:
                    if "$8" in sym_import:
                        sym_import["$8"] += len(SYSTEM_SYMBOL_TABLE.symbols)

            elif fragment.ftype == "$419":
                container_entity_map_cnt += 1

        if container_cnt != 1 or format_capabilities_cnt > 1 or ion_symbol_table_cnt != 1 or container_entity_map_cnt != 1:
            self.log.error("Missing/extra fragments required to build KFX container: "
                "container=%d format_capabilities=%d ion_symbol_table=%d container_entity_map=%d" % (
                    container_cnt, format_capabilities_cnt, ion_symbol_table_cnt, container_entity_map_cnt))

        entities = []
        for fragment in self.fragments:
            if (fragment.ftype not in CONTAINER_FRAGMENT_TYPES) or (fragment.ftype == "$419"):
                entities.append(KfxContainerEntity(self.log, self.book.symtab,
                        id_idnum=self.book.symtab.get_id(IS("$348") if fragment.is_single() else fragment.fid),
                        type_idnum=self.book.symtab.get_id(fragment.ftype), value=fragment.value))

        container = Serializer()
        container.pack("4s", KfxContainer.signature)
        container.pack("<H", KfxContainer.version)
        header_len_pack = container.pack("<L", 0)
        container_info_offset_pack = container.pack(b"<L", 0)
        container_info_length_pack = container.pack(b"<L", 0)

        container_info = IonStruct()
        container_info[IS("$409")] = container_id
        container_info[IS("$410")] = DEFAULT_COMPRESSION_TYPE
        container_info[IS("$411")] = DEFAULT_DRM_SCHEME

        entity_data = Serializer()
        entity_table = Serializer()
        entity_offset = 0
        for entity in entities:
            serialized_entity = entity.serialize()
            entity_data.append(serialized_entity)
            entity_len = len(serialized_entity)
            entity_table.pack(b"<L", entity.id_idnum)
            entity_table.pack(b"<L", entity.type_idnum)
            entity_table.pack(b"<Q", entity_offset)
            entity_table.pack(b"<Q", entity_len)
            entity_offset += entity_len

        container_info[IS("$413")] = len(container)
        container_info[IS("$414")] = len(entity_table)
        container.append(entity_table.serialize())

        if doc_symbols is not None:
            doc_symbol_data = IonBinary(self.log, self.book.symtab).serialize_single_value(doc_symbols)
        else:
            doc_symbol_data = b""

        container_info[IS("$415")] = len(container)
        container_info[IS("$416")] = len(doc_symbol_data)
        container.append(doc_symbol_data)

        container_info[IS("$412")] = KfxContainer.default_chunk_size

        if format_capabilities is not None:
            format_capabilities_data = IonBinary(self.log, self.book.symtab).serialize_single_value(format_capabilities)
        else:
            format_capabilities_data = b""

        if self.book.symtab.local_min_id > 595:

            container_info[IS("$594")] = len(container)
            container_info[IS("$595")] = len(format_capabilities_data)
            container.append(format_capabilities_data)

        container_info_data = IonBinary(self.log, self.book.symtab).serialize_single_value(container_info)
        container.repack(container_info_length_pack, len(container_info_data))
        container.repack(container_info_offset_pack, len(container))
        container.append(container_info_data)

        kfxgen_info = [
            IonStruct("key", "kfxgen_package_version", "value", kfxgen_package_version),
            IonStruct("key", "kfxgen_application_version", "value", kfxgen_application_version),
            IonStruct("key", "kfxgen_payload_sha1", "value", hex_string(entity_data.sha1(), sep="")),
            IonStruct("key", "kfxgen_acr", "value", container_id),
            ]
        container.append(json_serialize_compact(kfxgen_info).
                replace("\"key\":","key:",).replace("\"value\":", "value:").encode("ascii"))

        container.repack(header_len_pack, len(container))

        container.extend(entity_data)

        return container.serialize()

class KfxContainerEntity(object):
    signature = b"ENTY"
    version = 1
    allowed_versions = {1}
    min_length = 10

    def __init__(self, log, symtab, id_idnum=None, type_idnum=None, value=None, serialized_data=None, pure=False):
        self.log  = log
        self.symtab = symtab
        self.id_idnum = id_idnum
        self.type_idnum = type_idnum
        self.value = value
        self.serialized_data = serialized_data
        self.pure = pure

    def deserialize(self, data=None):
        if data is None: data = self.serialized_data

        cont_entity = Deserializer(data)
        signature = cont_entity.unpack("4s")
        version = cont_entity.unpack("<H")
        header_len = cont_entity.unpack("<L")

        if signature != KfxContainerEntity.signature:
            raise Exception("Container entity signature is incorrect (%s)" % hex_string(signature))

        if version not in KfxContainerEntity.allowed_versions:
            self.log.warning("Container entity version is incorrect (%d)" % version)

        if header_len < KfxContainerEntity.min_length:
            raise Exception("Container entity header is too short (%d)" % header_len)

        self.header = data[:header_len]

        entity_info = IonBinary(self.log, self.symtab).deserialize_single_value(cont_entity.extract(upto=header_len))
        compression_type = entity_info.pop("$410", DEFAULT_COMPRESSION_TYPE)
        drm_scheme = entity_info.pop("$411", DEFAULT_DRM_SCHEME)

        if compression_type != DEFAULT_COMPRESSION_TYPE:
            self.log.error("Container entity %s has unexpected bcComprType: %s" % (
                        repr(self), repr(compression_type)))

        if drm_scheme != DEFAULT_DRM_SCHEME:
            self.log.error("Container entity %s has unexpected bcDRMScheme: %s" % (
                        repr(self), repr(drm_scheme)))

        if len(entity_info):
            raise Exception("Container entity %s info has extra data: %s" % (
                        repr(self), repr(entity_info)))

        entity_data = cont_entity.extract()

        fid = self.symtab.get_symbol(self.id_idnum)
        ftype = self.symtab.get_symbol(self.type_idnum)

        if ftype in RAW_FRAGMENT_TYPES:
            self.value = IonBLOB(entity_data)
        else:
            self.value = IonBinary(self.log, self.symtab).deserialize_single_value(entity_data)

        if isinstance(self.value, IonAnnotation):
            if len(self.value.annotations) == 1 and self.value.annotations[0] == ftype and fid == "$348":

                fid = self.value.annotations[0]
                self.value = self.value.value
            else:
                self.log.error("Entity %s has IonAnnotation as value: %s" % (repr(self), repr(self.value)))

        if ftype == fid and ftype in ROOT_FRAGMENT_TYPES and not self.pure:

            fid = "$348"

        return YJFragment(fid=fid if fid != "$348" else None, ftype=ftype, value=self.value)

    def serialize(self):
        entity = Serializer()
        entity.pack("4s", KfxContainerEntity.signature)
        entity.pack("<H", KfxContainerEntity.version)
        header_len_pack = entity.pack("<L", 0)

        entity_info = IonStruct()
        entity_info[IS("$410")] = DEFAULT_COMPRESSION_TYPE
        entity_info[IS("$411")] = DEFAULT_DRM_SCHEME
        entity.append(IonBinary(self.log, self.symtab).serialize_single_value(entity_info))

        entity.repack(header_len_pack, len(entity))

        ftype = self.symtab.get_symbol(self.type_idnum)
        if ftype in RAW_FRAGMENT_TYPES:
            if isinstance(self.value, IonBLOB):
                entity.append(str(self.value))
            else:
                raise Exception("KfxContainerEntity %s must be IonBLOB, found %s" % (ftype, type_name(self.value)))
        else:
            entity.append(IonBinary(self.log, self.symtab).serialize_single_value(self.value))

        return entity.serialize()

    def __repr__(self):
        return b"$%d/$%d" % (self.type_idnum, self.id_idnum)

def sha1(data):
    return hashlib.sha1(data).digest()

