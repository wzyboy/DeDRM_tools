from __future__ import (unicode_literals, division, absolute_import, print_function)

import collections
import copy
import decimal
import lxml.html
import re
import cStringIO
import zipfile

from .ion import (ion_type, IonAnnotation, IonList, IonSExp, IonString, IonStruct, IonSymbol)
from .misc import (list_keys, list_symbols, truncate_list, unroot_path)
from .yj_to_epub_content import EPUBContent
from .yj_to_epub_metadata import EPUBMetadata
from .yj_to_epub_misc import EPUBMisc
from .yj_to_epub_navigation import EPUBNavigation
from .yj_to_epub_properties import (EPUBProperties, GENERIC_FONT_NAMES)
from .yj_to_epub_resources import EPUBResources

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

REPORT_KNOWN_UNSUPPORTED = True
REPORT_MISSING_FONTS = True

RETAIN_USED_FRAGMENTS = False

EPUB_VERSIONS = {"2.0", "3.0", "3.1"}

FRAGMENT_NAME_SYMBOL = {
    "$266": "$180",
    "$164": "$175",
    "$391": "$239",
    "$393": "$240",
    "$260": "$174",
    "$608": "$598",
    "$259": "$176",
    "$157": "$173",
    }

class EPUB(EPUBContent, EPUBMetadata, EPUBMisc,
            EPUBNavigation, EPUBProperties, EPUBResources):

    DEBUG = False

    GENERATE_EPUB2_COMPATIBLE = True

    OEBPS_DIR = "OEBPS"

    PLACE_FILES_IN_SUBDIRS = False

    if PLACE_FILES_IN_SUBDIRS:

        OPF_FILEPATH = "/content.opf"
        NCX_FILEPATH = "/toc.ncx"
        TEXT_FILEPATH = "/xhtml/part%04d.xhtml"
        NAV_FILEPATH = "/xhtml/nav.xhtml"
        FONT_FILEPATH = "/fonts/%s"
        IMAGE_FILEPATH = "/images/%s"
        STYLES_CSS_FILEPATH = "/css/stylesheet.css"
        RESET_CSS_FILEPATH = "/css/reset.css"
        LAYOUT_CSS_FILEPATH = "/css/layout%04d.css"
    else:

        OPF_FILEPATH = "/content.opf"
        NCX_FILEPATH = "/toc.ncx"
        TEXT_FILEPATH = "/part%04d.xhtml"
        NAV_FILEPATH = "/nav.xhtml"
        FONT_FILEPATH = "/%s"
        IMAGE_FILEPATH = "/%s"
        STYLES_CSS_FILEPATH = "/stylesheet.css"
        RESET_CSS_FILEPATH = "/reset.css"
        LAYOUT_CSS_FILEPATH = "/layout%04d.css"

    KFX_STYLE_NAME = "-kfx-style-name"

    def __init__(self, book, log, epub_version):
        self.log = log
        self.book = book
        self.book_data = self.organize_fragments_by_type(book.fragments)
        self.used_fragments = {}
        self.new_book_symbol_format = self.is_new_book_symbol_format(book.fragments)

        if epub_version not in EPUB_VERSIONS:
            raise Exception("Desired EPUB version (%s) is not supported. (%s allowed)" % (
                    epub_version, list_symbols(EPUB_VERSIONS)))

        self.epub_version = epub_version
        self.generate_epub3 = epub_version >= "3.0"
        self.generate_epub30 = self.generate_epub3 and epub_version < "3.1"
        self.generate_epub31 = epub_version >= "3.1"

        self.log.info("Converting book to EPUB %s" % self.epub_version)

        decimal.getcontext().prec = 6

        self.oebps_files = {}

        self.book_parts = []
        self.ncx_toc = []
        self.manifest = []
        self.guide = []
        self.pagemap = collections.OrderedDict()
        self.next_part_index = 0

        self.style_definitions = {}
        self.missing_styles = set()
        self.css_rules = {}
        self.css_files = set()
        self.missing_special_classes = set()
        self.media_queries = collections.defaultdict(dict)
        self.font_names = set()
        self.missing_font_names = set()
        self.font_name_replacements = {}

        self.font_faces = []
        self.location_filenames = {}
        self.reported_characters = set()

        for name in GENERIC_FONT_NAMES:
            self.fix_font_name(name, add=True, generic=True)

        self.toc_entry_count = 0
        self.anchor_uri = {}
        self.anchor_elem = {}
        self.position_anchors = {}
        self.anchor_positions = {}
        self.used_anchors = set()
        self.immovable_anchors = set()
        self.fix_condition_href = False

        self.fixed_layout = False
        self.region_magnification = False
        self.virtual_panels = False
        self.cde_content_type = ""
        self.book_type = ""
        self.illustrated_layout = False

        self.mp4_video = None

        self.min_aspect_ratio = self.max_aspect_ratio = None

        self.original_width = self.original_height = None

        self.used_external_resources = set()
        self.used_raw_media = set()

        self.process_fonts()
        self.process_document_data()
        self.process_content_features()
        self.process_metadata()

        if self.illustrated_layout:
            raise Exception("Illustrated layout (Kindle in Motion) is not supported.")

        self.set_condition_operators()

        self.process_anchors()
        self.process_navigation()

        self.process_styles()

        self.process_reading_orders()

        if self.cover_resource:
            self.cover_location = self.process_external_resource(self.cover_resource)

        self.create_epub3_nav()
        self.fixup_anchors_and_hrefs()
        self.fixup_styles_and_classes()
        self.create_css_files()
        self.compare_fixed_layout_viewports()
        self.save_book_parts()

        if self.position_anchors:
            pos = []
            for id in self.position_anchors:
                for offset in self.position_anchors[id]:
                    pos.append("%s.%s" % (id, offset))

            self.log.error("Failed to locate %d referenced positions: %s" % (len(pos), ", ".join(truncate_list(sorted(pos)))))

        self.create_ncx()
        self.create_opf()

        self.report_duplicate_anchors()

        external_resources = self.book_data.pop("$164", {})
        for used_external_resource in self.used_external_resources:
            external_resources.pop(used_external_resource)

        self.check_empty(external_resources, "external_resources")

        raw_media = self.book_data.pop("$417", {})
        for used_raw_media in self.used_raw_media:
            raw_media.pop(used_raw_media)

        self.check_empty(raw_media, "raw_media")
        self.check_empty(self.book_data.pop("$260", {}), "$260")
        self.check_empty(self.book_data.pop("$259", {}), "$259")

        self.book_data.pop("$270", None)
        self.book_data.pop("$593", None)
        self.book_data.pop("$3", None)
        self.book_data.pop("$270", None)
        self.book_data.pop("$419", None)
        self.book_data.pop("$145", None)
        self.book_data.pop("$608", None)
        self.book_data.pop("$692", None)

        self.book_data.pop("$550", None)

        self.book_data.pop("$265", None)

        self.book_data.pop("$264", None)

        if "$395" in self.book_data:
            resource_path = self.book_data.pop("$395")
            for ent in resource_path.pop("$247", []):
                ent.pop("$175", None)
                ent.pop("$166", None)
                self.check_empty(ent, "%s %s" % ("$395", "$247"))

            self.check_empty(resource_path, "$395")

        self.book_data.pop("$609", None)
        self.book_data.pop("$621", None)

        self.book_data.pop("$597", None)
        self.book_data.pop("$610", None)
        self.book_data.pop("$611", None)

        self.book_data.pop("$387", None)
        self.book_data.pop("$267", None)
        self.book_data.pop("$390", None)

        self.check_empty(self.book_data, "Book fragments")

        if self.missing_font_names and REPORT_MISSING_FONTS:
            self.log.warning("Missing font family names: %s" % list_symbols(self.missing_font_names))

            if self.font_names:
                self.log.info("Present font family names: %s" % list_symbols(self.font_names))

        self.epub_data = self.zip_epub(self.oebps_files)

    def organize_fragments_by_type(self, fragment_list):
        font_count = 0
        categorized_data = {}

        for fragment in fragment_list:
            id = fragment.fid

            if fragment.ftype == "$270":
                id = IonSymbol("%s:%s" % (fragment.value.get("$161", ""), fragment.value.get("$409", "")))
            elif fragment.ftype == "$262":
                id = IonSymbol("%s-font-%03d" % (id, font_count))
                font_count += 1
            elif fragment.ftype == "$387":
                id = IonSymbol("%s:%s" % (id, fragment.value["$215"]))

            dt = categorized_data.setdefault(fragment.ftype, {})

            if id not in dt:
                dt[id] = self.replace_ion_data(fragment.value)
            else:
                self.log.error("Book contains multiple %s fragments" % unicode(fragment))

        for category, ids in categorized_data.items():
            if len(ids) == 1:
                id = list(ids)[0]
                if id == category:
                    categorized_data[category] = categorized_data[category][id]
            elif None in ids:
                self.log.error("Fragment list contains mixed null/non-null ids of type '%s'" % category)

        return categorized_data

    def is_new_book_symbol_format(self, fragment_list):
        for fragment in fragment_list:
            if fragment.ftype == "$3":
                break
        else:
            self.log.error("Could not locate book symbols")
            return False

        old_fmt_count = new_fmt_count = 0

        for book_symbol in fragment.value.get("$7", []):
            if re.match("^[0-9a-zA-Z_-]{22}[0-9]+(-.+)?$", book_symbol.rpartition("/")[2]):

                new_fmt_count += 1
            else:
                old_fmt_count += 1

        return new_fmt_count >= old_fmt_count

    def replace_ion_data(self, f, replace_symbols=False):

        data_type = ion_type(f)

        if data_type is IonAnnotation:
            return self.replace_ion_data(f.value, replace_symbols=replace_symbols)

        if data_type is IonList:
            return [self.replace_ion_data(fc, replace_symbols=replace_symbols) for fc in f]

        if data_type is IonSExp:
            return IonSExp([self.replace_ion_data(fc, replace_symbols=replace_symbols) for fc in f])

        if data_type is IonStruct:
            newf = IonStruct()
            for fk,fv in f.items():
                newf[self.replace_ion_data(fk, replace_symbols=replace_symbols)] = self.replace_ion_data(fv, replace_symbols=replace_symbols)

            return newf

        if data_type is IonSymbol and replace_symbols:
            return unicode(f)

        return f

    def unique_key(self, s, d):

        if s not in d or s is None:
            return s

        count = 0
        while True:
            new_s = s + ":" + unicode(count)

            if new_s not in d:
                return new_s

            count += 1

    def get_fragment(self, ftype=None, fid=None, delete=True):

        if ion_type(fid) not in [IonString, IonSymbol]:
            return fid

        if ftype in self.book_data:
            fragment_container = self.book_data[ftype]
        elif ftype == "$393" and "$394" in self.book_data:
            fragment_container = self.book_data["$394"]
        else:
            raise Exception("book has no fragments of desired type: %s %s" % (ftype, fid))

        data = fragment_container.pop(fid, None) if delete else fragment_container.get(fid)
        if data is None:
            data = self.used_fragments.get((ftype, fid))
            if data is None:
                raise Exception("book is missing fragment: %s %s" % (ftype, fid))

            if not RETAIN_USED_FRAGMENTS:
                raise Exception("book fragment used multiple times: %s %s" % (ftype, fid))

            self.log.warning("book fragment used multiple times: %s %s" % (ftype, fid))

        if RETAIN_USED_FRAGMENTS:
            self.used_fragments[(ftype, fid)] = copy.deepcopy(data)
        else:
            self.used_fragments[(ftype, fid)] = True

        data_name = self.get_fragment_name(data, ftype, delete=False)
        if data_name and data_name != fid:
            self.log.error("Expected %s named %s but found %s" % (ftype, fid, data_name))
        return data

    def get_named_fragment(self, structure, ftype=None, delete=True):

        return self.get_fragment(ftype=ftype, fid=structure.pop(FRAGMENT_NAME_SYMBOL[ftype]), delete=delete)

    def get_location_id(self, structure):

        id = structure.pop("$155", None) or structure.pop("$598", None)
        if id is not None:
            id = unicode(id)

        return id

    def check_fragment_name(self, fragment_data, ftype, fid):

        name = self.get_fragment_name(fragment_data, ftype)
        if name != fid:
            raise Exception("Name of %s %s is incorrect, expected %s" % (ftype, name, fid))

    def get_fragment_name(self, fragment_data, ftype, delete=True):

        return self.get_structure_name(fragment_data, FRAGMENT_NAME_SYMBOL[ftype], delete)

    def get_structure_name(self, structure, name_key, delete=True):

        return structure.pop(name_key, None) if delete else structure.get(name_key, None)

    def file_id(self, filename):

        id = re.sub(r"[^A-Za-z0-9\.\-]", "_", unroot_path(filename))

        if not re.match(r"^[A-Za-z]", id[0]):
            id = "id_" + id

        return id

    def check_empty(self, a_dict, dict_name):
        if len(a_dict) > 0:
            try:
                extra_data = repr(a_dict)
            except:
                extra_data = None

            if (extra_data is None) or (len(extra_data) > 1024):
                extra_data = "%s (keys only)" % list_keys(a_dict)

            self.log.warning("%s has extra data: %s" % (unicode(dict_name), extra_data))
            a_dict.clear()

    def non_generic_class_name(self, name):

        if self.new_book_symbol_format:

            name = name[22:]
        else:

            name = re.sub(r"^V_[0-9]_[0-9]-(PARA|CHAR)-[0-9]_[0-9]_[0-9a-f]+_[0-9a-f]+", "", name, count=1)

        while name.startswith("-"):
            name = name[1:]

        if re.match("^[0-9]", name):
            name = "class" + name

        return name

    def fix_html_id(self, id):
        if self.illustrated_layout:
            id = id.replace(".", "_")

        id = re.sub(r"[^A-Za-z0-9_\-\.]", "_", id)

        if len(id) == 0 or not re.match(r"^[A-Za-z]", id):
            id = "id_" + id

        return id

    def log_unsupported(self, msg, book_types=None):
        if (book_types and self.book_type not in book_types) or REPORT_KNOWN_UNSUPPORTED:
            self.log.error(msg)
        elif REPORT_KNOWN_UNSUPPORTED is not None:
            self.log.info(msg)

    def zip_epub(self, oebps_files):
        file = cStringIO.StringIO()

        with zipfile.ZipFile(file, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/epub+zip".encode("ascii"), compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", self.container_xml())

            for filename, oebps_file in sorted(oebps_files.items()):
                zf.writestr(self.OEBPS_DIR + filename, str(oebps_file.binary_data))

        data = file.getvalue()
        file.close()

        return data

    def set_attrib(self, elem, name, val):
        if val:
            elem.set(name, unicode(val))
        elif name in elem.attrib:
            del elem.attrib[name]

    def SubElement(self, root, tag, first=False):
        child = lxml.html.Element(tag)

        if first:
            root.insert(0, child)
        else:
            root.append(child)

        return child

