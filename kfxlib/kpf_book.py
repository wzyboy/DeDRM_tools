from __future__ import (unicode_literals, division, absolute_import, print_function)

import copy
import decimal
import uuid

from .ion import (
        ion_type, IonAnnotation, IonFloat, IonList, IonSExp, IonString, IonStruct, IonSymbol, IS, isunicode, unannotated)
from .misc import font_file_ext
from .yj_container import (YJFragment, YJFragmentKey)
from .yj_structure import (
        FORMAT_SYMBOLS, MAX_CONTENT_FRAGMENT_SIZE)
from .yj_versions import (GENERIC_CREATOR_VERSIONS, is_known_aux_metadata)

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

FIX_BOOK = True
VERIFY_ORIGINAL_POSITION_MAP = False

CDE_CONTENT_TYPE_EBOK = "EBOK"
CDE_CONTENT_TYPE_PDOC = "PDOC"

EID_REFERENCES = {
    "$598",
    "$155",
    "$185",
    "$474",
    "$163",
    }

class KpfBook(object):
    def fix_kpf_prepub_book(self):
        if not FIX_BOOK:
            return

        for fragment in self.fragments.get_all("$417"):
            orig_fid = unicode(fragment.fid)
            fixed_fid = fix_resource_location(orig_fid)
            if fixed_fid != orig_fid:
                self.fragments.remove(fragment)
                self.fragments.append(YJFragment(ftype="$417", fid=self.create_local_symbol(fixed_fid), value=fragment.value))

        fragment = self.fragments.get("$585")
        if fragment is not None:
            fragment.value.pop("$598", None)

        for fragment in list(self.fragments):
            if fragment.ftype != "$270":
                fragment.value = self.kpf_fix_ion_data(fragment.value, ftype=fragment.ftype)

        for fragment in self.fragments.get_all("$266"):
            if fragment.value.get("$183", {}).get("$143", None) == 0:
                fragment.value["$183"].pop("$143")

        fragment = self.fragments.get("$550")
        if fragment is not None:
            for lm in fragment.value:
                lm.pop("$178", None)

        fragment = self.fragments.get("$490")
        if fragment is not None:

            for category in ["kindle_audit_metadata", "kindle_title_metadata"]:
                for cm in fragment.value["$491"]:
                    if cm["$495"] == category:
                        break
                else:
                    fragment.value["$491"].append(IonStruct(IS("$495"), category, IS("$258"), []))

            for cm in fragment.value["$491"]:
                if cm["$495"] == "kindle_audit_metadata":
                    if (self.kpf_container.file_creator and self.kpf_container.creator_version and
                            (not self.kpf_container.creator_version.startswith("unknown")) and
                            (self.get_metadata_value("file_creator", category="kindle_audit_metadata"),
                                self.get_metadata_value("creator_version", category="kindle_audit_metadata")) in GENERIC_CREATOR_VERSIONS):
                        for metadata in cm["$258"]:
                            if metadata["$492"] == "file_creator":
                                metadata["$307"] = self.kpf_container.file_creator

                            if metadata["$492"] == "creator_version":
                                metadata["$307"] = self.kpf_container.creator_version

                elif cm["$495"] == "kindle_title_metadata":
                    if self.get_metadata_value("is_sample") is None:
                        cm["$258"].append(IonStruct(IS("$492"), "is_sample", IS("$307"), False))

                    if self.get_metadata_value("override_kindle_font") is None:
                        cm["$258"].append(IonStruct(IS("$492"), "override_kindle_font", IS("$307"), False))

                    if (self.get_metadata_value("cover_image") is None and
                                self.get_metadata_value("yj_fixed_layout", category="kindle_capability_metadata") is not None):
                        cover_resource = self.locate_cover_image_resource_from_content(replace_pdf=True)
                        if cover_resource is not None:
                            cm["$258"].append(IonStruct(IS("$492"), "cover_image", IS("$307"), unicode(cover_resource)))

        for fragment in self.fragments.get_all("$262"):
            if fragment.fid != "$262":

                self.fragments.remove(fragment)
                self.fragments.append(YJFragment(ftype="$262", value=fragment.value))

            location = fragment.value["$165"]
            font_data_fragment = self.fragments[YJFragmentKey(ftype="$417", fid=location)]
            self.fragments.remove(font_data_fragment)
            self.fragments.append(YJFragment(ftype="$418", fid=self.create_local_symbol(location), value=font_data_fragment.value))

        for fragment in self.fragments.get_all("$164"):
            if (fragment.value.get("$161") == "$287" and "$422" not in fragment.value and
                    "$423" not in fragment.value and "$167" in fragment.value):

                referred_resources = fragment.value["$167"]
                for frag in self.fragments.get_all("$164"):
                    if (frag.fid in referred_resources and "$422" in frag.value and
                            "$423" in frag.value):

                        fragment.value[IS("$422")] = frag.value["$422"]
                        fragment.value[IS("$423")] = frag.value["$423"]
                        break

        canonical_format = (2, 0) if self.is_illustrated_layout else (1, 0)

        file_creator = self.get_metadata_value("file_creator", category="kindle_audit_metadata", default="")
        creator_version = self.get_metadata_value("creator_version", category="kindle_audit_metadata", default="")

        if (file_creator == "KC" or (file_creator == "KTC" and creator_version >= "1.11")) and canonical_format < (2, 0):
            canonical_format = (2, 0)

        content_features = self.fragments.get("$585")
        if content_features is None:
            content_features = YJFragment(ftype="$585", value=IonStruct(IS("$590"), []))
            self.fragments.append(content_features)

        if self.get_feature_value("CanonicalFormat", namespace="SDK.Marker") is None:

            features = content_features.value["$590"]
            features.append(IonStruct(
                IS("$586"), "SDK.Marker",
                IS("$492"), "CanonicalFormat",
                IS("$589"), IonStruct(IS("$5"), IonStruct(
                    IS("$587"), canonical_format[0],
                    IS("$588"), canonical_format[1]))))

        else:
            self.log.warning("CanonicalFormat already present in KPF")

        default_reading_order_name,default_reading_order = self.get_default_reading_order()

        if self.fragments.get("$389") is None:
            self.log.info("Adding book_navigation")
            book_nav = IonStruct()

            if default_reading_order_name is not None:
                book_nav[IS("$178")] = default_reading_order_name

            book_nav[IS("$392")] = []
            self.fragments.append(YJFragment(ftype="$389", value=[book_nav]))

        for book_navigation in self.fragments["$389"].value:
            pages = []
            nav_containers = book_navigation["$392"]

            for nav_container in nav_containers:
                nav_container = unannotated(nav_container)
                if nav_container.get("$235", None) == "$236":
                    entries = nav_container.get("$247", [])
                    i = 0
                    while i < len(entries):
                        entry = unannotated(entries[i])
                        label = entry.get("$241", {}).get("$244", "")
                        if label.startswith("page_list_entry:"):
                            seq,sep,text = label.partition(":")[2].partition(":")

                            pages.append((int(seq), IonAnnotation([IS("$393")], IonStruct(

                                IS("$241"), IonStruct(IS("$244"), text),
                                IS("$246"), entry["$246"]))))

                            entries.pop(i)
                            i -= 1

                        i += 1

            if pages:
                self.log.info("Transformed %d KFX landmark entries into a page list" % len(pages))

                nav_containers.append(IonAnnotation([IS("$391")], IonStruct(
                        IS("$235"), IS("$237"),

                        IS("$239"), self.kpf_gen_uuid_symbol(),
                        IS("$247"), [p[1] for p in sorted(pages)])))

        if self.is_dictionary:
            self.is_kpf_prepub = False
        else:

            content_fragment_data = {}
            for section_name in default_reading_order:
                for story_name in self.extract_section_story_names(section_name):
                    self.kpf_collect_content_strings(story_name, content_fragment_data)

            has_text_block = False
            for content_name,content_list in content_fragment_data.items():
                has_text_block = True
                self.fragments.append(YJFragment(ftype="$145", fid=content_name,
                        value=IonStruct(IS("$4"), content_name, IS("$146"), content_list)))

            section_names = self.get_default_reading_order()[1]
            map_pos_info = self.collect_position_map_info(section_names)

            if VERIFY_ORIGINAL_POSITION_MAP:
                content_pos_info = self.collect_content_position_info(section_names)
                self.verify_position_info(section_names, content_pos_info, map_pos_info)

            if len(map_pos_info) < 10 and self.is_illustrated_layout:

                self.log.warning("creating position map (original is missing or incorrect)")
                map_pos_info = self.collect_content_position_info(section_names)

            self.is_kpf_prepub = False
            has_spim, has_position_id_offset = self.create_position_map(section_names, map_pos_info)

            has_yj_location_pid_map = False
            if self.fragments.get("$550") is None and not (self.is_textbook or self.is_magazine):
                loc_info = self.generate_approximate_locations(map_pos_info)
                has_yj_location_pid_map = self.create_location_map(loc_info)

            if self.fragments.get("$395") is None:
                self.fragments.append(YJFragment(ftype="$395", value=IonStruct(IS("$247"), [])))

            for fragment in self.fragments.get_all("$593"):
                self.fragments.remove(fragment)

            fc = []

            if has_spim or has_yj_location_pid_map:
                fc.append(IonStruct(IS("$492"), "kfxgen.positionMaps", IS("$5"), 2))

            if has_position_id_offset:
                fc.append(IonStruct(IS("$492"), "kfxgen.pidMapWithOffset", IS("$5"), 1))

            if has_text_block:
                fc.append(IonStruct(IS("$492"), "kfxgen.textBlock", IS("$5"), 1))

            self.fragments.append(YJFragment(ftype="$593", value=fc))

        for fragment in self.fragments.get_all("$597"):
            for kv in fragment.value.get("$258", []):
                key = kv.get("$492", "")
                value = kv.get("$307", "")
                if not is_known_aux_metadata(key, value):
                    self.log.warning("Unknown auxiliary_data: %s=%s" % (key, value))

        self.check_fragment_usage(rebuild=True, ignore_extra=True)

        self.check_symbol_table(rebuild=True, ignore_unused=True)

    def kpf_gen_uuid_symbol(self):
        return self.create_local_symbol(unicode(uuid.uuid4()))

    def kpf_fix_ion_data(self, data, container=None, ftype=None):
        data_type = ion_type(data)

        if data_type is IonAnnotation:

            if data.annotations[0] == "$608":
                return self.kpf_fix_ion_data(data.value, container=container, ftype=ftype)

            new_annot = [self.kpf_fix_ion_data(annot, ftype=ftype) for annot in data.annotations]
            return IonAnnotation(new_annot, self.kpf_fix_ion_data(data.value, container=container, ftype=ftype))

        if data_type is IonList:
            new_list = []
            for i,fc in enumerate(data):

                if container == "$146" and isinstance(fc, IonSymbol):
                    fc = copy.deepcopy(self.fragments[YJFragmentKey(ftype="$608", fid=fc)].value)

                if ((not self.is_dictionary) and
                        ((ftype == "$609" and container == "contains_list_" and i == 1) or
                        (ftype == "$538" and container == "yj.semantics.containers_with_semantics"))):
                    fc = self.symbol_id(fc)

                if container == "$181":
                    list_container = "contains_list_"
                elif container == "$141":
                    list_container = "$141"
                else:
                    list_container = None

                new_list.append(self.kpf_fix_ion_data(fc, container=list_container, ftype=ftype))

            return new_list

        if data_type is IonSExp:
            new_sexp = IonSExp()
            for fc in data:
                new_sexp.append(self.kpf_fix_ion_data(fc, ftype=ftype))

            return new_sexp

        if data_type is IonStruct:
            new_struct = IonStruct()
            for fk,fv in data.items():
                fv = self.kpf_fix_ion_data(fv, container=fk, ftype=ftype)

                if not self.is_dictionary:

                    if fk == "$597":
                        continue

                    if fk == "$239":
                        self.create_local_symbol(unicode(fv))

                    if fk in EID_REFERENCES and ftype != "$597" and isinstance(fv, IonSymbol):

                        if fk == "$598":
                            fk = IS("$155")

                        if ftype != "$610" or self.fragments.get(ftype="$260", fid=fv) is None:
                            fv = self.symbol_id(fv)

                if fk == "$161" and isunicode(fv):
                    fv = IS(FORMAT_SYMBOLS[fv])

                if fk.startswith("yj.semantics.") or fk.startswith("yj.authoring."):
                    continue

                if (self.is_illustrated_layout and ftype == "$260" and container == "$141" and
                            fk in ["$67", "$66"]):
                    continue

                if fk == "$165":
                    if ion_type(fv) is not IonString:
                        raise Exception("location is not IonString: %s" % fv)

                    fv = fix_resource_location(fv)

                new_struct[self.kpf_fix_ion_data(fk, ftype=ftype)] = fv

            return new_struct

        if data_type is IonFloat:

            dec = decimal.Decimal("%g" % data)
            if abs(dec) < 0.001: dec = decimal.Decimal("0")
            return dec

        return data

    def kpf_collect_content_strings(self, story_name, content_fragment_data):

        def _kpf_collect_content_strings(data):
            data_type = ion_type(data)

            if data_type is IonAnnotation:
                _kpf_collect_content_strings(data.value)

            elif data_type is IonList or data_type is IonSExp:
                for fc in data:
                    _kpf_collect_content_strings(fc)

            elif data_type is IonStruct:
                for fk,fv in data.items():
                    if fk == "$145" and isunicode(fv):

                        if len(content_fragment_data) == 0 or self._content_fragment_size >= MAX_CONTENT_FRAGMENT_SIZE:
                            self._content_fragment_name = self.create_local_symbol("content_%d" % (len(content_fragment_data) + 1))
                            content_fragment_data[self._content_fragment_name] = []
                            self._content_fragment_size = 0

                        content_fragment_data[self._content_fragment_name].append(fv)
                        self._content_fragment_size += len(fv.encode("utf8"))

                        data[fk] = IonStruct(
                            IS("$4"), self._content_fragment_name,
                            IS("$403"), len(content_fragment_data[self._content_fragment_name]) - 1)
                    else:
                        _kpf_collect_content_strings(fv)

        _kpf_collect_content_strings(self.fragments[YJFragmentKey(ftype="$259", fid=story_name)].value)

    def symbol_id(self, symbol):
        if symbol is None or isinstance(symbol, int):
            return symbol

        return self.symtab.get_id(symbol)

    def kpf_add_font_ext(self, filename, raw_font):
        ext = font_file_ext(raw_font, default="bin")
        if ext == "bin":
            self.log.warn("font %s has unknown type (possibly obfuscated)" % filename)

        return "%s.%s" % (filename, ext)

def section_sort_key(reading_order, s):
    try:
        return (reading_order.index(s), s)
    except ValueError:
        return (len(reading_order), s)

def fix_resource_location(s):

    return s if s.startswith("resource/") else "resource/%s" % s

