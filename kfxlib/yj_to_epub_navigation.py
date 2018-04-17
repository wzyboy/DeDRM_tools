from __future__ import (unicode_literals, division, absolute_import, print_function)

from lxml import etree
import re
import urllib
from urlparse import urlparse

from .misc import (make_unique_name, urlrelpath)
from .yj_structure import APPROXIMATE_PAGE_LIST
from .yj_to_epub_resources import (ManifestEntry, OutputFile)

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

KEEP_APPROX_PG_NUMS = False

EPUB3_VOCABULARY = {
    "$233": "cover",
    "$396": "bodymatter",
    "$269": "bodymatter",
    "$212": "toc",
    }

GUIDE_TYPE_OF_LANDMARK_TYPE = {
    "$233": "cover",
    "$396": "text",
    "$212": "toc",
    }

class EPUBNavigation(object):

    def process_navigation(self):

        book_navigations = self.book_data.pop("$389", [])

        if len(book_navigations) == 0:

            self.reading_order_name = ""
        else:
            book_navigation = book_navigations[0]

            self.reading_order_name = book_navigation.pop("$178")

            for nav_container_ in book_navigation.pop("$392"):
                nav_container = self.get_fragment(ftype="$391", fid=nav_container_)
                self.process_nav_container(nav_container)

            self.check_empty(book_navigation, "book_navigation")

            if len(book_navigations) > 1:
                self.log.warning("Book contains %d navigations (first used)" % len(book_navigations))

        self.check_empty(self.book_data.pop("$391", {}), "nav_container")
        self.check_empty(self.book_data.pop("$394", {}), "conditional_nav_group_unit")

    def process_nav_container(self, nav_container):
        nav_container.pop("mkfx_id", None)
        nav_container_name = nav_container.pop("$239", "")
        nav_type = nav_container.pop("$235")
        if nav_type not in {"$212", "$236", "$237", "$213", "$214"}:
            self.log.error("nav_container %s has unknown type: %s" % (nav_container_name, nav_type))

        if nav_type in {"$213", "$214"}:
            self.log_unsupported("nav_container %s has unsupported type: %s" % (nav_container_name, nav_type), ["magazine"])

        if "$6" in nav_container:
            for import_name in nav_container.pop("$6"):
                self.process_nav_container(self.book_data["$391"].pop(import_name))
        else:
            for nav_unit_ in nav_container.pop("$247"):
                nav_unit = self.get_fragment(ftype="$393", fid=nav_unit_)
                nav_unit.pop("mkfx_id", None)

                if nav_type in {"$212", "$214", "$213"}:
                    self.process_nav_unit(nav_type, nav_unit, self.ncx_toc, nav_container_name)

                elif nav_type == "$236":
                    label = self.get_representation_label(nav_unit)
                    nav_unit_name = nav_unit.pop("$240", label)
                    target_position = self.get_position(nav_unit.pop("$246"))
                    landmark_type = nav_unit.pop("$238", None)

                    if landmark_type:
                        anchor_name = self.unique_key(self.fix_html_id(unicode(nav_unit_name)), self.anchor_positions)
                        self.register_anchor(anchor_name, target_position)
                        self.guide.append((landmark_type, label, anchor_name))

                elif nav_type == "$237":
                    label = self.get_representation_label(nav_unit)
                    nav_unit_name = nav_unit.pop("$240", "page_list_entry")
                    target_position = self.get_position(nav_unit.pop("$246"))

                    if nav_unit_name != "page_list_entry":
                        self.log.warning("Unexpected page_list nav_unit_name: %s" % nav_unit_name)

                    if label and (KEEP_APPROX_PG_NUMS or nav_container_name != APPROXIMATE_PAGE_LIST):
                        anchor_name = self.fix_html_id("page_" + label)
                        self.register_anchor(anchor_name, target_position)

                        if label in self.pagemap and self.pagemap[label] != anchor_name:
                            self.log.warning("Page %s has multiple anchors: %s, %s" % (label, self.pagemap[label], anchor_name))

                        self.pagemap[label] = anchor_name

                self.check_empty(nav_unit, "nav_container %s nav_unit" % nav_container_name)

        self.check_empty(nav_container, "nav_container %s" % nav_container_name)

    def process_nav_unit(self, nav_type, nav_unit, ncx_toc, nav_container_name):
        label = self.get_representation_label(nav_unit)
        nav_unit_name = nav_unit.pop("$240", label)
        nav_unit.pop("mkfx_id", None)

        nested_toc = []

        for entry in nav_unit.pop("$247", []):
            nested_nav_unit = self.get_fragment(ftype="$393", fid=entry)
            self.process_nav_unit(nav_type, nested_nav_unit, nested_toc, nav_container_name)

        for entry_set in nav_unit.pop("$248", []):
            for entry in entry_set.pop("$247", []):
                nested_nav_unit = self.get_fragment(ftype="$393", fid=entry)
                self.process_nav_unit(nav_type, nested_nav_unit, nested_toc, nav_container_name)

            orientation = entry_set.pop("$215")
            if orientation == "$386":
                if self.orientation_lock != "landscape":
                    nested_toc = []
            elif orientation == "$385":
                if self.orientation_lock == "landscape":
                    nested_toc = []
            else:
                self.log.error("Unknown entry set orientation: %s" % orientation)

            self.check_empty(entry_set, "nav_container %s %s entry_set" % (nav_container_name, nav_type))

        if "$246" in nav_unit:
            anchor_name = self.fix_html_id("toc%d_%s" % (self.toc_entry_count, nav_unit_name))
            self.toc_entry_count += 1

            target_position = self.get_position(nav_unit.pop("$246"))
            self.register_anchor(anchor_name, target_position)
        else:
            anchor_name = None

        if (not label) and (not anchor_name):
            ncx_toc.extend(nested_toc)
        else:
            ncx_toc.append((label, anchor_name, nested_toc))

        self.check_empty(nav_unit, "nav_container %s %s nav_unit" % (nav_container_name, nav_type))

    def process_anchors(self):

        anchors = self.book_data.pop("$266", {})
        for anchor_name, anchor in anchors.items():
            self.check_fragment_name(anchor, "$266", anchor_name)

            if "$186" in anchor:
                self.anchor_uri[unicode(anchor_name)] = anchor.pop("$186")

            elif "$183" in anchor:
                self.register_anchor(unicode(anchor_name), self.get_position(anchor.pop("$183")))

            self.check_empty(anchor, "anchor %s" % anchor_name)

    def get_position(self, position):

        id = self.get_location_id(position)
        offset = position.pop("$143", 0)
        self.check_empty(position, "position")
        return (id, offset)

    def get_representation_label(self, entry):
        if "$241" not in entry:
            return ""

        representation = entry.pop("$241")

        if "$244" in representation:
            label = representation.pop("$244")
        elif "$245" in representation:
            icon = representation.pop("$245")
            self.process_external_resource(icon)
            label = unicode(icon)
        else:
            label = ""

        self.check_empty(representation, "nav_container representation")
        return label

    def position_str(self, position):
        return "%s.%d" % position

    def register_anchor(self, anchor_name, position):
        if self.DEBUG: self.log.debug("register_anchor %s = %s" % (anchor_name, self.position_str(position)))

        if anchor_name not in self.anchor_positions:
            self.anchor_positions[anchor_name] = set()

        self.anchor_positions[anchor_name].add(position)

        id, offset = position
        if id not in self.position_anchors:
            self.position_anchors[id] = {}

        if offset not in self.position_anchors[id]:
            self.position_anchors[id][offset] = set()

        self.position_anchors[id][offset].add(anchor_name)

    def process_position(self, id, offset, elem):
        if self.DEBUG: self.log.debug("process position %s" % self.position_str((id, offset)))
        if id in self.position_anchors:
            if offset in self.position_anchors[id]:
                if self.DEBUG: self.log.debug("at registered position")
                if not elem.get("id", ""):

                    best_id = None
                    for anchor_name in self.position_anchors[id][offset]:
                        if best_id is None or anchor_name.startswith("page_"):
                            best_id = self.fix_html_id(anchor_name)

                    for anchor_name in self.position_anchors[id][offset]:
                        if anchor_name.startswith("magnify_"):
                            best_id = self.fix_html_id(anchor_name)

                    elem.set("id", best_id)
                    if self.DEBUG: self.log.debug("set element id %s for position %s" % (best_id, self.position_str((id, offset))))

                for anchor_name in self.position_anchors[id].pop(offset):
                    self.anchor_elem[anchor_name] = elem

                if len(self.position_anchors[id]) == 0:
                    self.position_anchors.pop(id)

    def get_element_anchor_name(self, elem, root_name):
        for anchor_name,anchor_elem in self.anchor_elem.items():
            if anchor_elem is elem:
                return anchor_name

        anchor_name = make_unique_name(root_name, self.anchor_elem)
        self.anchor_elem[anchor_name] = elem
        return anchor_name

    def move_anchors(self, old_root, target_elem):

        for anchor_name,elem in self.anchor_elem.items():
            if root_element(elem) is old_root:
                self.anchor_elem[anchor_name] = target_elem

    def get_anchor_uri(self, anchor_name):
        self.used_anchors.add(anchor_name)

        if anchor_name in self.anchor_uri:
            return self.anchor_uri[anchor_name]

        positions = self.anchor_positions.get(anchor_name, [])
        self.log.error("Failed to locate uri for anchor: %s (position: %s)" % (
                anchor_name, ", ".join([self.position_str(p) for p in sorted(positions)])))
        return "/MISSING#" + anchor_name

    def report_duplicate_anchors(self):
        for anchor_name, positions in self.anchor_positions.items():
            if (anchor_name in self.used_anchors) and (len(positions) > 1):
                self.log.error("Used anchor %s has multiple positions: %s" % (
                        anchor_name, ", ".join([self.position_str(p) for p in sorted(positions)])))

    def register_link_id(self, id, kind):
        id = unicode(id)
        anchor_name = self.fix_html_id("%s_%s" % (kind, id))
        self.register_anchor(anchor_name, (id, 0))
        return anchor_name

    def id_of_anchor(self, anchor, filename):
        url = self.get_anchor_uri(anchor)
        purl = urlparse(url)

        if purl.path != filename or not purl.fragment:
            self.log.error("anchor %s in file %s links to %s" % (anchor, filename, url))

        return purl.fragment

    def fixup_anchors_and_hrefs(self):

        for anchor_name, elem in self.anchor_elem.items():
            root = root_element(elem)

            for book_part in self.book_parts:
                if book_part.html is root:
                    id = elem.get("id", "")
                    if not id:
                        id = self.fix_html_id(unicode(anchor_name))
                        elem.set("id", id)

                    self.anchor_uri[anchor_name] = "%s#%s" % (urllib.quote(book_part.filename), id)
                    break
            else:
                self.log.error("Failed to locate element within book parts for anchor %s" % anchor_name)

        self.anchor_elem = None

        for book_part in self.book_parts:
            body = book_part.html.find("body")
            for e in body.iter("*"):
                if "id" in e.attrib and not visible_elements_before(e):

                    uri = book_part.filename + "#" + e.get("id")
                    if self.DEBUG: self.log.debug("no visible element before %s" % uri)
                    for anchor,a_uri in self.anchor_uri.items():
                        if (a_uri == uri) and (anchor not in self.immovable_anchors):
                            self.anchor_uri[anchor] = urllib.quote(book_part.filename)
                            if self.DEBUG: self.log.debug("   moved anchor %s" % anchor)

        for book_part in self.book_parts:
            body = book_part.html.find("body")
            for e in body.iter("*"):
                if (e.tag == "a") and ("href-anchor" in e.attrib):

                    e.set("href", urlrelpath(self.get_anchor_uri(unicode(e.attrib.pop("href-anchor"))), ref_from=book_part.filename))

        if self.book_parts:
            for g_type, g_title, g_anchor in self.guide:
                if g_type == "$233":
                    cover_page = self.get_anchor_uri(g_anchor)
                    break
            else:
                cover_page = self.book_parts[0].filename

            for book_part in self.book_parts:
                if book_part.filename == cover_page:
                    book_part.is_cover = True

                    if book_part.part_index != 0:
                        self.log.warning("Cover page is not first in book: %s" % cover_page)

                    break
            else:
                self.log.warning("Cover page %s not found in book" % cover_page)

    def create_ncx(self):
        if self.GENERATE_EPUB2_COMPATIBLE or not self.generate_epub3:
            if len(self.ncx_toc) == 0:
                content_anchor = "**Content**"
                self.anchor_uri[content_anchor] = self.TEXT_FILEPATH % 0
                self.ncx_toc.append(("Content", content_anchor, []))

            doctype = "" if self.generate_epub3 else \
                "<!DOCTYPE ncx PUBLIC \"-//NISO//DTD ncx 2005-1//EN\" \"http://www.daisy.org/z3986/2005/ncx-2005-1.dtd\">\n"

            xml_str = ("<?xml version='1.0' encoding='utf-8'?>\n"
                    "%s<ncx version=\"2005-1\" xmlns=\"http://www.daisy.org/z3986/2005/ncx/\">"
                    "<head><meta name=\"dtb:uid\" content=\"%s\"/></head></ncx>") % (doctype, self.uid)

            emit_playorder = len(doctype) > 0

            root = etree.XML(xml_str.encode("utf-8"))
            document = etree.ElementTree(root)
            ncx = document.getroot()

            doc_title = etree.SubElement(ncx, "docTitle")
            doc_title_text = etree.SubElement(doc_title, "text")
            doc_title_text.text = self.title

            for author in self.authors:
                doc_author = etree.SubElement(ncx, "docAuthor")
                doc_author_text = etree.SubElement(doc_author, "text")
                doc_author_text.text = author

            self.nav_id_count = 0
            self.uri_playorder = {}

            if len(self.ncx_toc) > 0:
                nav_map = etree.SubElement(ncx, "navMap")
                self.create_navmap(nav_map, self.ncx_toc, emit_playorder)

            if len(self.pagemap) > 0:
                pl = etree.SubElement(ncx, "pageList")

                nl = etree.SubElement(pl, "navLabel")
                nlt = etree.SubElement(nl, "text")
                nlt.text = "Pages"

                for p_label, p_anchor in self.pagemap.items():
                    p_uri = self.get_anchor_uri(p_anchor)

                    pt = etree.SubElement(pl, "pageTarget")
                    pt.set("id", self.fix_html_id("page_%s" % p_label))

                    if re.match("^[0-9]+$", p_label):
                        pt.set("value", p_label)
                        pt.set("type", "normal")
                    elif re.match("^[ivx]+$", p_label, flags=re.IGNORECASE):
                        pt.set("value", unicode(roman_to_int(p_label)))
                        pt.set("type", "front")
                    else:
                        pt.set("type", "special")

                    if emit_playorder:
                        pt.set("playOrder", self.get_next_playorder(p_uri))

                    nl = etree.SubElement(pt, "navLabel")
                    nlt = etree.SubElement(nl, "text")
                    nlt.text = p_label

                    ct = etree.SubElement(pt, "content")
                    ct.set("src", urlrelpath(p_uri, ref_from=self.NCX_FILEPATH))

            self.oebps_files[self.NCX_FILEPATH] = OutputFile(etree.tostring(document, encoding="utf-8",
                        pretty_print=True, xml_declaration=True), "application/x-dtbncx+xml")

            self.manifest.append(ManifestEntry(self.NCX_FILEPATH))

    def get_next_playorder(self, uri):
        if (uri not in self.uri_playorder) or (uri is None):
            self.uri_playorder[uri] = unicode(len(self.uri_playorder) + 1)

        return self.uri_playorder[uri]

    def create_navmap(self, root, ncx_toc, emit_playorder):
        for ch_title, ch_anchor, ch_subtoc in ncx_toc:
            ch_uri = self.get_anchor_uri(ch_anchor) if ch_anchor else None

            nav_point = etree.SubElement(root, "navPoint")
            nav_point.set("id", "nav" + unicode(self.nav_id_count))

            if emit_playorder:
                nav_point.set("playOrder", self.get_next_playorder(ch_uri))

            self.nav_id_count += 1

            nav_label = etree.SubElement(nav_point, "navLabel")
            nav_label_text = etree.SubElement(nav_label, "text")
            nav_label_text.text = ch_title

            if ch_uri:
                content = etree.SubElement(nav_point, "content")
                content.set("src", urlrelpath(ch_uri, ref_from=self.NCX_FILEPATH))

            if ch_subtoc:
                self.create_navmap(nav_point, ch_subtoc, emit_playorder)

    def create_epub3_nav(self):
        if self.generate_epub3:
            opf_properties = {"nav"}
            if self.fixed_layout: opf_properties.add("rendition:layout-reflowable")

            book_part = self.new_book_part(filename=self.NAV_FILEPATH, opf_properties=opf_properties, linear=None)

            self.link_css_file(book_part, self.STYLES_CSS_FILEPATH)

            body = self.SubElement(book_part.html, "body")
            self.add_style(body, {"display": "none"})

            nav = self.SubElement(body, "nav")
            nav.set("epub:type", "toc")

            h1 = self.SubElement(nav, "h1")
            h1.text = "Table of contents"

            self.create_nav_list(nav, self.ncx_toc)

            if self.guide:
                nav = self.SubElement(body, "nav")
                nav.set("epub:type", "landmarks")

                h2 = self.SubElement(nav, "h2")
                h2.text = "Guide"

                ol = self.SubElement(nav, "ol")

                for g_type, g_title, g_anchor in self.guide:
                    li = self.SubElement(ol, "li")
                    a = self.SubElement(li, "a")

                    if g_type in EPUB3_VOCABULARY:
                        a.set("epub:type", EPUB3_VOCABULARY[g_type])

                    a.set("href-anchor", g_anchor)
                    a.text = g_title or GUIDE_TYPE_OF_LANDMARK_TYPE[g_type]

            if len(self.pagemap) > 0:
                nav = self.SubElement(body, "nav")
                nav.set("epub:type", "page-list")

                ol = self.SubElement(nav, "ol")

                for p_label, p_anchor in self.pagemap.items():
                    li = self.SubElement(ol, "li")
                    a = self.SubElement(li, "a")
                    a.set("href-anchor", p_anchor)
                    a.text = p_label

    def create_nav_list(self, parent, ncx_toc):
        ol = self.SubElement(parent, "ol")

        for ch_title, ch_anchor, ch_subtoc in ncx_toc:
            li = self.SubElement(ol, "li")
            a = self.SubElement(li, "a")
            if ch_anchor: a.set("href-anchor", ch_anchor)
            a.text = ch_title or "."

            if ch_subtoc:
                self.create_nav_list(li, ch_subtoc)

    def find_by_id(self, root, id):
        result = root.get_element_by_id(id)
        if result is None:
            raise Exception("get_element_by_id could not locate id %s" % id)

        return result

def roman_to_int(input):
    input = input.upper()
    nums = ["M", "D", "C", "L", "X", "V", "I"]
    ints = [1000, 500, 100, 50,  10,  5,   1]
    places = []
    for c in input:

        if c not in nums:
            return 0

    for i in range(len(input)):
        c = input[i]
        value = ints[nums.index(c)]

        try:
            nextvalue = ints[nums.index(input[i + 1])]
            if nextvalue > value:
                value *= -1
        except IndexError:
            pass

        places.append(value)

    sum = 0
    for n in places: sum += n

    return sum

def root_element(elem):
    while elem.getparent() is not None:
        elem = elem.getparent()

    return elem

def visible_elements_before(elem, root=None):

    if root is None:
        root = elem
        while root.tag != "body":
            root = root.getparent()

    if elem is root:
        return False

    for e in root.findall(".//*"):
        if e is elem:
            break

        if e.tag in ["img", "br", "hr"]:
            return True

        if e.text or e.tail:
            return True

    return False

