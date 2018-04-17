from __future__ import (unicode_literals, division, absolute_import, print_function)

import collections
import random
import re
import string

from .ion import (
            ion_type, ion_data_eq, IonAnnotation, IonInt, IonList, IonSExp, IonString,
            IonStruct, IonSymbol, IS)
from .kfx_container import KfxContainer
from .misc import (list_symbols, list_truncated, natural_sort_key, type_name, UUID_MATCH_RE)
from .yj_container import (CONTAINER_FORMAT_KFX_MAIN, YJFragment, YJFragmentKey, YJFragmentList,
            ALLOWED_BOOK_FRAGMENT_TYPES, CONTAINER_FRAGMENT_TYPES, KNOWN_FRAGMENT_TYPES,
            REQUIRED_BOOK_FRAGMENT_TYPES, ROOT_FRAGMENT_TYPES, SINGLETON_FRAGMENT_TYPES)
from .yj_versions import is_known_aux_metadata

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

REPORT_KNOWN_PROBLEMS = None

MAX_CONTENT_FRAGMENT_SIZE = 8192

APPROXIMATE_PAGE_LIST = "APPROXIMATE_PAGE_LIST"
KFX_COVER_RESOURCE = "kfx_cover_image"

DICTIONARY_RULES_SYMBOL = "dictionary_rules"

METADATA_SYMBOLS = {
    "ASIN": "$224",
    "asset_id": "$466",
    "author": "$222",
    "cde_content_type": "$251",
    "cover_image": "$424",
    "description": "$154",
    "language": "$10",
    "orientation": "$215",
    "publisher": "$232",
    "reading_orders": "$169",
    "support_landscape": "$218",
    "support_portrait": "$217",
    "title": "$153",
    }

METADATA_NAMES = {}
for k,v in METADATA_SYMBOLS.items(): METADATA_NAMES[v] = k

FORMAT_SYMBOLS = {
    "bmp": "$599",
    "gif": "$286",
    "jpg": "$285",
    "jxr": "$548",
    "pbm": "$420",
    "pdf": "$565",
    "png": "$284",
    "pobject": "$287",
    "tiff": "$600",
    "yj.bpg": "$612",
    }

SYMBOL_FORMATS = {}
for k,v in FORMAT_SYMBOLS.items(): SYMBOL_FORMATS[v] = k

FRAGMENT_ID_KEYS = {
    "$266": ["$180"],
    "$597": ["$174", "$598"],
    "$418": ["$165"],
    "$417": ["$165"],
    "$394": ["$240"],
    "$145": ["$4"],
    "$164": ["$175"],
    "$391": ["$239"],
    "$692": ["$4"],
    "$387": ["$174"],
    "$260": ["$174"],
    "$267": ["$174"],
    "$609": ["$174"],
    "$259": ["$176"],
    "$608": ["$598"],
    "$157": ["$173"],
    "$610": ["$602"],
    }

COMMON_REFERENCES = {
    "$266": "$266",
    "$597": "$597",
    "$429": "$157",
    "$479": "$164",
    "$145": "$145",
    "$146": "$608",
    "$245": "$164",
    "$179": "$266",
    "$165": "$417",
    "$392": "$391",
    "$4": "$145",
    "$167": "$164",
    "$175": "$164",
    "$174": "$260",
    "$170": "$260",
    "$176": "$259",
    "$157": "$157",
    "$173": "$157",
    "$214": "$164",
    "$636": "$417",
    "$635": "$164",
    }

SPECIAL_FRAGMENT_REFERENCES = {
    "$391": {
        "$247": "$394",
        },
    "$387": {
        "$213": "$164",
        "$214": "$164",
        "$212": "$164",
        },
    }

SPECIAL_PARENT_FRAGMENT_REFERENCES = {
    "$538": {
        "$597": "$597",
        },
    }

SECTION_DATA_TYPES = {
    "$387",
    "$260",
    "$267",
    "$609",
    }

EXPECTED_ANNOTATIONS = {
    ("$164", "$214", "$164"),
    ("$389", "$247", "$393"),
    ("$389", "$392", "$391"),
    ("$259", "$429", "$157"),
    ("$259", "$173", "$157"),
    }

EXPECTED_DICTIONARY_ANNOTATIONS = {
    ("$260", "$141", "$608"),
    ("$259", "$146", "$608"),
    }

class BookStructure(object):
    def get_default_reading_order(self):
        document_data = self.fragments.get("$538", first=True)
        if document_data is None:
            document_data = self.fragments.get("$258", first=True)

        if document_data is not None:
            reading_orders = document_data.value.get("$169", [])
            for reading_order in reading_orders:
                if len(reading_orders) == 1 or reading_order["$178"] == "default":
                    return (reading_order["$178"], reading_order.get("$170", []))

        return (None, [])

    def extract_section_story_names(self, section_name):
        story_names = []

        def _extract_story_names(data):
            data_type = ion_type(data)

            if data_type is IonAnnotation:
                _extract_story_names(data.value)

            elif data_type is IonList or data_type is IonSExp:
                for fc in data:
                    _extract_story_names(fc)

            elif data_type is IonStruct:
                for fk,fv in data.items():
                    if fk == "$176":
                        if fv not in story_names:
                            story_names.append(fv)
                    else:
                        _extract_story_names(fv)

        _extract_story_names(self.fragments[YJFragmentKey(ftype="$260", fid=section_name)])
        return story_names

    def check_consistency(self):
        fragment_id_types = collections.defaultdict(set)
        for fragment in self.fragments:
            if fragment.ftype in ROOT_FRAGMENT_TYPES:
                if not fragment.is_single():
                    self.log.error("Fragment type %s has unexpected id %s" % (fragment.ftype, fragment.fid))
            else:
                if fragment.ftype == fragment.fid:
                        self.log.error("Fragment type %s has unexpected id %s" % (fragment.ftype, fragment.fid))

            if fragment.ftype in FRAGMENT_ID_KEYS:

                value_fid = None

                if ion_type(fragment.value) is IonStruct:
                    for id_key in FRAGMENT_ID_KEYS[fragment.ftype]:
                        if id_key in fragment.value:
                            value_fid = fragment.value[id_key]

                            if fragment.ftype == "$609" and (self.is_dictionary or self.is_kpf_prepub):
                                value_fid = IS(unicode(value_fid) + "-spm")
                            elif fragment.ftype == "$610" and isinstance(value_fid, int):
                                value_fid = IonSymbol("eidbucket_%d" % value_fid)
                            break

                    if fragment.fid != value_fid:
                        self.log.error("Fragment type %s has unexpected id %s instead of %s" % (
                                    fragment.ftype, fragment.fid, value_fid))

            fragment_id_types[fragment.fid].add(fragment.ftype)

        for fid,ftypes in fragment_id_types.items():

            if len(ftypes) > 1 and (len(ftypes - SECTION_DATA_TYPES) > 0 or self.is_dictionary or self.is_kpf_prepub):
                self.log.error("Book contains same fragment id %s with multiple types %s" % (fragment.fid, list_symbols(ftypes)))

        for ftype in SINGLETON_FRAGMENT_TYPES:
            if len(self.fragments.get_all(ftype)) > 1:
                self.log.error("Multiple %s fragments present (only one expected per book)" % ftype)

        containers = {}
        for fragment in self.fragments.get_all("$270"):
            if "$409" in fragment.value:
                container_id = fragment.value["$409"]
                containers[container_id] = fragment

                if fragment.value["$161"] == CONTAINER_FORMAT_KFX_MAIN and not self.is_magazine:

                    asset_id = self.get_asset_id()
                    if asset_id and asset_id != container_id:
                        self.log.error("asset_id (%s) != main container_id (%s)" % (asset_id, container_id))

        container_entity_map = self.fragments.get("$419", first=True)
        if container_entity_map is not None:
            cem_container_ids = set()

            for cem_container_info in container_entity_map.value["$252"]:
                container_id = cem_container_info["$155"]
                cem_container_ids.add(container_id)
                cem_fragment_ids = set(cem_container_info.get("$181", []))

                if cem_fragment_ids:
                    container = containers.get(container_id)
                    if container is not None and "$181" in container.value:

                        container_fragment_ids = set([self.symtab.get_symbol(e[1]) for e in container.value["$181"] if e[0] != e[1]])

                        missing_fids = (cem_fragment_ids - container_fragment_ids) - {"$348"}
                        if missing_fids:
                            self.log_known_error("Entity map references missing fragments in %s: %s" % (
                                    container_id, list_truncated(missing_fids)))

                        extra_fids = (container_fragment_ids - cem_fragment_ids) - {"$348"}
                        if extra_fids:
                            self.log.error("Found fragments in %s missing from entity map: %s" % (container_id, list_truncated(extra_fids)))

            actual_container_ids = set(containers.keys())
            missing_container_ids = cem_container_ids - actual_container_ids
            if missing_container_ids:
                raise Exception("Book is incomplete. All of the KFX container files that make up the book must be combined "
                            "into a KFX-ZIP file for successful conversion. (Missing containers %s)" %
                                   list_symbols(list(missing_container_ids)))
                self.log.error("Entity map references missing containers: %s" % list_symbols(missing_container_ids))

            extra_ids = actual_container_ids - cem_container_ids
            if extra_ids:
                self.log.error("Found containers missing from entity map: %s" % list_symbols(extra_ids))

        required_ftypes = REQUIRED_BOOK_FRAGMENT_TYPES.copy()
        allowed_ftypes = ALLOWED_BOOK_FRAGMENT_TYPES.copy()
        present_ftypes = self.fragments.ftypes()

        if self.is_dictionary or self.is_kpf_prepub:
            required_ftypes.remove("$419")
            required_ftypes.remove("$265")
            required_ftypes.remove("$264")
        else:
            required_ftypes.remove("$611")

            if self.get_feature_value("kfxgen.positionMaps", namespace="format_capabilities") != 2:
                allowed_ftypes.remove("$609")
                allowed_ftypes.remove("$621")

        if not self.is_kpf_prepub:
            allowed_ftypes.remove("$610")

        if self.is_dictionary or self.is_magazine or self.is_textbook:
            required_ftypes.remove("$550")

            if not self.is_dictionary:
                allowed_ftypes.discard("$621")

        if not self.is_magazine:
            allowed_ftypes.remove("$267")
            allowed_ftypes.remove("$390")

        if self.is_kfx_v1:
            required_ftypes.remove("$538")
            required_ftypes.discard("$265")

        allowed_ftypes.update(required_ftypes)

        if "$490" in present_ftypes:
            required_ftypes.remove("$258")
        elif "$258" in present_ftypes:
            required_ftypes.remove("$490")

        missing_ftypes = required_ftypes - present_ftypes
        if missing_ftypes:
            missing_ft = list_symbols(missing_ftypes)

            if missing_ftypes == {"$389"}:
                self.log.warning("Book incomplete. Missing %s" % missing_ft)
            else:
                raise Exception("Book is incomplete. All of the KFX container files that make up the book must be combined "
                            "into a KFX-ZIP file for successful conversion. (Missing fragments %s)" % missing_ft)
                self.log.error("Book incomplete. Missing %s" % missing_ft)

        extra_ftypes = present_ftypes - allowed_ftypes
        if extra_ftypes:
            self.log.warning("Book has unexpected fragment types: %s" % list_symbols(extra_ftypes))

        has_content_fragment = False
        for fragment in self.fragments.get_all("$145"):
            has_content_fragment = True
            content_bytes = 0
            for content in fragment.value["$146"][:-1]:
                content_bytes += len(content.encode("utf8"))

            if content_bytes >= MAX_CONTENT_FRAGMENT_SIZE:
                self.log.error("Content %s: %d bytes exceeds maximum (%d bytes)" % (
                    fragment.fid, content_bytes, MAX_CONTENT_FRAGMENT_SIZE))

        for fragment in self.fragments.get_all("$395"):
            if len(fragment.value["$247"]) > 0 and not self.is_magazine:
                self.log.warning("resource_path of %s contains entries" % self.cde_type)

        is_sample = self.get_metadata_value("is_sample", default=False)
        if (self.cde_type == "EBSP") is not is_sample:
            self.log.warning("Feature/content mismatch: cde_type=%s, is_sample=%s" % (self.cde_type, is_sample))

        has_hdv_image = False
        for fragment in self.fragments.get_all("$164"):
            location = fragment.value.get("$165", None)
            if location is not None and ion_type(location) is not IonString:
                self.log.error("resource %s location is type %s" % (unicode(fragment.fid), type_name(location)))

            if not self.is_fixed_layout:

                resource_height = fragment.value.get("$423", 0)
                resource_width = fragment.value.get("$422", 0)

                if resource_height > 1920 or resource_width > 1920:

                    has_hdv_image = True

        if not self.is_sample:
            yj_hdv = self.get_feature_value("yj_hdv")
            if has_hdv_image and yj_hdv is None:
                self.log.warning("HDV image detected without yj_hd feature")

        has_textBlock = False
        format_capability_sets = set()
        for fragment in self.fragments.get_all("$593"):
            fcxs = []
            for fc in fragment.value:
                fcxs.append((fc["$492"], fc["$5"]))

            if ("kfxgen.textBlock", 1) in fcxs:
                has_textBlock = True

            format_capability_sets.add(tuple(sorted(fcxs)))

        if len(format_capability_sets) > 1:
            self.log.error("Book has %d different format capabilities" % len(format_capability_sets))
            self.log.info(unicode(format_capability_sets))

        if has_textBlock is not has_content_fragment:
            self.log.error("textBlock=%s content_fragment=%s" % (has_textBlock, has_content_fragment))

        for fragment in self.fragments.get_all("$597"):
            if len(set(fragment.value.keys()) - {"$258", "$598"}) > 0:
                self.log.error("Malformed auxiliary_data: %s" % repr(fragment))
            else:
                for kv in fragment.value.get("$258", []):
                    if len(kv) != 2 or "$492" not in kv or "$307" not in kv:
                        self.log.error("Malformed auxiliary_data value: %s" % repr(fragment))
                    else:
                        key = kv.get("$492", "")
                        value = kv.get("$307", "")
                        if not is_known_aux_metadata(key, value):
                            self.log.warning("Unknown auxiliary_data: %s=%s" % (key, value))

        asin = self.get_metadata_value("ASIN")
        content_id = self.get_metadata_value("content_id")
        if asin and content_id and content_id != asin:
            self.log.error("content_id (%s) != ASIN (%s)" % (content_id, asin))

        self.check_position_and_location_maps()

    def extract_fragment_id_from_value(self, ftype, value):
        if ion_type(value) is IonStruct and ftype in FRAGMENT_ID_KEYS:
            for id_key in FRAGMENT_ID_KEYS[ftype]:
                if id_key in value:
                    fid = value[id_key]

                    if ftype == "$609" and (self.is_dictionary or self.is_kpf_prepub):
                        fid = IS(unicode(fid) + "-spm")
                    elif ftype == "$610" and isinstance(fid, int):
                        fid = IonSymbol("eidbucket_%d" % fid)

                    return fid

        return ftype

    def check_fragment_usage(self, rebuild=False, ignore_extra=False):
        discovered = set()

        unreferenced_fragment_types = ROOT_FRAGMENT_TYPES - {"$419"}

        if self.is_kpf_prepub:
            unreferenced_fragment_types.add("$610")

        for fragment in self.fragments:
            if fragment.ftype in unreferenced_fragment_types:
                discovered.add(fragment)
                if fragment.ftype == "$490":
                    for cm in fragment.value["$491"]:
                        if cm["$495"] == "kindle_title_metadata":
                            for kv in cm["$258"]:
                                if kv["$492"] == "cover_image":
                                    fid = kv["$307"]
                                    discovered.add(YJFragmentKey(ftype="$164",
                                        fid=(fid if isinstance(fid, IonSymbol) else IS(fid))))

                if fragment.ftype == "$258" and "$424" in fragment.value:
                    discovered.add(YJFragmentKey(ftype="$164", fid=fragment.value["$424"]))

            if fragment.ftype not in KNOWN_FRAGMENT_TYPES:
                discovered.add(fragment)

        visited = set()
        mandatory_references = {}
        optional_references = {}
        missing = set()

        for ftype in CONTAINER_FRAGMENT_TYPES:
            visited.add(YJFragmentKey(ftype=ftype))

        while discovered:
            next_visits = discovered - visited
            discovered = set()

            for fragment in self.fragments:
                if fragment in next_visits:
                    mandatory_refs = set()
                    optional_refs = set()

                    self.walk_fragment(fragment, mandatory_refs, optional_refs, set())

                    visited.add(fragment)
                    mandatory_references[fragment] = mandatory_refs
                    optional_references[fragment] = optional_refs
                    discovered |= mandatory_refs | optional_refs

            missing |= (next_visits - visited)

        for key in missing:
            self.log.error("Referenced fragment %s is missing from book" % unicode(key))

        referenced_fragments = YJFragmentList()
        unreferenced_fragments = YJFragmentList()
        already_processed = {}
        diff_dupe_fragments = False

        for fragment in self.fragments:
            if fragment.ftype not in ["$262", "$387"]:
                if fragment in already_processed:
                    if fragment.ftype in ["$270", "$593"]:
                        continue

                    if ion_data_eq(fragment.value, already_processed[fragment].value):
                        if fragment.ftype == "$597":
                            self.log_known_error("Duplicate fragment: %s" % unicode(fragment))
                        else:
                            self.log.error("Duplicate fragment: %s" % unicode(fragment))
                        continue
                    else:
                        self.log.error("Duplicate fragment key with different content: %s" % unicode(fragment))
                        diff_dupe_fragments = True
                else:
                    already_processed[fragment] = fragment

            if fragment in visited:
                referenced_fragments.append(fragment)
            elif (fragment.ftype in CONTAINER_FRAGMENT_TYPES) or (fragment.fid == fragment.ftype):
                self.log.error("Unexpected root fragment: %s" % unicode(fragment))
            elif fragment.ftype == "$597" and (self.is_sample or self.is_dictionary):
                pass
            elif not ignore_extra:
                unreferenced_fragments.append(fragment)

        if unreferenced_fragments:

            self.log.error("Unreferenced fragments: %s" % list_truncated(unreferenced_fragments))

        if diff_dupe_fragments:
            raise Exception("Book appears to have KFX containers from multiple books. (duplicate fragments)")
            pass

        if rebuild:
            if not self.is_dictionary:

                container_ids = set()
                kfxgen_application_version = kfxgen_package_version = version = None
                for fragment in self.fragments.get_all("$270"):
                    container_id_ = fragment.value.get("$409", "")
                    if container_id_:
                        container_ids.add(container_id_)

                    kfxgen_application_version = fragment.value.get("$587") or kfxgen_application_version
                    kfxgen_package_version = fragment.value.get("$588") or kfxgen_package_version
                    version = fragment.value.get("$5") or version
                    referenced_fragments.discard(fragment)

                if len(container_ids) == 1:
                    container_id = list(container_ids)[0]
                else:
                    container_id = self.get_asset_id()

                if not container_id:
                    container_id = self.create_container_id()

                referenced_fragments.append(YJFragment(ftype="$270", value=IonStruct(
                    IS("$409"), container_id,
                    IS("$161"), CONTAINER_FORMAT_KFX_MAIN,
                    IS("$587"), kfxgen_application_version or "",
                    IS("$588"), kfxgen_package_version or "",
                    IS("$5"), version or KfxContainer.version)))

            self.fragments = YJFragmentList(sorted(referenced_fragments))

            if not self.is_dictionary:
                self.rebuild_container_entity_map(container_id, self.determine_entity_dependencies(mandatory_references, optional_references))

    def create_container_id(self):
        return "CR!%s" % "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(28))

    def walk_fragment(self, fragment, m_r, o_r, eids):

        def walk(data, container=None, container_parent=None, top_level=False):
            data_type = ion_type(data)

            if container is None:
                container = fragment.ftype

            if data_type is IonAnnotation:
                if not top_level:
                    for annot in data.annotations:
                        if ((fragment.ftype, container, annot) not in EXPECTED_ANNOTATIONS and
                                (self.is_dictionary and (fragment.ftype, container, annot) not in EXPECTED_DICTIONARY_ANNOTATIONS)):
                            self.log_error_once("Found unexpected IonAnnotation %s in %s of %s fragment" % (annot, container, fragment.ftype))

                walk(data.value, container, container_parent)

            elif data_type is IonList:
                for fc in data:
                    walk(fc, container, container_parent)

            elif data_type is IonStruct:
                for fk,fv in data.items():
                    walk(fv, fk, container)

            elif data_type is IonSExp:
                for fc in data[1:]:
                    walk(fc, data[0], container)

            elif data_type is IonString:
                if container in ["$165", "$636"]:
                    walk(IS(data), container, container_parent)

            elif data_type is IonSymbol:
                if container == "$155":
                    eids.add(data)

                frag_ref = None

                special_refs = SPECIAL_FRAGMENT_REFERENCES.get(fragment.ftype)
                if special_refs is not None and container in special_refs:
                    frag_ref = special_refs[container]

                if frag_ref is None:
                    special_refs = SPECIAL_PARENT_FRAGMENT_REFERENCES.get(fragment.ftype)
                    if special_refs is not None and container_parent is not None and container_parent in special_refs:
                        frag_ref = special_refs[container_parent]

                if frag_ref is None:
                    frag_ref = COMMON_REFERENCES.get(container)

                if frag_ref is not None:
                    if container == "$4" and container_parent in ["$249", "$692"]:
                        m_r.add(YJFragmentKey(ftype="$692", fid=data))
                    elif (container == "$165" and self.fragments.get(ftype="$418", fid=data) is not None):
                        m_r.add(YJFragmentKey(ftype="$418", fid=data))
                    elif container == "$635":
                        o_r.add(YJFragmentKey(ftype=frag_ref, fid=data))
                    else:
                        m_r.add(YJFragmentKey(ftype=frag_ref, fid=data))

                    if frag_ref == "$260":

                        for ref_key in [YJFragmentKey(ftype="$609", fid=data),
                                        YJFragmentKey(ftype="$609", fid=data + "-spm"),
                                        YJFragmentKey(ftype="$597", fid=data + "-ad"),
                                        YJFragmentKey(ftype="$597", fid=data),
                                        YJFragmentKey(ftype="$267", fid=data),
                                        YJFragmentKey(ftype="$387", fid=data)]:
                            if self.fragments.get(ref_key, first=True) is not None:
                                m_r.add(ref_key)

            elif data_type is IonInt:
                if container == "$155":
                    eids.add(data)

        try:
            walk(fragment, top_level=True)
        except Exception:
            self.log.info("Exception processing fragment: %s" % repr(fragment))
            raise

    def determine_entity_dependencies(self, mandatory_references, optional_references):
        deep_references = {}

        for fragment, refs in mandatory_references.items():
            if fragment.ftype == "$387":
                mandatory_references[fragment] = set()

        for fragment, refs in mandatory_references.items():
            old_refs = set()
            new_refs = set(refs)

            if fragment.ftype == "$164":
                for n_fragment in list(new_refs):
                    if n_fragment.ftype == "$164":
                        new_refs.remove(n_fragment)

            while len(new_refs - old_refs) > 0:
                old_refs = old_refs | new_refs
                new_refs = set(old_refs)
                for ref in old_refs:
                    new_refs |= mandatory_references.get(ref, set())

            deep_references[fragment] = new_refs

        entity_dependencies = []

        for fragment in sorted(deep_references):
            mandatory_dependencies = []
            optional_dependencies = []

            for depends, dependant in [("$260", "$164"),
                                    ("$164", "$417")]:
                if fragment.ftype == depends:
                    for ref_fragment in sorted(deep_references[fragment]):
                        if ref_fragment.ftype == dependant:
                            mandatory_dependencies.append(ref_fragment.fid)

                            opt = optional_references.get(ref_fragment, [])
                            for opt_ref_fragment in sorted(opt):
                                if opt_ref_fragment.ftype == dependant:
                                    optional_dependencies.append(opt_ref_fragment.fid)

            if mandatory_dependencies:
                entity_dependencies.append(IonStruct(
                            IS("$155"), fragment.fid,
                            IS("$254"), mandatory_dependencies))

            if optional_dependencies:
                entity_dependencies.append(IonStruct(
                            IS("$155"), fragment.fid,
                            IS("$255"), optional_dependencies))

        return entity_dependencies

    def rebuild_container_entity_map(self, container_id, entity_dependencies=None):

        old_entity_dependencies = None
        new_fragments = YJFragmentList()
        entity_ids = []

        for fragment in self.fragments:
            if fragment.ftype == "$419":
                container_entity_map = fragment.value
                old_entity_dependencies = container_entity_map.get("$253", None)
            else:
                new_fragments.append(fragment)

                if fragment.ftype not in CONTAINER_FRAGMENT_TYPES and fragment.fid != fragment.ftype:
                    entity_ids.append(fragment.fid)

        if entity_dependencies is None:
            entity_dependencies = old_entity_dependencies

        container_contents = IonStruct(IS("$155"), container_id, IS("$181"), entity_ids)

        container_entity_map = IonStruct(IS("$252"), [container_contents])

        if entity_dependencies:
            container_entity_map[IS("$253")] = entity_dependencies

        if entity_ids or entity_dependencies:

            new_fragments.append(YJFragment(ftype="$419", value=container_entity_map))

        else:
            self.log.error("Omitting container_entity_map due to lack of content")

        self.fragments = new_fragments

    def create_local_symbol(self, name):
        if not (name.startswith("content_") or
                re.match(r"^.{10,}[0-9](-ad|-spm|.ttf|.otf|.woff|.eot|.dfont|.bin)?$", name) or
                re.match(r"^G[0-9]+(-spm)?$", name) or
                re.match(UUID_MATCH_RE, name) or
                name == APPROXIMATE_PAGE_LIST or name.startswith(KFX_COVER_RESOURCE) or
                name == DICTIONARY_RULES_SYMBOL):

            self.log.error("Invalid local symbol created: %s" % name)

        return self.symtab.create_local_symbol(name)

    def check_symbol_table(self, rebuild=False, ignore_unused=False):
        used_symbols = set()
        original_symbols = set()
        for fragment in self.fragments:
            if fragment.ftype not in CONTAINER_FRAGMENT_TYPES:
                self.find_symbol_references(fragment, used_symbols)

            if fragment.ftype == "$3":
                original_symbols |= set(fragment.value.get("$7", []))

        new_symbols = set()
        for symbol in used_symbols:
            if not self.symtab.is_shared_symbol(symbol):
                new_symbols.add(unicode(symbol))

        missing_symbols = new_symbols - original_symbols

        if rebuild:
            missing_symbols -= set(self.symtab.get_local_symbols())

        if missing_symbols and not (self.is_dictionary or self.is_kpf_prepub):
            self.log.error("Symbol table is missing symbols: %s" % list_truncated(missing_symbols, 20))

        unused_symbols = original_symbols - new_symbols
        if unused_symbols and not ignore_unused:
            unused_uuid_symbols = set()
            for symbol in list(unused_symbols):
                if (re.match(UUID_MATCH_RE, symbol) or
                        symbol.startswith("PAGE_LIST_") or symbol == "page_list_entry" or
                        (self.is_sample and symbol.endswith("-ad"))):
                    unused_uuid_symbols.add(symbol)
                    unused_symbols.remove(symbol)

            if unused_symbols:
                self.log.warning("Symbol table contains %d unused symbols: %s" % (len(unused_symbols),
                        list_truncated(unused_symbols, 5)))

            if unused_uuid_symbols:
                self.log_known_error("Symbol table contains %d expected unused symbols: %s" % (len(unused_uuid_symbols),
                        list_truncated(unused_uuid_symbols, 5)))

        if rebuild:
            book_symbols = []
            for symbol in used_symbols:
                if self.symtab.get_id(symbol, used=False) >= self.symtab.local_min_id:
                    book_symbols.append(unicode(symbol))

            self.symtab.replace_local_symbols(sorted(book_symbols, key=natural_sort_key))
            self.replace_symbol_table_import()

    def replace_symbol_table_import(self):
        symtab_import = self.symtab.create_import()

        if symtab_import is not None:
            fragment = self.fragments.get("$3")
            if fragment is not None:
                self.fragments.remove(fragment)

            self.fragments.insert(0, YJFragment(symtab_import))

    def find_symbol_references(self, data, s):
        data_type = ion_type(data)

        if data_type is IonAnnotation:
            for a in data.annotations:
                s.add(a)

            self.find_symbol_references(data.value, s)

        if data_type is IonList or data_type is IonSExp:
            for fc in data:
                self.find_symbol_references(fc, s)

        if data_type is IonStruct:
            for fk,fv in data.items():
                s.add(fk)
                self.find_symbol_references(fv, s)

        if data_type is IonSymbol:
            s.add(data)

        if (data_type is IonString) and self.symtab.get_id(IS(data), used=False):
            s.add(IS(data))

    def log_known_error(self, msg):
        if REPORT_KNOWN_PROBLEMS:
            self.log.error(msg)
        elif REPORT_KNOWN_PROBLEMS is not None:
            self.log.info(msg)

    def log_error_once(self, msg):
        if msg not in self.reported_errors:
            self.log.error(msg)
            self.reported_errors.add(msg)

