from __future__ import (unicode_literals, division, absolute_import, print_function)

import collections
from lxml import etree
import lxml.html
import re
import urllib

from .yj_to_epub_properties import YJ_PROPERTY_NAMES
from .yj_to_epub_resources import (ManifestEntry, OutputFile)

from .ion import (
            ion_type, IonList, IonString, IonStruct, IonSymbol)

from .misc import (json_serialize_compact, list_keys, urlrelpath, type_name, make_unique_name)

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

CHECK_UNEXPECTED_CHARS = True

REPLACE_WEBP_VIDEO_TEST = False

USE_CSS_RESET_ON_COVERS = False

REPORT_CONFLICTING_VIEWPORTS = False

RESTORE_MATHML_FROM_ANNOTATION = False

LIST_STYLES = {
    "$346": ("ol", "lower-alpha"),
    "$347": ("ol", "upper-alpha"),
    "$342": ("ul", "circle"),
    "$340": ("ul", "disc"),
    "$271": ("ul", "disc"),
    "$349": ("ul", "none"),
    "$343": ("ol", "decimal"),
    "$344": ("ol", "lower-roman"),
    "$345": ("ol", "upper-roman"),
    "$341": ("ul", "square"),
    }

LIST_STYLE_POSITIONS = {
    "$552": "inside",
    "$553": "outside",
    }

CLASSIFICATION_EPUB_TYPE = {
    "$618": "annotation", # or "sidebar"?
    "$619": "rearnote",
    "$281": "footnote",
    }

NBSP = "\u00a0"

TEMP_TAG = "temporary-tag"

class BookPart(object):
    def __init__(self, filename, part_index, html, head, opf_properties=set(), linear=None, omit=False):
        self.filename = filename
        self.part_index = part_index
        self.html = html
        self.head = head
        self.opf_properties = set(opf_properties)
        self.linear = linear
        self.omit = omit

        self.viewport_height = self.viewport_width = None
        self.is_cover = False

class EPUBContent(object):

    def process_reading_orders(self):
        if len(self.reading_orders) == 1 and not self.reading_order_name:
            self.reading_order_name = self.reading_orders[0]["$178"]

        if len(self.reading_orders) > 1:
            self.log.warning("Found %d reading orders. Using: %s" % (len(self.reading_orders), self.reading_order_name))

        for reading_order in self.reading_orders:
            if reading_order["$178"] == self.reading_order_name:

                for section_ in reading_order["$170"]:

                    self.process_section(self.get_fragment(ftype="$260", fid=section_))
                break

        else:
            raise Exception("Failed to find reading order %s" % self.reading_order_name)

    def process_section(self, section):
        section_name = section.pop("$174")
        if self.DEBUG: self.log.debug("Processing section %s" % section_name)
        self.content_context = "section %s" % section_name

        page_templates = section.pop("$141")

        if self.book_type == "comic":
            self.process_comic_page_template(self.get_fragment(ftype="$608", fid=page_templates[0]), section_name)

        elif self.book_type in {"magazine", "textbook"}:

            templates_processed = 0

            for i,page_template in enumerate(page_templates):
                if self.evaluate_binary_condition(page_template.pop("$171", "true")):
                    page_template.pop("$159")
                    page_template.pop("$156")

                    book_part = self.new_book_part()
                    self.link_css_file(book_part, self.STYLES_CSS_FILEPATH)
                    self.add_content(page_template, book_part.html, book_part, True)
                    self.process_position(self.get_location_id(page_template), 0, book_part.html.find("body"))

                    self.check_empty(page_template, "%s conditional page_template %d" % (self.content_context, i))
                    templates_processed += 1

            if templates_processed != 1:
                self.log.error("%s has %d active conditional page templates" % (self.content_context, templates_processed))

        else:

            if len(page_templates) != 1:
                self.log.error("E-book %s contains %s page templates" % (self.content_context, len(page_templates)))

            book_part = self.new_book_part()
            self.process_content(page_templates[0], book_part.html, book_part)
            self.link_css_file(book_part, self.STYLES_CSS_FILEPATH)
            self.check_empty(page_templates[0], "%s page_template" % self.content_context)

        self.check_empty(section, self.content_context)

    def process_comic_page_template(self, page_template, section_name, page_spread="", parent_template_id=None):
        if (page_template["$159"] == "$270" and
                page_template["$156"] in ["$437", "$438"]):

            page_template.pop("$159")
            layout = page_template.pop("$156")

            virtual_panel = page_template.pop("$434", None)
            if virtual_panel is None:
                if self.book_type == "comic" and not self.region_magnification:
                    self.log.error("Section %s has missing virtual panel in comic without region magnification" % section_name)
            elif virtual_panel == "$441":
                self.virtual_panels = True
            else:
                self.log.warning("Unexpected virtual_panel: %s" % virtual_panel)

            parent_template_id = page_template.pop("$155")
            story = self.get_named_fragment(page_template, ftype="$259")
            story_name = story.pop("$176")
            if self.DEBUG: self.log.debug("Processing %s story %s" % (layout, story_name))
            saved_content = self.content_context
            self.content_context = "story %s" % story_name

            LAYOUTS = {
                "$437": "page-spread",
                "$438": "facing-page",
                }

            base_property = LAYOUTS[layout]
            left_property = base_property + "-left"
            right_property = base_property + "-right"

            page_property = left_property if self.page_progression_direction == "ltr" else right_property
            for page_template_ in story.pop("$146", []):
                if not self.generate_epub3: page_property = ""
                self.process_comic_page_template(page_template_, section_name, page_property, parent_template_id)
                page_property = left_property if page_property == right_property else right_property
                parent_template_id = None

            self.check_empty(story, "story %s" % story_name)
            self.content_context = saved_content

        elif (page_template["$159"] == "$270" and
                    page_template["$156"] == "$323" and
                    page_template.get("$656", False)):

            page_template.pop("$159")
            page_template.pop("$156")
            page_template.pop("$656")

            connected_pagination = page_template.pop("$655", 0)
            if connected_pagination != 2:
                self.log.error("Unexpected connected_pagination: %d" % connected_pagination)

            parent_template_id = page_template.pop("$155")
            story = self.get_named_fragment(page_template, ftype="$259")
            story_name = story.pop("$176")
            if self.DEBUG: self.log.debug("Processing page_spread story %s" % story_name)
            saved_content = self.content_context
            self.content_context = "story %s" % story_name

            for page_template_ in story.pop("$146", []):
                self.process_comic_page_template(page_template_, section_name,
                        "rendition:page-spread-center" if self.generate_epub3 else "", parent_template_id)
                parent_template_id = None

            self.check_empty(story, "story %s" % story_name)
            self.content_context = saved_content

        else:
            book_part = self.new_book_part(opf_properties=set(page_spread.split()))
            self.process_content(page_template, book_part.html, book_part)
            self.link_css_file(book_part, self.STYLES_CSS_FILEPATH)

            if parent_template_id is not None:
                self.process_position(unicode(parent_template_id), 0, book_part.html.find("body"))

        self.check_empty(page_template, "Section %s page_template" % section_name)

    def process_story(self, story, parent, book_part):
        story_name = story.pop("$176")
        if self.DEBUG: self.log.debug("Processing story %s" % story_name)

        saved_content = self.content_context
        self.content_context = "story %s" % story_name

        location_id = self.get_location_id(story)
        if location_id:
            self.process_position(location_id, 0, parent)

        self.process_content_list(story.pop("$146", []), parent, book_part)

        self.check_empty(story, self.content_context)

        self.content_context = saved_content

    def add_content(self, content, parent, book_part, content_layout=None):
        if "$145" in content:
            text_elem = self.SubElement(parent, "span")
            text_elem.text = self.content_text(content.pop("$145"))

        elif "$146" in content:
            self.process_content_list(content.pop("$146", []), parent, book_part, content_layout=content_layout)

        elif "$176" in content:
            story_content = self.get_named_fragment(content, ftype="$259")
            self.process_story(story_content, parent, book_part)

    def process_content_list(self, content_list, parent, book_part, content_layout=None):

        if ion_type(content_list) is not IonList:
            raise Exception("%s has unknown content_list data type: %s" % (self.content_context, unicode(type(content_list))))

        for content in content_list:
            self.process_content(content, parent, book_part, content_layout=content_layout)

    def process_content(self, content, parent, book_part, content_layout=None):
        if self.DEBUG: self.log.debug("\nprocess content: %s\n" % repr(content))
        data_type = ion_type(content)

        if data_type is IonString:

            content_elem = self.SubElement(parent, "span")
            content_elem.text = content
            return

        if data_type is IonSymbol:
            self.process_content(self.get_fragment(ftype="$608", fid=content), parent, book_part)
            return

        if data_type is not IonStruct:
            self.log.info("content: %s" % repr(content))
            raise Exception("%s has unknown content data type: %s" % (self.content_context, type_name(content)))

        content_elem = lxml.html.Element("unknown")
        content_type = content.pop("$159")
        top_level = (parent.tag == "html")
        add_container = fit_width = discard = False

        if "$157" in content:
            style_name = unicode(self.get_structure_name(content, "$157"))
            self.set_kfx_class(content_elem, style_name)
        else:
            style_name = "inline"

        if content_type == "$269":
            content_elem.tag = "div"

            content.pop("$597", None)

            if "$605" in content:

                word_iteration_type = content.pop("$605")
                if word_iteration_type != "$604":
                    self.log.warning("%s has text word_iteration_type=%s" % (self.content_context, word_iteration_type))

            self.add_content(content, content_elem, book_part)

        elif content_type == "$271":
            content_elem.tag = "img"
            content_elem.set("src", urlrelpath(self.process_external_resource(
                        self.get_fragment_name(content, "$164")), ref_from=book_part.filename))
            content_elem.set("alt", content.pop("$584", ""))

            render = content.pop("$601", None)
            if render is None:
                add_container = True
            elif render == "$283":
                if top_level:
                    self.log.error("Found inline image without container")
            else:
                self.log.error("%s has unknown image render: %s" % (self.content_context, render))

        elif content_type == "$274":

            resource_name = content.pop("$175")

            raw_media = self.process_external_resource(resource_name, save=False, plugin=True).decode("utf-8")

            alt_text = content.pop("$584", "")
            content.pop("$597", None)

            plugin_type = raw_media.partition("::")[0].replace("\n", "")
            self.log.error("Cannot convert %s plugin resource %s" % (plugin_type, resource_name))

            if True:
                content_elem.tag = "object"
                src = self.process_external_resource(resource_name, plugin=True)
                content_elem.set("data", urlrelpath(src, ref_from=book_part.filename))
                content_elem.set("type", self.oebps_files[src].mimetype)

                self.add_content(content, content_elem, book_part)

                if len(content_elem) == 0:
                    content_elem.text = alt_text or "Cannot display %s content" % plugin_type

        elif content_type in {"$270", "$439"}:
            layout = content.pop("$156")
            content_elem.tag = "div"

            self.add_content(content, content_elem, book_part, content_layout=layout)

            if content_type == "$439":

                self.add_style(content_elem, {"display": "none"})

            if layout == "$323":

                pass

            elif layout == "$326":

                if "$434" in content:
                    virtual_panel = content.pop("$434")
                    if virtual_panel == "$441":
                        self.virtual_panels = True
                    else:
                        self.log.warning("Unexpected container virtual_panel: %s" % virtual_panel)

                fixed_height = content.pop("$67")
                fixed_width = content.pop("$66")

                if self.fixed_layout:
                    if top_level:
                        meta = book_part.head.find("meta")
                        if meta is not None and meta.get("name") == "viewport":
                            self.log.error("Fixed layout html already has viewport when adding")

                        meta = self.SubElement(book_part.head, "meta")
                        self.set_attrib(meta, "name", "viewport")
                        self.set_attrib(meta, "content", "width=%d, height=%d" % (fixed_width, fixed_height))

                        book_part.viewport_width = fixed_width
                        book_part.viewport_height = fixed_height

                        self.link_css_file(book_part, self.RESET_CSS_FILEPATH)
                    else:
                        self.convert_to_svg(content_elem, layout, book_part)

                else:

                    if not top_level:
                        self.log.error("scale_fit container (assumed cover) is not at top level in %s" % self.content_context)

                    self.add_style(content_elem, {"height": "100%",
                            "text-align": "center", "text-indent": "0"})

                    for child in content_elem.findall(".//*"):
                        if child.tag == "img":
                            self.add_style(child, {"height": "100%", "max-width": "100%"})
                            break

                    if USE_CSS_RESET_ON_COVERS:
                        self.link_css_file(book_part, self.RESET_CSS_FILEPATH)

            elif layout == "$324":

                pass

            elif layout == "$325":

                self.log_unsupported("%s has unsupported %s layout: %s" % (self.content_context, content_type, layout), ["magazine"])

                content.pop("$67", None)
                content.pop("$66", None)

            elif layout == "$322":

                self.convert_to_svg(content_elem, layout, book_part)

            else:
                self.log.error("%s has unknown %s layout: %s" % (self.content_context, content_type, layout))

            if "$601" in content:
                render = content.pop("$601")
                if render == "$283":

                    self.add_style(content_elem, {"display": "inline-block"})
                else:
                    raise Exception("%s has unknown container render: %s" % (self.content_context, render))

            if "$475" in content:
                fit_text = content.pop("$475")
                if fit_text != "$472":
                    self.log_unsupported("%s has container fit_text=%s" % (self.content_context, fit_text), ["textbook"])

            if "$684" in content:
                pan_zoom_viewer = content.pop("$684")
                if pan_zoom_viewer != "$441":
                    self.log_error("%s has container pan_zoom_viewer=%s" % (self.content_context, pan_zoom_viewer))

            if content.pop("$69", False):

                self.add_style(content_elem, {"visibility": "hidden"})

            if "$426" in content:
                if not self.region_magnification:
                    self.log.error("activate found without region magnification")
                    self.region_magnification = True

                ordinal = content.pop("$427")

                for activate in content.pop("$426"):
                    action = activate.pop("$428")
                    if action == "$468":

                        activate_elem = self.SubElement(content_elem, "a")
                        activate_elem.set("class", "app-amzn-magnify")

                        activate_elem.set("data-app-amzn-magnify",  json_serialize_compact(collections.OrderedDict([
                                ("targetId", self.register_link_id(activate.pop("$163"), "magnify_target")),
                                ("sourceId", self.register_link_id(activate.pop("$474"), "magnify_source")),
                                ("ordinal", ordinal),
                                ])))

                        self.check_empty(activate, "%s activate" % self.content_context)
                    else:
                        self.log.error("%s has unknown %s action: %s" % (self.content_context, content_type, action))

            if "$429" in content:

                bd_style_name = unicode(self.get_structure_name(content, "$429"))

                if bd_style_name in self.style_definitions:
                    bd_style = self.style_definitions[bd_style_name]

                    if len(bd_style) != 1 or "background-color" not in bd_style:
                        self.log.error("%s has unexpected background style content for %s: %s" % (
                                self.content_context, bd_style_name, bd_style))

                elif bd_style_name not in self.missing_styles:
                    self.log.error("No definition found for backdrop style: %s" % bd_style_name)
                    self.missing_styles.add(bd_style_name)

            if "$683" in content:
                for annotation in content.pop("$683"):
                    annotation_type = annotation.pop("$687")
                    annotation_text = self.content_text(annotation.pop("$145"))

                    if annotation_type == "$690":
                        svg = content_elem.find(".//svg")
                        if svg is None:
                            self.log.error("Missing svg for mathml annotation in: %s" % etree.tostring(content_elem))

                        if RESTORE_MATHML_FROM_ANNOTATION:

                            mathml = etree.fromstring(annotation_text, parser=etree.XMLParser(encoding="utf-8", recover=True))
                            for elem in mathml.iter("*"):
                                elem.attrib.pop("amzn-src-id", None)
                                self.set_attrib(elem, "class", "")

                            if "alttext" not in mathml.attrib:
                                mathml.set("alttext", "")

                            self.set_attrib(mathml, "id", svg.get("id", ""))

                            svg_parent = svg.getparent()
                            svg_index = svg_parent.index(svg)
                            svg_parent.remove(svg)
                            svg_parent.insert(svg_index, mathml)
                        else:
                            desc = lxml.html.Element("desc")
                            desc.text = annotation_text
                            svg.insert(0 if svg[0].tag != "title" else 1, desc)
                    elif annotation_type == "$584":
                        if annotation_text != "no accessible name found.":
                            self.set_attrib(content_elem, "aria-label", annotation_text)
                    else:
                        self.log.warning("%s content has unknown annotation type: %s" % (self.content_context, annotation_type))

                    self.check_empty(annotation, "%s annotation" % self.content_context)

        elif content_type == "$276":
            self.process_list(content_elem, content, False)

            self.add_content(content, content_elem, book_part)

            for child_elem in content_elem:
                if child_elem.tag != "li":

                    self.log.info("%s has a %s inside of a list" % (self.content_context, child_elem.tag))

        elif content_type == "$277":
            if parent.tag not in {"ol", "ul"}:
                self.log.error("%s has list item inside non-list %s element" % (self.content_context, parent.tag))

            self.process_list(content_elem, content, True)

            if "$102" in content:

                list_indent_style = self.convert_yj_properties({"$53": content.pop("$102")})
                if list_indent_style != self.Style({"padding-left": "0"}):

                    try:
                        self.add_style(parent, list_indent_style, replace=Exception)

                    except:
                        try:
                            self.add_style(content_elem, list_indent_style, replace=Exception)
                            self.log.info("added list_indent to content_elem")
                        except:
                            self.log.error("Could not add list_indent since parent and listitem both already have padding-left")

            self.add_content(content, content_elem, book_part)

        elif content_type == "$278":
            content_elem.tag = "table"

            if content.pop("$150", False):
                self.add_style(content_elem, {"border-collapse": "collapse"})

            border_spacing_h = content.pop("$457", None)
            border_spacing_v = content.pop("$456", None)
            if border_spacing_h or border_spacing_v:
                self.add_style(content_elem, {"border-spacing": " ".join(filter(None,
                        [self.property_value("$457", border_spacing_h),
                        self.property_value("$456", border_spacing_v)]))})

            if "$152" in content:
                colgroup_elem = self.SubElement(content_elem, "colgroup")

                for col_fmt in content.pop("$152"):
                    col_elem = self.SubElement(colgroup_elem, "col")
                    if "$118" in col_fmt:
                        self.set_attrib(col_elem, "span", unicode(col_fmt.pop("$118")))

                    col_fmt.pop("$698", False)

                    self.add_style(col_elem, self.convert_yj_properties(col_fmt))

            if "$700" in content:
                for row,col in content.pop("$700", []):
                    pass

            if "$630" in content:
                table_selection_mode = content.pop("$630")
                if table_selection_mode != "$632":
                    self.log.error("%s table has unexpected table_selection_mode: %s" % (self.content_context, table_selection_mode))

            if "$629" in content:
                for table_feature in content.pop("$629"):
                    if table_feature not in {
                            "$581",
                            "$326",
                            "$657"}:
                        self.log.error("%s table has unexpected table_feature: %s" % (self.content_context, table_feature))

            self.add_content(content, content_elem, book_part)

        elif content_type == "$454":
            content_elem.tag = "tbody"
            self.add_content(content, content_elem, book_part)

        elif content_type == "$151":
            content_elem.tag = "thead"
            self.add_content(content, content_elem, book_part)

        elif content_type == "$455":
            content_elem.tag = "tfoot"
            self.add_content(content, content_elem, book_part)

        elif content_type == "$279":
            content_elem.tag = "tr"
            self.add_content(content, content_elem, book_part)

            for child_elem in content_elem:
                if child_elem.tag == "div":
                    child_elem.tag = "td"
                else:
                    self.log.error("Unexpected child %s found in table_row" % child_elem.tag)

        elif content_type == "$596":
            content_elem.tag = "hr"

        elif content_type == "$272":

            content_elem.tag = "svg"
            content_elem.set("xmlns", "http://www.w3.org/2000/svg")
            content_elem.set("version", "1.1")
            content_elem.set("preserveAspectRatio", "xMidYMid meet")

            if "$66" in content:
                content_elem.set("viewBox", "0 0 %d %d" % (content.pop("$66"), content.pop("$67")))

            if "$686" in content:
                kvg_content_type = content.pop("$686", "")
                if kvg_content_type != "$269":
                    self.log.error("%s has unknown kvg_content_type: %s" % (self.content_context, kvg_content_type))

            content_list = content.pop("$146", [])

            for shape in content.pop("$250", []):
                self.process_kvg_shape(content_elem, shape, content_list, book_part)

            self.check_empty(content_list, "KVG content_list")

        else:

            self.log.error("%s has unknown content type: %s" % (self.content_context, content_type))
            content_elem.tag = "div"
            self.add_content(content, content_elem, book_part)

        word_boundary_list = content.pop("$696", None)
        if word_boundary_list is not None:

            if len(word_boundary_list) % 2 == 0:
                SEP_RE = r"^[ \n]*$"
                txt = self.combined_text(content_elem)
                offset = 0

                for i in range(0, len(word_boundary_list), 2):
                    sep_len = word_boundary_list[i]
                    if sep_len < 0 or len(txt)-offset < sep_len:
                        self.log.warning("Unexpected word_boundary_list separator len %d: %s (%d), '%s' (%d)" % (
                                sep_len, unicode(word_boundary_list), i, txt, offset))
                        break

                    sep = txt[offset:offset+sep_len]
                    if not re.match(SEP_RE, sep):
                        self.log.warning("Unexpected word_boundary_list separator character: %s (%d), '%s' (%d)" % (
                                unicode(word_boundary_list), i, txt, offset))

                    offset += sep_len

                    word_len = word_boundary_list[i+1]
                    if word_len <= 0 or len(txt)-offset < word_len:
                        self.log.warning("Unexpected word_boundary_list word len %d: %s (%d), '%s' (%d)" % (
                                word_len, unicode(word_boundary_list), i, txt, offset))
                        break

                    offset += word_len

                if offset < len(txt):
                    sep = txt[offset:]
                    if not re.match(SEP_RE, sep):
                        self.log.warning("Unexpected word_boundary_list final separator character: %s (%d), '%s' (%d)" % (
                                unicode(word_boundary_list), i, txt, offset))

            else:
                self.log.warning("Unexpected word_boundary_list length: %s" % unicode(word_boundary_list))

        if "$622" in content:
            first_line_style = content.pop("$622")
            line_style = self.style_definitions.get(unicode(first_line_style.pop("$173")), "")

            for style_type, style_value in first_line_style.pop("$625", {}).items():
                if style_type == "$623":
                    if style_value != 1:
                        self.log.error("%s has first_line_style_type/number_of_lines: %d" % (self.content_context, style_value))
                else:
                    self.log.error("%s has unknown first_line_style_type: %s" % (self.content_context, style_type))

            self.add_style(content_elem, line_style.partition(name_prefix="-kfx-firstline", add_prefix=True))

            self.check_empty(first_line_style, "%s first_line_style" % self.content_context)

        if content_layout is not None and content_layout == "$324":
            self.add_style(content_elem, {"position": "fixed"})
            add_container = False

        if "$183" in content:
            position = content.pop("$183")
            if position == "$455":
                self.add_style(content_elem, {"display": "oeb-page-foot"})
            elif position == "$151":
                self.add_style(content_elem, {"display": "oeb-page-head"})
            elif position == "$324":
                self.add_style(content_elem, {"position": "fixed"})
            else:
                self.log.warning("%s has unknown position: %s" % (self.content_context, position))

        if "$615" in content:
            classification = content.pop("$615")

            if classification in {"$618", "$619", "$281"}:

                if self.generate_epub3 and content_elem.tag == "div":
                    content_elem.tag = "aside"
                    self.add_style(content_elem, {"-kfx-attrib-epub-type": CLASSIFICATION_EPUB_TYPE[classification]})
            elif classification == "$688":
                content_elem.set("role", "math")
            elif classification == "$689":
                pass
            elif classification == "$453":

                if content_elem.tag == "div" and parent.tag == "table":
                    content_elem.tag = "caption"
            else:
                self.log.warning("%s content has classification: %s" % (self.content_context, classification))

        location_id = self.get_location_id(content)
        if location_id:
            self.process_position(location_id, 0, content_elem)

            if location_id in self.position_anchors:
                for anchor_offset in sorted(self.position_anchors[location_id].keys()):
                    elem = self.locate_offset(content_elem, anchor_offset, split_after=False, zero_len=True)
                    if elem is not None:
                        self.process_position(location_id, anchor_offset, elem)

        content_style = self.get_style(content_elem, remove=True)
        content_style.update(self.process_content_properties(content), replace=True) # content styles override named styles (KC published 5/2017)

        style_events = list(content.pop("$142", []))

        dropcap_style = content_style.partition(property_names=["-kfx-dropcap-chars", "-kfx-dropcap-lines"])
        if dropcap_style:

            dropcap_chars = int(dropcap_style.get("-kfx-dropcap-chars", 1))
            dropcap_lines = int(dropcap_style.get("-kfx-dropcap-lines", 1))

            if dropcap_chars and dropcap_lines:

                dc_style = self.Style({"float": "left", "font-size": "%dem" % dropcap_lines, "line-height": "100%",
                            "margin-top": "0", "margin-right": "0.1em", "margin-bottom": "0"})

                dropcap_style_name = style_name + "-kfx-dropcap"
                if (dropcap_style_name in self.style_definitions) and (self.style_definitions[dropcap_style_name] != dc_style):
                    dropcap_style_name = make_unique_name(style_name + "-kfx-dropcap", self.style_definitions)

                self.style_definitions[dropcap_style_name] = dc_style

                style_events.append({"$143": 0, "$144": dropcap_chars, "$157": dropcap_style_name})

        if style_events:
            if content_type not in ["$269", "$277"]:
                self.log.warning("unexpected style events in %s" % content_type)

        for style_event in style_events:
            event_offset = style_event.pop("$143")
            event_length = style_event.pop("$144")

            if event_length <= 0:
                raise Exception("%s style_event has length: %s" % (self.content_context, event_length))

            first = self.locate_offset(content_elem, event_offset, split_after=False)
            last = self.locate_offset(content_elem, event_offset + event_length - 1, split_after=True)

            if ((first is last) and ("$157" in style_event) and ("class" not in first.attrib) and
                    ("style" not in first.attrib) and ("$179" not in style_event) and
                    ("$616" not in style_event)):
                self.set_kfx_class(first, unicode(self.get_structure_name(style_event, "$157")))

            else:

                event_elem = lxml.html.Element("a" if "$179" in style_event else "span")

                if "$157" in style_event:
                    self.set_kfx_class(event_elem, unicode(self.get_structure_name(style_event, "$157")))

                if "$179" in style_event:
                    self.set_attrib(event_elem, "href-anchor", self.get_structure_name(style_event, "$179"))

                if "$604" in style_event:
                    model = style_event.pop("$604")

                    if model != "$606":
                        self.log.warning("%s has style_event model=%s" % (self.content_context, model))

                self.add_style(event_elem, self.process_content_properties(style_event), replace=True)

                if first.getparent() != last.getparent():
                    raise Exception("%s style_event first and last have different parents" % self.content_context)

                se_parent = first.getparent()
                first_index = se_parent.index(first)

                for i in range(first_index, se_parent.index(last) + 1):
                    e = se_parent[first_index]
                    se_parent.remove(e)
                    event_elem.append(e)

                se_parent.insert(first_index, event_elem)

                self.check_empty(style_event, "%s style_event" % self.content_context)

        if content.pop("$478", False):

            fit_width = add_container = True

            if "width" not in content_style:

                for e in content_elem.iter("*"):
                    nested_style = self.get_style(e)
                    if "width" in nested_style:
                        content_style["width"] = nested_style.pop("width")

                        floated = "float" in content_style

                        if e.tag == "img" and not floated:
                            nested_style["width"] = "100%"

                        self.set_style(e, nested_style)
                        break

        if "float" in content_style and fit_width and content_style.get("display", "") == "inline-block":

            fit_width = add_container = False
            content_style.pop("display", None)

        self.check_empty(content, "%s content type %s" % (self.content_context, content_type))

        if add_container:
            container_elem = lxml.html.Element("div")
            container_elem.append(content_elem)

            container_style = content_style.partition(property_names=[
                    "-kfx-box-align", "-kfx-attrib-valign", "-kfx-vertical-align",
                    "box-sizing", "display", "float",
                    "margin-left", "margin-right",  "margin-top", "margin-bottom", "overflow",
                    "text-align"])

            if content_elem.tag == "div":
                for e in content_elem.iter("*"):
                    if e.tag == "table":
                        break
                else:
                    content_style["display"] = "inline-block"

            if self.KFX_STYLE_NAME in content_style:
                container_style[self.KFX_STYLE_NAME] = content_style[self.KFX_STYLE_NAME]

            if "-kfx-box-align" in container_style:
                container_style["text-align"] = container_style.pop("-kfx-box-align")

            if "-kfx-vertical-align" in container_style:
                container_style["vertical-align"] = container_style.pop("-kfx-vertical-align")

            self.set_style(container_elem, container_style)

        else:

            if "-kfx-min-aspect-ratio" in content_style:
                min_aspect_ratio = content_style.pop("-kfx-min-aspect-ratio")
                if self.min_aspect_ratio is None or min_aspect_ratio < self.min_aspect_ratio:
                    self.min_aspect_ratio = min_aspect_ratio

            if "-kfx-max-aspect-ratio" in content_style:
                max_aspect_ratio = content_style.pop("-kfx-max-aspect-ratio")
                if self.max_aspect_ratio is None or max_aspect_ratio > self.max_aspect_ratio:
                    self.max_aspect_ratio = max_aspect_ratio

            if "-kfx-vertical-align" in content_style:
                vertical_align = content_style.pop("-kfx-vertical-align")
                if ("vertical-align" in content_style) and content_style["vertical-align"] != vertical_align:
                    self.log.error("Conflicting %s -kfx-vertical-align and vertical-align in same style: %s" % (
                                            content_elem.tag, unicode(content_style)))

                content_style["vertical-align"] = vertical_align

            if "-kfx-box-align" in content_style:
                if content_elem.tag not in ["aside", "div", "img", "hr", "table"]:

                    self.log.error("Unexpected box-align found in %s element: %s" % (content_elem.tag, unicode(content_style)))

                box_align = content_style.pop("-kfx-box-align")
                if box_align in ["left", "center", "right"]:
                    align_conflict = False
                    margin_left = content_style.get("margin-left")
                    margin_right = content_style.get("margin-right")

                    if box_align == "left":
                        if margin_left is None:
                            content_style["margin-left"] = "0"
                        elif margin_left == "auto":
                            align_conflict = True

                        if margin_right is None:
                            content_style["margin-right"] = "auto"
                        elif margin_right != "auto":
                            align_conflict = True

                    elif box_align == "right":
                        if margin_left is None:
                            content_style["margin-left"] = "auto"
                        elif margin_left != "auto":
                            align_conflict = True

                        if margin_right is None:
                            content_style["margin-right"] = "0"
                        elif margin_right == "auto":
                            align_conflict = True

                    else:
                        if margin_left is None:
                            content_style["margin-left"] = "auto"
                        elif margin_left != margin_right:
                            align_conflict = True

                        if margin_right is None:
                            content_style["margin-right"] = "auto"
                        elif margin_right != margin_left:
                            align_conflict = True

                    if align_conflict:

                        if "text-align" not in content_style:
                            content_style["text-align"] = box_align
                        elif content_style["text-align"] == box_align:
                            pass
                        else:
                            self.log.error("conflicting %s box-align and margin-left/margin-right/text-align in same style: %s" % (
                                            content_elem.tag, unicode(content_style)))

                    if ("width" not in content_style and
                            (content_style.get("margin-left") == "auto" or content_style.get("margin-right") == "auto")):

                        if content_elem.tag in ["aside", "div"]:
                            if content_style.get("text-align") != box_align:
                                content_style["width"] = "intrinsic"

                        elif content_elem.tag != "table":
                            self.log.error("box-align of %s is missing width: %s" % (content_elem.tag, unicode(content_style)))

                else:
                    self.log.error("Unexpected box-align value: %s" % box_align)

        self.set_style(content_elem, content_style)

        if discard:
            return False

        if add_container:
            content_elem = container_elem

        if top_level:

            if content_elem.tag not in ["aside", "div"]:
                self.log.error("Top level element in html file for %s is '%s'" % (self.content_context, content_elem.tag))
                container_elem = lxml.html.Element(content_elem.tag)
                container_elem.append(content_elem)
                content_elem = container_elem

            content_elem.tag = "body"

        parent.append(content_elem)
        return True

    def process_list(self, content_elem, content, is_listitem):
        list_style = content.pop("$100", None)

        if list_style is None:
            if not is_listitem:
                self.log.error("%s list is missing list_style" % self.content_context)
                list_type = "ul"
        else:
            if list_style in LIST_STYLES:
                list_type, style_type = LIST_STYLES[list_style]

                if style_type is not None:
                    self.add_style(content_elem, {"list-style-type": style_type})
            else:
                self.log.error("Unknown list_style: %s" % list_style)
                list_type = "ul"

        content_elem.tag = "li" if is_listitem else list_type

        if "$503" in content:
            image_style = self.convert_yj_properties(content.pop("$503"))
            self.add_style(content_elem, {"list-style-image": image_style["-kfx-resource-name"]})

        if "$551" in content:
            list_style_position = content.pop("$551")
            if list_style_position in LIST_STYLE_POSITIONS:
                self.add_style(content_elem, {"list-style-position": LIST_STYLE_POSITIONS[list_style_position]})
            else:
                self.log.error("%s list has list_style_position: %s" % (self.content_context, list_style_position))

        if "$104" in content:
            content_elem.set("value" if is_listitem else "start", unicode(content.pop("$104")))

    def process_content_properties(self, content):
        content_properties = {}
        for property_name in content.keys():
            if property_name in YJ_PROPERTY_NAMES:
                content_properties[property_name] = content.pop(property_name)

        return self.convert_yj_properties(content_properties)

    def content_text(self, content):
        t = ion_type(content)
        if t is IonString:
            return content

        if t is IonStruct:

            content_name = content.pop("$4")
            content_index = content.pop("$403")
            self.check_empty(content, "content")

            if "$145" not in self.book_data or content_name not in self.book_data["$145"]:
                self.log.error("Missing book content: %s" % content_name)
                return ""

            return self.book_data["$145"][content_name]["$146"][content_index]

        raise Exception("Unexpected content type: %s" % type_name(content))

    def combined_text(self, elem):

        if elem.tag in {"img", "svg", "math"}:
            return " "

        texts = []

        if elem.text:
            texts.append(elem.text)

        for e in elem.findall("*"):
            texts.append(self.combined_text(e))

        if elem.tail:
            texts.append(elem.tail)

        return "".join(texts)

    def locate_offset(self, root, offset_query, split_after=False, zero_len=False):
        if self.DEBUG: self.log.debug("locating offset %d in %s" % (offset_query, etree.tostring(root)))

        result = self.locate_offset_in(root, offset_query, split_after, zero_len)

        if not isinstance(result, int):
            return result

        if result == 0 and not split_after:
            return self.SubElement(root, "span")

        self.log.error("locate_offset failed to find offset %d (remaining=%d, split_after=%s) in %s" % (
                            offset_query, result, unicode(split_after), etree.tostring(root)))

        return root

    def locate_offset_in(self, elem, offset_query, split_after, zero_len):

        if offset_query < 0:
            return offset_query

        if elem.tail:
            self.log.error("locate_offset found tail in %s element" % elem.tag)

        if elem.tag == "span":
            text_len = len(elem.text or "")

            if text_len > 0:

                if not split_after:
                    if offset_query == 0:
                        return elem

                    elif offset_query < text_len:

                        new_span = self.split_span(elem, offset_query)

                        if zero_len:
                            self.split_span(new_span, 0)

                        return new_span
                else:
                    if offset_query == text_len - 1:
                        return elem

                    elif offset_query < text_len:

                        self.split_span(elem, offset_query + 1)
                        return elem

                offset_query -= text_len

            scan_children = True

        else:
            if elem.text:
                self.log.error("locate_offset found text in %s element" % elem.tag)

            if elem.tag in {"img", "svg", "math"}:
                if offset_query == 0:
                        return elem

                offset_query -= 1
                scan_children = False

            elif elem.tag in {"a", "aside", "div", "li"}:
                scan_children = True

            else:
                self.log.error("locate_offset found unexpected element %s" % elem.tag)
                scan_children = False

        if scan_children:
            for e in elem.findall("*"):
                result = self.locate_offset_in(e, offset_query, split_after, zero_len)

                if not isinstance(result, int):
                    return result

                offset_query = result

        return offset_query

    def split_span(self, old_span, first_text_len):

        new_span = lxml.html.Element("span")
        text = old_span.text or ""

        old_span.text = text[:first_text_len] or None
        new_span.text = text[first_text_len:] or None

        parent = old_span.getparent()
        parent.insert(parent.index(old_span) + 1, new_span)

        return new_span

    def new_book_part(self, filename=None, opf_properties=set(), linear=True, omit=False):
        if filename is None:
            part_index = self.next_part_index
            filename = self.TEXT_FILEPATH % part_index
            self.next_part_index += 1
        else:
            part_index = None

        html = lxml.html.Element("html")
        head = self.SubElement(html, "head")

        title = self.SubElement(head, "title")
        title.text = filename.replace("/", "").replace(".xhtml", "")

        book_part = BookPart(filename, part_index, html, head, opf_properties, linear, omit)
        self.book_parts.append(book_part)

        return book_part

    def link_css_file(self, book_part, css_file, css_type="text/css"):
        self.css_files.add(css_file)
        link = self.SubElement(book_part.head, "link")
        link.set("rel", "stylesheet")
        link.set("type", css_type)
        link.set("href", urllib.quote(urlrelpath(css_file, ref_from=book_part.filename)))

    def reset_preformat(self):
        self.ps_first_in_block = True
        self.ps_previous_char = ""
        self.ps_previous_replaced = False
        self.ps_prior_is_tail = False
        self.ps_prior_elem = None

    def preformat_spaces(self, elem):
        if (elem.tag in {"a", "b", "bdi", "bdo", "em", "i", "image", "path", "span", "strong", "sub", "sup", "u",
                        "idx:orth", "idx:infl", "idx:iform"} or
                    elem.tag.startswith("{http://www.w3.org/1998/Math/MathML}")):
            pass

        elif elem.tag in {"img", "object", "svg", "video"}:

            self.ps_first_in_block = False
            self.ps_previous_char = "?"
            self.ps_previous_replaced = False
            self.ps_prior_elem = None

        else:
            if elem.tag not in {"body", "nav", "aside", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li",
                        "table", "tbody", "thead", "tr", "td", "caption", "br", "colgroup", "col", "hr", "idx:entry",
                        "text", "title", "desc"}:
                self.log.warning("Unexpected block start tag in preformat_spaces: %s" % elem.tag)

            self.reset_preformat()

        self.preformat_text(elem)

        for child in elem:
            self.preformat_spaces(child)

        self.preformat_text(elem, do_tail=True)

    def preformat_text(self, elem, do_tail=False):
        text = elem.tail if do_tail else elem.text

        if not text:
            return

        for i,ch in enumerate(text):

            did_replace = False

            if ch == " " and (self.ps_first_in_block or self.ps_previous_char == " "):
                if self.ps_previous_char == " " and not self.ps_previous_replaced:
                    if i > 0:
                        text = text[:i-1] + NBSP + text[i:]

                    else:

                        if self.ps_prior_is_tail:
                            self.ps_prior_elem.tail = self.ps_prior_elem.tail[:-1] + NBSP
                        else:
                            self.ps_prior_elem.text = self.ps_prior_elem.text[:-1] + NBSP

                text = text[:i] + NBSP + text[i+1:]
                did_replace = True

            self.ps_first_in_block = False
            self.ps_previous_char = ch
            self.ps_previous_replaced = did_replace

        if do_tail:
            elem.tail = text
        else:
            elem.text = text

        self.ps_prior_is_tail = do_tail
        self.ps_prior_elem = elem

    def replace_eol_with_br(self, body, eol):
        changed = True
        while changed:
            changed = False
            for e in body.findall(".//*"):
                if e.text and (eol in e.text):
                    e.text,x,post = e.text.partition(eol)
                    br = self.SubElement(e, "br", first=True)
                    if post: br.tail = post
                    changed = True

                if e.tail and (eol in e.tail):
                    e.tail,x,post = e.tail.partition(eol)
                    br = lxml.html.Element("br")
                    parent = e.getparent()
                    parent.insert(parent.index(e) + 1, br)
                    if post: br.tail = post
                    changed = True

    def compare_fixed_layout_viewports(self):
        if not self.fixed_layout:
            return

        viewport_count = collections.defaultdict(int)
        for book_part in self.book_parts:

            if book_part.viewport_width and book_part.viewport_height and not book_part.is_cover:
                viewport_count[(book_part.viewport_width, book_part.viewport_height)] += 1

        if len(viewport_count) == 0:
            self.log.error("No viewports found for fixed layout book")
        else:
            viewports_by_count = sorted(viewport_count.items(), key=lambda x: -x[1])
            self.original_width, self.original_height = viewports_by_count[0][0]

            if len(viewports_by_count) > 1 and REPORT_CONFLICTING_VIEWPORTS:
                self.log.warning("Conflicting viewport sizes: %s" %
                        (", ".join(["%dw x %dh (%d)" % (fw, fh, ct) for (fw, fh), ct in viewports_by_count])))

            viewports_by_size = sorted(viewport_count.items(), key=lambda x: -(x[0][0] + x[0][1]))
            best_width, best_height = viewports_by_size[0][0]
            if self.original_width != best_width or self.original_height != best_height:
                self.log.error("Best/largest viewport is not the most common: %s" %
                        (", ".join(["%dw x %dh (%d)" % (fw, fh, ct) for (fw, fh), ct in viewports_by_size])))

    def save_book_parts(self):
        for book_part in self.book_parts:
            head = book_part.html.find("head")
            body = book_part.html.find("body")

            self.replace_eol_with_br(body, "\n")
            self.replace_eol_with_br(body, "\r")

            self.reset_preformat()
            self.preformat_spaces(body)

            for toptag in body.findall("*"):
                changed = True
                while changed:
                    changed = False
                    for e in toptag.iterdescendants():
                        if e.tag in {"a", "b", "em", "i", "span", "strong", "sub", "sup", "u"}:
                            n = e.getnext()
                            while ((not e.tail) and (n is not None) and n.tag == e.tag and
                                    tuple(sorted(dict(e.attrib).items())) == tuple(sorted(dict(n.attrib).items()))):

                                if n.text:

                                    if len(e) > 0:
                                        tt = e[-1]
                                        tt.tail = (tt.tail + n.text) if tt.tail else n.text
                                    else:
                                        e.text = (e.text + n.text) if e.text else n.text

                                    n.text = ""

                                while len(n) > 0:
                                    c = n[0]
                                    n.remove(c)
                                    e.append(c)

                                if n.tail:
                                    e.tail = n.tail

                                n.getparent().remove(n)

                                changed = True

                                n = e.getnext()

                            if changed:
                                break

            for e in body.iter("span"):
                if e.tag == "span" and len(e.attrib) == 0:
                    e.tag = TEMP_TAG

            etree.strip_tags(body, TEMP_TAG)

            for e in body.iter("div"):
                if e.tag == "div" and len(e.attrib) == 0 and not e.text:
                    parent = e.getparent()

                    if (len(parent) == 1) and not parent.text:

                        real_parent = parent
                        while real_parent.tag == TEMP_TAG: real_parent = real_parent.getparent()

                        if real_parent.tag in {"aside", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "caption", "idx:entry"}:
                            e.tag = TEMP_TAG
                        elif real_parent.tag == "body":

                            for child in e.findall("*"):
                                if (child.tag not in {"aside", "div", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "ol", "table", "ul", "idx:entry"} or
                                        child.tail):
                                    break
                            else:
                                e.tag = TEMP_TAG

                    if (len(e) == 1) and (e[0].tag in {"div", TEMP_TAG}):
                        e.tag = TEMP_TAG

            etree.strip_tags(body, TEMP_TAG)

            for e in [book_part.html] + book_part.html.findall("*") + head.findall("*") + body.findall("*"):
                if e.tag in {"html", "head", "body"} and not e.text:
                    e.text = "\n"

                if e.tag in {"head", "title", "link", "meta", "style", "body", "aside", "div", "hr", "table", "ul", "ol", "idx:entry"} and not e.tail:
                    e.tail = "\n"

                if e.tag == "div" and e.get("id", "").startswith("amzn_master_range_"):

                    for ee in e.findall("*"):
                        if ee.tag in {"aside", "div", "hr", "table", "ul", "ol", "idx:entry"} and not ee.tail:
                            ee.tail = "\n"

            book_part.html.set("xmlns", "http://www.w3.org/1999/xhtml")

            epub_prefix = amzn_prefix = idx_prefix = mbp_prefix = False

            if self.generate_epub3:
                if body.find(".//svg") is not None:
                    book_part.opf_properties.add("svg")

                if body.find(".//{*}math") is not None:
                    book_part.opf_properties.add("mathml")

            for e in body.findall(".//*"):
                if e.tag.startswith("idx:"):
                    idx_prefix = True
                elif e.tag.startswith("mbp:"):
                    mbp_prefix = True

                for a in e.attrib:
                    if a.startswith("epub:"):
                        epub_prefix = True

                if e.get("epub:type", "").startswith("amzn:"):
                    amzn_prefix = True

            if epub_prefix:
                book_part.html.set("xmlns:epub", "http://www.idpf.org/2007/ops")

            if mbp_prefix:
                book_part.html.set("xmlns:mbp", "https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf")

            if idx_prefix:
                book_part.html.set("xmlns:idx", "https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf")

            if self.language:
                book_part.html.set("xml:lang", self.language)

            if amzn_prefix:
                book_part.html.set("epub:prefix",
                    "amzn: https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf")

            if self.fixed_layout and book_part.linear and book_part.is_cover:
                book_part.linear = False

            if len(body) > 0 and not book_part.omit:
                document = etree.ElementTree(book_part.html)

                doctype = b"<!DOCTYPE html>"
                html_str = etree.tostring(document, encoding="utf-8", doctype=doctype, xml_declaration=True).replace(doctype + b"\n", b"")
                self.oebps_files[book_part.filename] = OutputFile(html_str, "application/xhtml+xml")
                self.manifest.append(ManifestEntry(book_part.filename, book_part.opf_properties, book_part.linear))

    def set_kfx_class(self, elem, class_name):
        if class_name:
            new_class_name = self.non_generic_class_name(class_name)
            if new_class_name:
                if self.DEBUG: self.log.debug("Using class name from book: %s" % new_class_name)
                self.add_style(elem, {self.KFX_STYLE_NAME: fix_html_class(new_class_name)})

            if class_name in self.style_definitions:
                self.add_style(elem, self.style_definitions[class_name])

            elif class_name not in self.missing_styles:
                self.log.error("No definition found for style: %s" % class_name)
                if self.DEBUG: self.log.debug("styles: %s" % list_keys(self.style_definitions))
                self.missing_styles.add(class_name)

def fix_html_class(id):
    if len(id) == 0: id = "class"

    id = re.sub(r"[^A-Za-z0-9_\.\-]", "_", id)

    if not re.match(r"^[A-Za-z]", id):
        id = "class-" + id

    return id

