from __future__ import (unicode_literals, division, absolute_import, print_function)

from lxml import etree
import datetime
import urllib
import uuid

from .misc import urlrelpath
from .yj_to_epub_navigation import GUIDE_TYPE_OF_LANDMARK_TYPE
from .yj_to_epub_properties import (DEFAULT_FONT_NAMES, unquote_font_name, value_str)
from .yj_to_epub_resources import OutputFile
from .yj_structure import METADATA_NAMES

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

DEFAULT_DOCUMENT_FONT_FAMILY = "serif"
DEFAULT_DOCUMENT_LINE_HEIGHT = "1.2em"
DEFAULT_DOCUMENT_FONT_SIZE = "1em"

PRIMARY_WRITING_MODE = {
    ("horizontal-tb", "ltr"): "horizontal-lr",
    ("horizontal-tb", "rtl"): "horizontal-rl",
    ("vertical-lr", "ltr"): "vertical-lr",
    ("vertical-rl", "rtl"): "vertical-rl",
    }

ORIENTATIONS = {
    "$385": "portrait",
    "$386": "landscape",
    "$349": "none",
    }

ITEM_PROPERTIES = {"cover-image", "mathml", "nav", "remote-resources", "scripted", "svg", "switch"}

ITEMREF_PROPERTIES = {"page-spread-left", "page-spread-right", "rendition:align-x-center",
    "rendition:flow-auto", "rendition:flow-paginated", "rendition:flow-scrolled-continuous",
    "rendition:flow-scrolled-doc", "rendition:layout-pre-paginated", "rendition:layout-reflowable",
    "rendition:orientation-auto", "rendition:orientation-landscape", "rendition:orientation-portrait",
    "rendition:page-spread-center", "rendition:spread-auto", "rendition:spread-both",
    "rendition:spread-landscape", "rendition:spread-none", "rendition:spread-portrait",

    "facing-page-left", "facing-page-right", "layout-blank"}

OPF_PROPERTIES = ITEM_PROPERTIES | ITEMREF_PROPERTIES

class EPUBMetadata(object):

    def process_document_data(self):

        document_data = self.book_data.pop("$538", {})

        if "$433" in document_data:
            orientation_lock_ = document_data.pop("$433")
            if orientation_lock_ in ORIENTATIONS:
                self.orientation_lock = ORIENTATIONS[orientation_lock_]
            else:
                self.log.error("Unexpected orientation_lock: %s" % orientation_lock_)
                self.orientation_lock = "none"
        else:
            self.orientation_lock = "none"

        if "$436" in document_data:
            selection = document_data.pop("$436")
            if selection not in ["$442", "$441"]:
                self.log.error("Unexpected document selection: %s" % selection)

        if "$477" in document_data:
            spacing_percent_base = document_data.pop("$477")
            if spacing_percent_base != "$56":
                self.log.error("Unexpected document spacing_percent_base: %s" % spacing_percent_base)

        if "$581" in document_data:
            pan_zoom = document_data.pop("$581")
            if pan_zoom != "$441":
                self.log.error("Unexpected document pan_zoom: %s" % pan_zoom)

        if "$665" in document_data:
            self.book_type = "comic"
            comic_panel_view_mode = document_data.pop("$665")
            if comic_panel_view_mode != "$666":
                self.log.error("Unexpected comic panel view mode: %s" % comic_panel_view_mode)

        if "$668" in document_data:

            auto_contrast = document_data.pop("$668")
            if auto_contrast != "$573":
                self.log.error("Unexpected auto_contrast: %s" % auto_contrast)

        document_data.pop("$597", None)

        self.reading_orders = document_data.pop("$169", [])

        doc_style = self.process_content_properties(document_data)

        column_count = doc_style.pop("column-count", "auto")
        if column_count != "auto":
            self.log.warning("Unexpected document column_count: %s" % column_count)

        self.page_progression_direction = doc_style.pop("direction", "ltr")

        self.default_font_family = unquote_font_name(doc_style.pop("font-family", DEFAULT_DOCUMENT_FONT_FAMILY))

        for default_name in DEFAULT_FONT_NAMES:
            self.font_name_replacements[default_name] = self.default_font_family

        font_size = doc_style.pop("font-size", DEFAULT_DOCUMENT_FONT_SIZE)
        if font_size != DEFAULT_DOCUMENT_FONT_SIZE:
            self.log.warning("Unexpected document font-size: %s" % font_size)

        line_height = doc_style.pop("line-height", DEFAULT_DOCUMENT_LINE_HEIGHT)
        if line_height != DEFAULT_DOCUMENT_LINE_HEIGHT:
            self.log.warning("Unexpected document line-height: %s" % line_height)

        self.writing_mode = doc_style.pop("writing-mode", "horizontal-tb")
        if self.writing_mode != "horizontal-tb":
            self.log.warning("Unexpected document writing-mode: %s" % self.writing_mode)

        self.check_empty(doc_style, "document data styles")
        self.check_empty(document_data, "$538")

    def process_content_features(self):

        content_features = self.book_data.pop("$585", {})

        for feature in content_features.pop("$590", []):

            key = "%s/%s" % (feature.pop("$586", ""), feature.pop("$492", ""))
            version_info = feature.pop("$589", {})
            version = version_info.pop("$5", {})
            version.pop("$587", "")
            version.pop("$588", "")

            self.check_empty(version_info, "content_features %s version_info" % key)
            self.check_empty(feature, "content_features %s feature" % key)

        if content_features.pop("$598", content_features.pop("$155", "$585")) != "$585":
            self.log.error("content_features kfx_id is incorrect")

        self.check_empty(content_features, "$585")

    def process_metadata(self):

        self.asin = ""
        self.title = ""
        self.authors = []
        self.publisher = ""
        self.pubdate = ""
        self.description = ""
        self.language = ""
        self.source_language = self.target_language = ""
        self.is_sample = self.is_magazine = self.is_dictionary = False
        self.cover_resource = None
        self.cover_location = None

        book_metadata = self.book_data.pop("$490", {})

        for categorised_metadata in book_metadata.pop("$491", []):
            category = categorised_metadata.pop("$495")
            for metadata in categorised_metadata.pop("$258"):
                key = metadata.pop("$492")
                self.process_metadata_item(category, key, metadata.pop("$307"))
                self.check_empty(metadata, "categorised_metadata %s/%s" % (category, key))

            self.check_empty(categorised_metadata, "categorised_metadata %s" % category)

        self.check_empty(book_metadata, "$490")

        for key, value in self.book_data.pop("$258", {}).items():
            self.process_metadata_item("", METADATA_NAMES.get(key, unicode(key)), value)

        if self.asin:
            self.uid = "urn:asin:" + self.asin
        else:
            self.uid = "urn:uuid:" + unicode(uuid.uuid4())

        if not self.authors:
            self.authors = ["Unknown"]

        if not self.title:
            self.title = "Unknown"

        if self.is_sample:
            self.title += " - Sample"

        desc = []
        if self.is_dictionary: desc.append("dictionary")
        if self.is_sample: desc.append("sample")
        if self.fixed_layout: desc.append("fixed layout")
        if self.illustrated_layout: desc.append("illustrated layout")
        if self.book_type: desc.append(self.book_type)
        if self.cde_content_type: desc.append(self.cde_content_type)

        if desc:
            self.log.info("Format is %s" % " ".join(desc))

    def process_metadata_item(self, category, key, value):

        cat_key = "%s/%s" % (category, key) if category else key

        if cat_key == "kindle_title_metadata/ASIN" or cat_key == "ASIN":
            if not self.asin: self.asin = value
        elif cat_key == "kindle_title_metadata/author":
            if value:
                self.authors.insert(0, value)
        elif cat_key == "author":
            if not self.authors: self.authors = [a.strip() for a in value.split("&") if a]
        elif cat_key == "kindle_title_metadata/cde_content_type" or cat_key == "cde_content_type":
            self.cde_content_type = value
            if value == "MAGZ":
                self.book_type = "magazine"
                self.is_magazine = True
            elif value == "EBSP":
                self.is_sample = True
        elif cat_key == "kindle_title_metadata/description" or cat_key == "description":
            self.description = value.strip()
        elif cat_key == "kindle_title_metadata/cover_image":
            self.cover_resource = value
        elif cat_key == "cover_image":
            self.cover_resource = value
        elif cat_key == "kindle_title_metadata/issue_date":
            self.pubdate = value
        elif cat_key == "kindle_title_metadata/language" or cat_key == "language":
            self.language = value
        elif cat_key == "kindle_title_metadata/publisher" or cat_key == "publisher":
            self.publisher = value
        elif cat_key == "kindle_title_metadata/title" or cat_key == "title":
            if not self.title: self.title = value
        elif cat_key == "kindle_ebook_metadata/book_orientation_lock":
            if value != self.orientation_lock:
                self.log.error("Conflicting orientation lock values: %s, %s" % (self.orientation_lock, value))
            self.orientation_lock = value
        elif cat_key == "kindle_title_metadata/dictionary_lookup":
            self.is_dictionary = True
            self.source_language = value.pop("$474")
            self.target_language = value.pop("$163")
            self.check_empty(value, "kindle_title_metadata/dictionary_lookup")
        elif cat_key == "kindle_title_metadata/is_dictionary":
            self.is_dictionary = value
        elif cat_key == "kindle_title_metadata/is_sample":
            self.is_sample = value
        elif cat_key == "kindle_capability_metadata/continuous_popup_progression":
            self.book_type = "comic"
        elif cat_key == "kindle_capability_metadata/yj_fixed_layout":
            self.fixed_layout = True
        elif cat_key == "kindle_capability_metadata/yj_publisher_panels":
            self.book_type = "comic"
            self.region_magnification = True
        elif cat_key == "kindle_capability_metadata/yj_facing_page":
            self.book_type = "comic"
        elif cat_key == "kindle_capability_metadata/yj_double_page_spread":
            self.book_type = "comic"
        elif cat_key == "kindle_capability_metadata/yj_textbook":
            self.book_type = "textbook"
        elif cat_key == "kindle_capability_metadata/yj_illustrated_layout":
            self.illustrated_layout = True
        elif cat_key == "reading_orders":
            if not self.reading_orders:
                self.reading_orders = value
        elif cat_key == "support_landscape":
            if value is False and self.orientation_lock == "none":
                self.orientation_lock = "portrait"
        elif cat_key == "support_portrait":
            if value is False and self.orientation_lock == "none":
                self.orientation_lock = "landscape"

    def create_opf(self):
        rendition_prefix = False

        xml_str = ("<?xml version='1.0' encoding='utf-8'?>\n"
                "<package version=\"%s\" xmlns=\"http://www.idpf.org/2007/opf\" unique-identifier=\"bookid\">"
                "<metadata xmlns:dc=\"http://purl.org/dc/elements/1.1/\" xmlns:opf=\"http://www.idpf.org/2007/opf\">"
                "</metadata></package>") % self.epub_version

        root = etree.XML(xml_str.encode("utf-8"))
        document = etree.ElementTree(root)
        package = document.getroot()
        metadata = package.find("{*}metadata")

        identifier = etree.SubElement(metadata, "{http://purl.org/dc/elements/1.1/}identifier")
        identifier.set("id", "bookid")
        identifier.text = self.uid

        if self.uid.startswith("urn:uuid:") and not self.generate_epub30:
            identifier.set("{http://www.idpf.org/2007/opf}scheme", "uuid")

        title = etree.SubElement(metadata, "{http://purl.org/dc/elements/1.1/}title")
        title.text = self.title

        for i,author in enumerate(self.authors):
            creator = etree.SubElement(metadata, "{http://purl.org/dc/elements/1.1/}creator")
            creator.text = author

            if self.generate_epub30:

                author_id = "creator%d" % i
                creator.set("id", author_id)

                meta_refines = etree.SubElement(metadata, "meta")
                meta_refines.set("refines", "#" + author_id)
                meta_refines.set("property", "role")
                meta_refines.text = "aut"

            else:

                creator.set("{http://www.idpf.org/2007/opf}role", "aut")

        language = etree.SubElement(metadata, "{http://purl.org/dc/elements/1.1/}language")
        language.text = self.language if self.language else "und"

        if self.publisher:
            publisher = etree.SubElement(metadata, "{http://purl.org/dc/elements/1.1/}publisher")
            publisher.text = self.publisher

        if self.pubdate:
            pubdate = etree.SubElement(metadata, "{http://purl.org/dc/elements/1.1/}date")

            if not self.generate_epub3:
                pubdate.set("{http://www.idpf.org/2007/opf}event", "publication")

            pubdate.text = unicode(self.pubdate)[0:10]

        if self.description:
            description = etree.SubElement(metadata, "{http://purl.org/dc/elements/1.1/}description")
            description.text = self.description

        if self.generate_epub3:
            meta_dcterms_modified = etree.SubElement(metadata, "meta")
            meta_dcterms_modified.set("property", "dcterms:modified")
            meta_dcterms_modified.text = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

        if self.fixed_layout:
            if self.generate_epub3:
                rendition_prefix = True
                meta_rendition_layout = etree.SubElement(metadata, "meta")
                meta_rendition_layout.set("property", "rendition:layout")
                meta_rendition_layout.text = "pre-paginated"

            meta_fixed_layout = etree.SubElement(metadata, "meta")
            meta_fixed_layout.set("name", "fixed-layout")
            meta_fixed_layout.set("content", "true")

            if self.original_width and self.original_height:

                if self.orientation_lock == "none":
                    self.orientation_lock = "landscape" if self.original_width > self.original_height else "portrait"

                meta_fixed_layout = etree.SubElement(metadata, "meta")
                meta_fixed_layout.set("name", "original-resolution")
                meta_fixed_layout.set("content", "%dx%d" % (self.original_width, self.original_height))

                if self.generate_epub30:
                    meta_rendition_viewport = etree.SubElement(metadata, "meta")
                    meta_rendition_viewport.set("property", "rendition:viewport")
                    meta_rendition_viewport.text = "width=%s, height=%s" % (self.original_width, self.original_height)

        if self.book_type:
            meta_fixed_layout = etree.SubElement(metadata, "meta")
            meta_fixed_layout.set("name", "book-type")
            meta_fixed_layout.set("content", self.book_type)

        if self.orientation_lock  != "none":
            if self.generate_epub3:
                rendition_prefix = True
                meta_rendition_layout = etree.SubElement(metadata, "meta")
                meta_rendition_layout.set("property", "rendition:orientation")

                meta_rendition_layout.text = self.orientation_lock if self.orientation_lock != "none" else "auto"

            meta_fixed_layout = etree.SubElement(metadata, "meta")
            meta_fixed_layout.set("name", "orientation-lock")
            meta_fixed_layout.set("content", self.orientation_lock)

        primary_writing_mode = PRIMARY_WRITING_MODE.get((self.writing_mode, self.page_progression_direction))
        if primary_writing_mode is None:
            self.log.error("Cannot determine primary-writing-mode for mode %s and direction %s" % (self.writing_mode, self.page_progression_direction))
        elif primary_writing_mode != "horizontal-lr":

            meta_fixed_layout = etree.SubElement(metadata, "meta")
            meta_fixed_layout.set("name", "primary-writing-mode")
            meta_fixed_layout.set("content", primary_writing_mode)

        if self.region_magnification:
            meta_fixed_layout = etree.SubElement(metadata, "meta")
            meta_fixed_layout.set("name", "RegionMagnification")
            meta_fixed_layout.set("content", "true")

            if self.virtual_panels:
                self.log.error("Virtual panels used with region magnification")

        if self.illustrated_layout:
            meta_fixed_layout = etree.SubElement(metadata, "meta")
            meta_fixed_layout.set("name", "amzn:kindle-illustrated")
            meta_fixed_layout.set("content", "true")

            meta_fixed_layout = etree.SubElement(metadata, "meta")
            meta_fixed_layout.set("name", "amzn:cover-as-html")
            meta_fixed_layout.set("content", "true")

        if self.min_aspect_ratio:
            meta_fixed_layout = etree.SubElement(metadata, "meta")
            meta_fixed_layout.set("name", "amzn:min-aspect-ratio")
            meta_fixed_layout.set("content", value_str(self.min_aspect_ratio))

        if self.max_aspect_ratio:
            meta_fixed_layout = etree.SubElement(metadata, "meta")
            meta_fixed_layout.set("name", "amzn:max-aspect-ratio")
            meta_fixed_layout.set("content", value_str(self.max_aspect_ratio))

        if self.is_dictionary:
            x_metadata = etree.SubElement(metadata, "x-metadata")

            in_language = etree.SubElement(x_metadata, "DictionaryInLanguage")
            in_language.text = self.source_language

            out_language = etree.SubElement(x_metadata, "DictionaryOutLanguage")
            out_language.text = self.target_language

        if rendition_prefix:
            package.set("prefix", "rendition: http://www.idpf.org/vocab/rendition/#")

        man = etree.SubElement(package, "manifest")
        spine = etree.SubElement(package, "spine")

        if self.GENERATE_EPUB2_COMPATIBLE or not self.generate_epub3:
            spine.set("toc", self.file_id(self.NCX_FILEPATH))

        if self.generate_epub3 and self.page_progression_direction != "ltr":
            spine.set("page-progression-direction", self.page_progression_direction)

        used_ids = {}

        for manifest_entry in self.manifest:
            id = self.file_id(manifest_entry.filename)
            mimetype = self.oebps_files[manifest_entry.filename].mimetype

            if id in used_ids:
                if used_ids[id] != (manifest_entry.filename, mimetype):
                    self.log.error("Conflicting manifest id %s for %s (%s) and %s (%s)" % (
                            id, used_ids[id][0], used_ids[id][1], manifest_entry.filename, mimetype))
            else:
                item = etree.SubElement(man, "item")
                item.set("id", id)
                item.set("href", urlrelpath(urllib.quote(manifest_entry.filename), ref_from=self.OPF_FILEPATH))
                item.set("media-type", mimetype)

                if manifest_entry.filename == self.cover_location and not self.illustrated_layout:

                    meta_cover = etree.SubElement(metadata, "meta")
                    meta_cover.set("name", "cover")
                    meta_cover.set("content", id)

                    if self.generate_epub3:
                        manifest_entry.opf_properties.add("cover-image")

                elif manifest_entry.linear is not None:
                    itemref = etree.SubElement(spine, "itemref")
                    itemref.set("idref", id)

                    itemref_properties = manifest_entry.opf_properties & ITEMREF_PROPERTIES
                    if len(itemref_properties):
                        itemref.set("properties", " ".join(sorted(list(itemref_properties))))

                    if self.generate_epub3 and manifest_entry.linear is False:
                        itemref.set("linear", "no")

                item_properties = manifest_entry.opf_properties & ITEM_PROPERTIES
                if len(item_properties):
                    item.set("properties", " ".join(sorted(list(item_properties))))

                unknown_properties = manifest_entry.opf_properties - OPF_PROPERTIES
                if len(unknown_properties):
                    self.log.error("Manifest file %s has %d unknown OPF properties: '%s'" % (
                                manifest_entry.filename, len(unknown_properties), " ".join(sorted(list(unknown_properties)))))

                used_ids[id] = (manifest_entry.filename, mimetype)

        if self.guide and (self.GENERATE_EPUB2_COMPATIBLE or not self.generate_epub3):
            gd = etree.SubElement(package, "guide")

            for g_type, g_title, g_anchor in self.guide:
                ref = etree.SubElement(gd, "reference")
                if g_title: ref.set("title",g_title)
                ref.set("type", GUIDE_TYPE_OF_LANDMARK_TYPE[g_type])
                ref.set("href", urlrelpath(self.get_anchor_uri(g_anchor), ref_from=self.OPF_FILEPATH))

        self.oebps_files[self.OPF_FILEPATH] = OutputFile(etree.tostring(document, encoding="utf-8",
                    pretty_print=True, xml_declaration=True), "application/oebps-package+xml")

    def container_xml(self):
        xml_str = ("<?xml version='1.0' encoding='utf-8' standalone='yes'?>\n"
                "<container version=\"1.0\" xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\">"
                "<rootfiles><rootfile full-path=\"%s\" media-type=\"application/oebps-package+xml\" />"
                "</rootfiles></container>") % (self.OEBPS_DIR + self.OPF_FILEPATH)

        root = etree.XML(xml_str.encode("utf-8"))
        document = etree.ElementTree(root)
        return etree.tostring(document, encoding="utf-8", pretty_print=True, xml_declaration=True)

