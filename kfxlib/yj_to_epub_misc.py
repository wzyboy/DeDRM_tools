from __future__ import (unicode_literals, division, absolute_import, print_function)

from lxml import etree
import operator
import re

from .ion import (
            ion_type, IonSExp, IonStruct, IonSymbol)
from .misc import (get_url_filename, urlabspath)
from .yj_to_epub_properties import value_str

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

DEVICE_SCREEN_NARROW_PX = 600
DEVICE_SCREEN_WIDE_PX = 1024

class EPUBMisc(object):

    def set_condition_operators(self):
        if self.orientation_lock == "landscape":
            screen_width = DEVICE_SCREEN_WIDE_PX
            screen_height = DEVICE_SCREEN_NARROW_PX
        else:
            screen_width = DEVICE_SCREEN_NARROW_PX
            screen_height = DEVICE_SCREEN_WIDE_PX

        self.condition_operators = {
            "$305": (0, screen_height),
            "$304": (0, screen_width),

            "$300": (0, True),
            "$301": (0, True),
            "$183": (0, 0),
            "$302": (0, screen_width),
            "$303": (0, screen_height),
            "$525": (0, (screen_width > screen_height)),
            "$526": (0, (screen_width < screen_height)),

            "$660": (0, True),

            "$293": (1, operator.not_),
            "$266": (1, None),
            "$659": (1, None),

            "$292": (2, operator.and_),
            "$291": (2, operator.or_),
            "$294": (2, operator.eq),
            "$295": (2, operator.ne),
            "$296": (2, operator.gt),
            "$297": (2, operator.ge),
            "$298": (2, operator.lt),
            "$299": (2, operator.le),
            "$516": (2, operator.add),
            "$517": (2, operator.sub),
            "$518": (2, operator.mul),
            "$519": (2, operator.truediv),
            }

    def evaluate_binary_condition(self, condition):
        value = self.evaluate_condition(condition)
        if value not in {True, False}:
            self.log.error("Condition has non-binary result (%s): %s" % (unicode(value), unicode(condition)))
            return False

        return value

    def evaluate_condition(self, condition):
        if ion_type(condition) is IonSExp:
            op = condition[0]
            num = len(condition) - 1
        else:
            op = condition
            num = 0

        if (ion_type(op) is not IonSymbol) or (op not in self.condition_operators):
            self.log.error("Condition operator is unknown: %s" % unicode(condition))
            return False

        nargs, func = self.condition_operators[op]

        if nargs != num:
            self.log.error("Condition operator has wrong number of arguments: %s" % unicode(condition))
            return False

        if nargs == 0:
            return func

        if nargs == 1:
            if op == "$266":
                return 0

            if op == "$659":

                if condition[1] == "$660":
                    return True

                self.log.error("yj.supports feature unknown: %s" % condition[1])
                return False

            return func(self.evaluate_condition(condition[1]))

        return func(self.evaluate_condition(condition[1]), self.evaluate_condition(condition[2]))

    def convert_to_svg(self, content_elem, layout, book_part):
        if (content_elem.tag == "div" and len(content_elem) == 1 and content_elem[0].tag == "div" and
                len(content_elem[0]) == 1 and content_elem[0][0].tag == "img"):
            old_div = content_elem[0]
            div_style = self.get_style(old_div)

            img = old_div[0]
            img_style = self.get_style(img)
            img_filename = get_url_filename(urlabspath(img.get("src"), ref_from=book_part.filename))
            img_height = self.oebps_files[img_filename].height
            img_width = self.oebps_files[img_filename].width
            iheight = img_style.pop("height", "")
            iwidth = img_style.pop("width", "")

            if (img_style.pop("top", "") == "0" and img_style.pop("left", "") == "0" and
                    img_style.pop("text-indent", "0") == "0" and
                    (iheight == "" or iheight == unicode(img_height)) and
                    (re.match(r"^(100|99.*)%$", iwidth) or iwidth == unicode(img_width)) and
                    div_style.pop("text-align", "") == "center" and
                    len(img_style) == 0 and len(div_style) == 0):

                self.log.info("Rendering %s layout container with image as SVG" % layout)

                content_elem.remove(old_div)

                content_elem.tag = "svg"
                content_elem.set("xmlns", "http://www.w3.org/2000/svg")
                content_elem.set("xmlns:xlink", "http://www.w3.org/1999/xlink")
                content_elem.set("version", "1.1")
                content_elem.set("preserveAspectRatio", "xMidYMid meet")
                content_elem.set("viewBox", "0 0 %d %d" % (img_width, img_height))

                image = self.SubElement(content_elem, "image")
                image.set("xlink:href", img.get("src"))
                image.set("height", "%d" % img_height)
                image.set("width", "%d" % img_width)

            else:
                self.log_unsupported("%s layout div/image have incorrect styles for SVG rendering, div style: '%s', image style: '%s'" %
                        (layout, unicode(div_style), unicode(img_style)))

        else:
            self.log_unsupported("%s layout has incorrect content for SVG rendering, content_elem=%s" % (
                        layout, etree.tostring(content_elem)))

    def process_kvg_shape(self, parent, shape, content_list, book_part):
        shape_type = shape.pop("$159")
        if shape_type == "$273":
            elem = self.SubElement(parent, "path")
            elem.set("d", self.process_path(shape.pop("$249")))

        elif shape_type == "$270":
            source = shape.pop("$474")

            for i,content in enumerate(content_list):
                if content["$155"] == source:
                    break
            else:
                self.log.error("Missing KVG container content ID: %s" % source)
                return

            content_list.pop(i)
            self.process_content(content, parent, book_part)
            elem = parent[-1]

            if elem.tag != "div":
                self.log.error("Unexpected non-text content in KVG container: %s" % elem.tag)
                return

            elem.tag = "text"

        else:
            self.log.error("Unexpected shape type: %s" % shape_type)
            return

        if "$98" in shape:
            elem.set("transform", self.property_value("$98", shape.pop("$98"), svg=True))

        if "$70" in shape:
            elem.set("stroke", self.property_value("$498", shape.pop("$70"), svg=True))

        if "$76" in shape:
            elem.set("stroke-width", self.property_value("$76", shape.pop("$76"), svg=True))

        self.check_empty(shape, "shape")

    def process_path(self, path):
        if ion_type(path) is IonStruct:

            path_bundle_name = path.pop("$4")
            path_index = path.pop("$403")
            self.check_empty(path, "path")

            if "$692" not in self.book_data or path_bundle_name not in self.book_data["$692"]:
                self.log.error("Missing book path_bundle: %s" % path_bundle_name)
                return ""

            return self.process_path(self.book_data["$692"][path_bundle_name]["$693"][path_index])

        p = list(path)
        d = []

        def process_instruction(inst, n_args):
            d.append(inst)

            for j in range(n_args):
                if len(p) == 0:
                    self.log.error("Incomplete path instruction in %s" % unicode(path))
                    return

                d.append(value_str(p.pop(0)))

        while len(p) > 0:
            inst = p.pop(0)
            if inst == 0:
                process_instruction("M", 2)

            elif inst == 1:
                process_instruction("L", 2)

            elif inst == 2:
                process_instruction("Q", 4)

            elif inst == 3:
                process_instruction("C", 4)

            elif inst == 4:
                process_instruction("Z", 0)

            else:
                self.log.error("Unexpected path instruction %s in %s" % (unicode(inst), unicode(path)))
                break

        return " ".join(d)

    def process_polygon(self, path):
        d = []

        i = 0
        l = len(path)
        while i < l:
            inst = path[i]
            if inst == 0 or inst == 1:
                if i + 3 > l:
                    self.log.error("Bad path instruction in %s" % unicode(path))
                    break

                d.append("%s%% %s%%" % (value_str(path[i+1] * 100), value_str(path[i+2] * 100)))
                i += 3

            elif inst == 4:
                i += 1

            else:
                self.log.error("Unexpected path instruction %s in %s" % (unicode(inst), unicode(path)))
                break

        return "polygon(%s)" % (", ".join(d))

    def process_transform(self, vals):
        if len(vals) == 6:

            if vals[0:4] == [1., 0., 0., 1.]:
                return "translate(%s, %s)" % (value_str(vals[4], ""), value_str(vals[5], ""))

            if vals[1:3] == [0., 0.] and vals[4:6] == [0., 0.]:
                return "scale(%s, %s)" % (value_str(vals[0], ""), value_str(vals[3], ""))

            return "matrix(%s)" % (", ".join([value_str(v, "") for v in vals]))

        self.log.error("Unexpected transform: %s" % unicode(vals))
        return "?"

