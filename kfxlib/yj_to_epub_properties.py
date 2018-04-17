from __future__ import (unicode_literals, division, absolute_import, print_function)

import collections
import decimal
import lxml
import re
import urllib

from .ion import (ion_type, IonBool, IonDecimal, IonFloat, IonInt, IonList, IonString, IonStruct, IonSymbol, isunicode)
from .misc import (get_url_filename, list_symbols, make_unique_name, natural_sort_key, type_name, urlabspath, urlrelpath)
from .yj_to_epub_resources import (ManifestEntry, OutputFile)

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

STYLE_TEST = False

FIX_MINIMUM_BORDER_WEIGHT = True

FIX_NONSTANDARD_FONT_WEIGHT = False

SUPER_SUB_MULT_FACTOR = decimal.Decimal("2.0")

LINE_HEIGHT_SCALE_FACTOR = decimal.Decimal("1.2")
USE_NORMAL_LINE_HEIGHT = True

MINIMUM_LINE_HEIGHT = decimal.Decimal("1.0")

CVT_DIRECTION_PROPERTY_TO_MARKUP = False

class Prop(object):

    def __init__(self, name, values=None):
        self.name = name
        self.values = values

COLLISIONS = {
    "$352": "always",
    "$652": "queue",
    }

BORDER_STYLES = {
    "$349": "none",
    "$328": "solid",
    "$331": "dotted",
    "$330": "dashed",
    "$329": "double",
    "$335": "ridge",
    "$334": "groove",
    "$336": "inset",
    "$337": "outset",
    }

YJ_PROPERTY_INFO = {
    "$479": Prop("background-image"),
    "$480": Prop("-kfx-background-positionx"),
    "$481": Prop("-kfx-background-positiony"),

    "$547": Prop("background-origin", {
        "$378": "border-box",
        "$377": "content-box",
        "$379": "padding-box",
        }),

    "$484": Prop("background-repeat", {
        "$487": "no-repeat",
        "$485": "repeat-x",
        "$486": "repeat-y",
        }),

    "$482": Prop("-kfx-background-sizex"),
    "$483": Prop("-kfx-background-sizey"),

    "$31": Prop("-kfx-baseline-shift"),

    "$44": Prop("vertical-align", {
        "$60": "bottom",
        "$320": "middle",
        "$350": "baseline",
        "$371": "sub",
        "$370": "super",
        "$449": "text-bottom",
        "$447": "text-top",
        "$58": "top",
        }),

    "$682": Prop("direction", {
        "$376": "ltr",
        "$375": "rtl",
        }),

    "$674": Prop("unicode-bidi", {
        "$675": "embed",
        "$676": "isolate",
        "$678": "isolate-override",
        "$350": "normal",
        "$677": "bidi-override",
        "$679": "plaintext",
        }),

    "$83": Prop("border-color"),
    "$86": Prop("border-bottom-color"),
    "$85": Prop("border-left-color"),
    "$87": Prop("border-right-color"),
    "$84": Prop("border-top-color"),

    "$461": Prop("border-bottom-left-radius"),
    "$462": Prop("border-bottom-right-radius"),
    "$459": Prop("border-top-left-radius"),
    "$460": Prop("border-top-right-radius"),

    "$88": Prop("border-style", BORDER_STYLES),
    "$91": Prop("border-bottom-style", BORDER_STYLES),
    "$90": Prop("border-left-style", BORDER_STYLES),
    "$92": Prop("border-right-style", BORDER_STYLES),
    "$89": Prop("border-top-style", BORDER_STYLES),

    "$93": Prop("border-width"),
    "$96": Prop("border-bottom-width"),
    "$95": Prop("border-left-width"),
    "$97": Prop("border-right-width"),
    "$94": Prop("border-top-width"),

    "$60": Prop("bottom"),
    "$580": Prop("-kfx-box-align", {
        "$320": "center",
        "$59": "left",
        "$61": "right",
        }),

    "$133": Prop("page-break-after", {
        "$352": "always",
        "$353": "avoid",
        }),

    "$134": Prop("page-break-before", {
        "$352": "always",
        "$353": "avoid",
        }),

    "$135": Prop("page-break-inside", {
        "$353": "avoid",
        }),

    "$476": Prop("overflow", {
        False: "visible",
        True: "hidden",
        }),

    "$112": Prop("column-count", {
        "$383": "auto",
        }),

    "$116": Prop("column-rule-color"),

    "$192": Prop("direction", {
        "$376": "ltr",
        "$375": "rtl",
        }),

    "$126": Prop("-kfx-dropcap-chars"),
    "$125": Prop("-kfx-dropcap-lines"),

    "$73": Prop("background-clip", {
        "$378": "border-box",
        "$377": "content-box",
        "$379": "padding-box",
        }),

    "$70": Prop("-kfx-fill-color"),
    "$72": Prop("-kfx-fill-opacity"),

    "$140": Prop("float", {
        "$320": "none",
        "$59": "left",
        "$61": "right",
        }),

    "$11": Prop("font-family"),
    "$16": Prop("font-size"),
    "$15": Prop("font-stretch"),

    "$12": Prop("font-style", {
        "$382": "italic",
        "$350": "normal",
        "$381": "oblique",
         }),

    "$13": Prop("font-weight", {
        "$361": "bold",

        "$363": "900",
        "$357": "300",
        "$359": "500",
        "$350": "normal",
        "$360": "600",
        "$355": "100",
        "$362": "800",

        "$356": "200",
        }),

    "$583": Prop("font-variant", {
        "$349": "normal",
        "$369": "small-caps"}),

    "$57": Prop("height"),

    "$458": Prop("empty-cells", {
        False: "show",
        True: "hide",
        }),

    "$127": Prop("-webkit-hyphens", {
        "$383": "auto",
        "$384": "manual",
        "$349": "none",
        }),

    "$10": Prop("-kfx-attrib-xml-lang"),
    "$59": Prop("left"),
    "$32": Prop("letter-spacing"),
    "$42": Prop("line-height"),
    "$577": Prop("-kfx-link-color"),
    "$576": Prop("-kfx-visited-color"),
    "$551": Prop("list-style-position"),

    "$46": Prop("margin"),
    "$49": Prop("margin-bottom"),
    "$48": Prop("margin-left"),
    "$50": Prop("margin-right"),
    "$47": Prop("margin-top"),

    "$64": Prop("max-height"),
    "$65": Prop("max-width"),
    "$62": Prop("min-height"),
    "$63": Prop("min-width"),

    "$45": Prop("white-space", {
        False: "normal",
        True: "nowrap",
        }),

    "$105": Prop("outline-color"),
    "$106": Prop("outline-offset"),
    "$107": Prop("outline-style"),
    "$108": Prop("outline-width"),

    "$554": Prop("text-decoration", {
        "$349": None,
        "$328": "overline",
        }),

    "$51": Prop("padding"),
    "$54": Prop("padding-bottom"),
    "$53": Prop("padding-left"),
    "$55": Prop("padding-right"),
    "$52": Prop("padding-top"),

    "$183": Prop("position", {
        "$324": "absolute",
        "$488": "relative",
        "$489": "fixed",
        }),

    "$175": Prop("-kfx-resource-name"),
    "$61": Prop("right"),

    "$436": Prop("-kfx-attrib-epub-type", {
        "$442": "amzn:kindle-illustrated",
        "$441": None,
        }),

    "$496": Prop("box-shadow"),

    "$546": Prop("box-sizing", {
        "$378": "border-box",
        "$377": "content-box",
        "$379": "padding-box",
        }),

    "src": Prop("src"),

    "$27": Prop("text-decoration", {
        "$349": None,
        "$328": "line-through"}),

    "$75": Prop("-webkit-text-stroke-color"),
    "$76": Prop("-webkit-text-stroke-width"),

    "$150": Prop("border-collapse", {
        False: "separate",
        True: "collapse",
        }),

    "$148": Prop("-kfx-attrib-colspan"),
    "$149": Prop("-kfx-attrib-rowspan"),

    "$34": Prop("text-align", {
        "$320": "center",
        "$321": "justify",
        "$59": "left",
        "$61": "right",
        }),

    "$35": Prop("text-align-last"),
    "$21": Prop("background-color"),
    "$19": Prop("color"),
    "$36": Prop("text-indent"),

    "$41": Prop("text-transform", {
        "$373": "lowercase",
        "$349": "none",
        "$374": "capitalize",
        "$372": "uppercase",
        }),

    "$497": Prop("text-shadow"),
    "$58": Prop("top"),
    "$98": Prop("-webkit-transform"),

    "$23": Prop("text-decoration", {
        "$349": None,
        "$328": "underline",
        }),

    "$24": Prop("text-decoration-color"),

    "$68": Prop("visibility", {
        False: "hidden",
        True: "visible"}),

    "$716": Prop("white-space", {
        "$715": "nowrap",
        }),

    "$56": Prop("width"),

    "$569": Prop("word-break", {
        "$570": "break-all",
        "$350": "normal",
        }),

    "$33": Prop("word-spacing"),

    "$560": Prop("writing-mode", {
        "$557": "horizontal-tb",
        "$559": "vertical-rl",
        "$558": "vertical-lr"}),

    "$650": Prop("-amzn-shape-outside"),

    "$646": Prop("-kfx-collision"),

    "$616": Prop("-kfx-attrib-epub-type", {
        "$617": "noteref"}),

    "$658": Prop("yj-float-align", {
        "$58": None,
        }),

    "$672": Prop("yj-float-bias", {
        "$671": None,
        }),

    "$628": Prop("clear", {
        "$59": "left",
        "$61": "right",
        "$421": "both",
        "$349": "none",
        }),

    "$673": Prop("yj-float-to-block", {
        False: None}),

    "$644": Prop("-amzn-page-footer",{
        "$442": "disable",
        "$441": "overlay",
        }),

    "$643": Prop("-amzn-page-header", {
        "$442": "disable",
        "$441": "overlay",
        }),

    "$645": Prop("-amzn-max-crop-percentage"),

    "$647": Prop("-kfx-min-aspect-ratio"),
    "$648": Prop("-kfx-max-aspect-ratio"),

    "$640": Prop("-kfx-user-margin-bottom-percentage"),
    "$641": Prop("-kfx-user-margin-left-percentage"),
    "$642": Prop("-kfx-user-margin-right-percentage"),
    "$639": Prop("-kfx-user-margin-top-percentage"),

    "$633": Prop("-kfx-vertical-align", {
        "$350": "baseline",
        "$60": "bottom",
        "$320": "middle",
        "$58": "top",
        }),

    "$649": Prop("-kfx-attrib-epub-type", {
        "$442": "amzn:decorative",
        "$441": "amzn:not-decorative",
        }),
    }

YJ_PROPERTY_NAMES = set(YJ_PROPERTY_INFO.keys())

YJ_LENGTH_UNITS = {
    "$506": "ch",
    "$315": "cm",
    "$308": "em",
    "$309": "ex",
    "$317": "in",
    "$310": "lh",
    "$316": "mm",

    "$314": "%",
    "$318": "pt",
    "$319": "px",
    "$505": "rem",
    "$312": "vh",
    "$507": "vmax",
    "$313": "vmin",
    "$311": "vw",
    }

COLOR_NAME = {
    "#000000": "black",
    "#000080": "navy",
    "#0000ff": "blue",
    "#008000": "green",
    "#008080": "teal",
    "#00ff00": "lime",
    "#00ffff": "cyan",
    "#800000": "maroon",
    "#800080": "purple",
    "#808000": "olive",
    "#808080": "gray",
    "#ff0000": "red",
    "#ff00ff": "magenta",
    "#ffff00": "yellow",
    "#ffffff": "white",
    }

COLOR_NAMES = set(COLOR_NAME.values())

GENERIC_FONT_NAMES = {

    "serif", "sans-serif", "cursive", "fantasy", "monospace",

    "Arial", "Caecilia", "Courier", "Georgia", "Lucida", "Times New Roman", "Trebuchet",

    "Amazon Ember", "Amazon Ember Bold", "Baskerville", "Bookerly", "Caecilia",
    "Caecilia Condensed", "Futura", "Helvetica", "Open Dyslexic", "Palatino",

    "Helvetica Light", "Noto Sans",

    "Droid Sans", "Droid Serif", "Verdana",

    "Book Antiqua", "Calibri", "Calibri Light", "Cambria", "Comic Sans MS", "Courier New", "Lucida Sans Unicode",
    "Palatino Linotype", "Tahoma", "Trebuchet MS",

    "Palatino LT Std",
    }

DEFAULT_FONT_NAMES = {"default", "$amzn_fixup_default_font$"}

MISSPELLED_FONT_NAMES = {
    "san-serif": "sans-serif",
    "ariel": "Arial",
    }

KNOWN_STYLES = {
    "background-color": {"#0"},
    "background-image": {"*"},
    "background-origin": {"border-box", "content-box"},
    "background-position": {"0 0"},
    "background-size": {"0 0", "auto 0", "0 auto", "contain", "cover"},
    "background-repeat": {"no-repeat", "repeat-x", "repeat-y"},
    "border-bottom-color": {"#0"},
    "border-bottom-left-radius": {"0"},
    "border-bottom-right-radius": {"0"},
    "border-bottom-style": {"dashed", "dotted", "double", "groove", "inset", "outset", "none", "solid"},
    "border-bottom-width": {"0"},
    "border-collapse": {"collapse"},
    "border-color": {"#0"},
    "border-left-color": {"#0"},
    "border-left-style": {"dashed", "dotted", "double", "groove", "inset", "outset", "none", "solid"},
    "border-left-width": {"0"},
    "border-right-color": {"#0"},
    "border-right-style": {"dashed", "dotted", "double", "groove", "inset", "outset", "none", "solid"},
    "border-right-width": {"0"},
    "border-spacing": {"0 0"},
    "border-style": {"dashed", "dotted", "double", "groove", "inset", "none", "outset", "solid"},
    "border-top-color": {"#0"},
    "border-top-left-radius": {"0"},
    "border-top-right-radius": {"0"},
    "border-top-style": {"dashed", "dotted", "double", "groove", "inset", "none", "outset", "solid"},
    "border-top-width": {"0"},
    "border-width": {"0"},
    "bottom": {"0"},
    "box-shadow": {"0 0 0 #0", "0 0 0 #0 inset", "0 0 0 0 #0", "0 0 0 0 #0 inset"},
    "box-sizing": {"border-box", "content-box"},
    "clear": {"both", "left", "none", "right"},
    "color": {"#0"},
    "direction": {"ltr", "rtl"},
    "display": {"block", "inline", "inline-block", "none", "oeb-page-foot", "oeb-page-head"},
    "float": {"left", "right"},
    "font-family": {"*"},
    "font-size": {"0"},
    "font-style": {"italic", "normal", "oblique"},
    "font-variant": {"normal", "small-caps"},
    "font-weight": {"0", "bold", "normal"},
    "height": {"0"},
    "left": {"0"},
    "letter-spacing": {"0"},
    "line-height": {"0", "normal"},
    "list-style-image": {"*"},
    "list-style-position": {"inside", "outside"},
    "list-style-type": {"circle", "decimal", "disc", "lower-alpha", "lower-roman", "none", "square", "upper-alpha", "upper-roman"},
    "margin": {"0"},
    "margin-bottom": {"0"},
    "margin-left": {"0", "auto"},
    "margin-right": {"0", "auto"},
    "margin-top": {"0"},
    "max-width": {"0"},
    "min-height": {"0"},
    "min-width": {"0"},
    "outline-color": {"#0"},
    "outline-offset": {"0"},
    "outline-style": {"dashed", "dotted", "double", "inset", "none", "ridge", "solid"},
    "outline-width": {"0"},
    "overflow": {"hidden"},
    "padding": {"0"},
    "padding-bottom": {"0"},
    "padding-left": {"0"},
    "padding-right": {"0"},
    "padding-top": {"0"},
    "page-break-after": {"always"},
    "position": {"absolute", "fixed", "relative"},
    "right": {"0"},
    "src": {"*"},
    "text-align": {"center", "justify", "left", "right"},

    "text-decoration": {"line-through", "none !important", "overline", "underline", "overline underline"},
    "text-decoration-color": {"#0"},
    "text-indent": {"0"},
    "text-shadow": {"0 0 0 #0", "0 0 #0"},
    "text-transform": {"capitalize", "none", "lowercase", "uppercase"},
    "top": {"0"},
    "unicode-bidi": {"bidi-override", "embed", "isolate", "isolate-override", "normal", "plaintext"},
    "vertical-align": {"0", "baseline", "bottom", "middle", "sub", "super", "text-bottom", "text-top", "top"},
    "visibility": {"hidden"},
    "white-space": {"normal", "nowrap"},
    "width": {"0", "intrinsic"},
    "word-break": {"break-all"},
    "word-spacing": {"0"},

    "-amzn-float": {"bottom", "top", "top,bottom"},
    "-amzn-max-crop-percentage": {"0 0 0 0"},
    "-amzn-page-align": {"all", "bottom", "bottom,left", "bottom,left,right", "bottom,right", "left", "left,right",
            "right", "top", "top,bottom,left", "top,bottom,right", "top,left", "top,left,right", "top,right"},

    "-amzn-page-footer": {"disable"},
    "-amzn-page-header": {"disable"},
    "-amzn-shape-outside": {"*"},
    "-webkit-hyphens": {"auto", "manual", "none"},
    "-webkit-text-stroke-color": {"#0"},
    "-webkit-text-stroke-width": {"0"},
    }

CONFLICTING_PROPERTIES = {
    "background": {"background-color", "background-image", "background-repeat", "background-attachment", "background-position"},
    "border-color": {"border-bottom-color", "border-left-color", "border-right-color", "border-top-color"},
    "border-style": {"border-bottom-style", "border-left-style", "border-right-style", "border-top-style"},
    "border-width": {"border-bottom-width", "border-left-width", "border-right-width", "border-top-width"},
    "font": {"font-family", "font-size", "font-style", "font-variant", "font-weight"},
    "list-style": {"list-style-type", "list-style-position", "list-style-image"},
    "margin": {"margin-bottom", "margin-left", "margin-right", "margin-top"},
    "outline": {"outline-width", "outline-style", "outline-color"},
    "padding": {"padding-bottom", "padding-left", "padding-right", "padding-top"},
    }

for name,conf_set in CONFLICTING_PROPERTIES.items():
    for conf in conf_set:
        if conf not in CONFLICTING_PROPERTIES: CONFLICTING_PROPERTIES[conf] = set()
        CONFLICTING_PROPERTIES[conf].add(name)

HERITABLE_PROPERTIES = {

    "-kfx-user-margin-bottom-percentage", "-kfx-user-margin-left-percentage",
    "-kfx-user-margin-right-percentage", "-kfx-user-margin-top-percentage",
    "-amzn-page-align",

    "azimuth", "border-collapse", "border-spacing", "caption-side", "color", "cursor", "direction", "elevation", "empty-cells",
    "font", "font-family", "font-size", "font-style", "font-variant", "font-weight", "letter-spacing", "line-height", "list-style-image",
    "list-style-position", "list-style-type", "list-style", "orphans", "pitch-range", "pitch", "quotes", "richness", "stress",
    "text-align", "text-indent", "text-transform", "visibility", "white-space", "widows", "word-spacing",

    "hanging-punctuation", "hyphens", "line-break", "overflow-wrap", "tab-size", "text-align-last", "text-combine-upright",
    "text-justify", "word-break", "word-wrap", "text-shadow", "text-underline-position", "font-feature-settings",
    "font-kerning", "font-language-override", "font-size-adjust", "font-stretch", "font-synthesis", "text-orientation",
    "text-combine-upright", "unicode-bidi", "word-break", "writing-mode",

    "-kfx-attrib-xml-lang",
    }

HERITABLE_DEFAULT_PROPERTIES = (
    "-kfx-user-margin-bottom-percentage: 100; -kfx-user-margin-left-percentage: 100; "
    "-kfx-user-margin-right-percentage: 100; -kfx-user-margin-top-percentage: 100; "
    "-amzn-page-align: none; "
    "border-collapse: separate; direction: ltr; "
    "font-family: serif; font-size: 1rem; font-style: normal; font-variant: normal; font-weight: normal; "
    "line-height: normal; list-style-position: outside; list-style-type: disc; "
    "text-align: left; text-align-last: auto; text-transform: none; text-indent: 0; unicode-bidi: normal; "
    "visibility: visible; writing-mode: horizontal-tb; "
    )

NON_HERITABLE_DEFAULT_PROPERTIES = (
    "background-origin: padding-box; box-sizing: content-box; "
    "margin-bottom: 0; margin-left: 0; margin-right:0; margin-top: 0; "
    "padding-bottom: 0; padding-left: 0; padding-right:0; padding-top: 0; "
    "position: static; float: none; column-count: auto; text-decoration: none; "
    )

RESET_CSS_DATA = (
    "html {color: #000; background: #FFF;}\n" +

    "body,div,dl,dt,dd,ul,ol,li,h1,h2,h3,h4,h5,h6,th,td {margin: 0; padding: 0;}\n" +
    "table {border-collapse: collapse; border-spacing: 0;}\n" +
    "fieldset,img {border: 0;}\n" +
    "caption,th,var {font-style: normal; font-weight: normal;}\n" +
    "li {list-style: none;}\n" +
    "caption,th {text-align: left;}\n" +
    "h1,h2,h3,h4,h5,h6 {font-size: 100%; font-weight: normal;}\n" +
    "sup {vertical-align: text-top;}\n" +
    "sub {vertical-align: text-bottom;}\n" +

    "a.app-amzn-magnify {display: block; width: 100%; height: 100%;}\n")

AMAZON_SPECIAL_CLASSES = {
    "app-amzn-magnify",
    }

style_cache = {}

class EPUBProperties(object):

    def Style(self, x):
        return Style(x, self.log)

    def process_styles(self):

        styles = self.book_data.pop("$157", {})

        for style_name, yj_properties in styles.items():
            self.check_fragment_name(yj_properties, "$157", style_name)
            self.style_definitions[unicode(style_name)] = self.convert_yj_properties(yj_properties, style_name)

    def convert_yj_properties(self, yj_properties, style_name=""):
        declarations = {}

        for yj_property_name, yj_value in yj_properties.items():
            value = self.property_value(yj_property_name, yj_value, style_name)

            if yj_property_name in YJ_PROPERTY_INFO:
                property = YJ_PROPERTY_INFO[yj_property_name].name
            else:
                self.log.warning("unknown property name in style %s: %s" % (style_name, yj_property_name))
                property = unicode(yj_property_name).replace("_", "-")

            if (property is not None) and (value is not None):
                if property in declarations and declarations[property] != value:

                    if property == "vertical-align" and (
                            (declarations[property] == "sub" and value.startswith("-")) or
                            (declarations[property] == "super" and re.match(r"^[0-9]", value[0]))):
                        value = multiply_value(value, SUPER_SUB_MULT_FACTOR)

                    elif property == "vertical-align" and (
                            (value == "sub" and declarations[property].startswith("-")) or
                            (value == "super" and re.match(r"^[0-9]", declarations[property]))):
                        value = multiply_value(declarations[property], SUPER_SUB_MULT_FACTOR)

                    elif property == "-kfx-attrib-epub-type":

                        vals = set(declarations[property].split() + value.split())
                        for val in vals:
                            if not val.startswith("amzn:"):
                                self.log.error("Style %s property %s has multiple incompatible values: \"%s\" and \"%s\"" % (
                                    style_name, property, declarations[property], value))
                                break
                        else:
                            value = " ".join(sorted(list(vals)))

                    elif property == "text-decoration":

                        vals = set(declarations[property].split() + value.split())
                        value = " ".join(sorted(list(vals)))

                    else:
                        self.log.error("Style %s property %s has multiple values: \"%s\" and \"%s\"" % (
                                    style_name, property, declarations[property], value))

                declarations[property] = value

        if "-kfx-background-positionx" in declarations or "-kfx-background-positiony" in declarations:
            declarations["background-position"] = "%s %s" % (
                    declarations.pop("-kfx-background-positionx", "50%"), declarations.pop("-kfx-background-positiony", "50%"))

        if "-kfx-background-sizex" in declarations or "-kfx-background-sizey" in declarations:
            declarations["background-size"] = "%s %s" % (
                    declarations.pop("-kfx-background-sizex", "auto"), declarations.pop("-kfx-background-sizey", "auto"))

        if "-kfx-fill-color" in declarations or "-kfx-fill-opacity" in declarations:

            declarations["background-color"] = self.fix_color_value(
                    int(declarations.pop("-kfx-fill-color", 0xffffff)),
                    opacity=float(declarations.pop("-kfx-fill-opacity")) if "-kfx-fill-opacity" in declarations else None)

        if ("text-decoration-color" in declarations and "text-decoration" not in declarations and
                declarations["text-decoration-color"] == "rgba(255,255,255,0.00)"):

            declarations.pop("text-decoration-color")
            declarations["text-decoration"] = "none !important"

        if FIX_NONSTANDARD_FONT_WEIGHT and "font-weight" in declarations and re.match(r"^[0-9]+$", declarations["font-weight"]):
            weight_num = int(declarations["font-weight"])
            declarations["font-weight"] = "normal" if weight_num <= 500 else "bold"

        return self.Style(declarations)

    def property_value(self, yj_property_name, yj_value, style_name="", svg=False):
        property_info = YJ_PROPERTY_INFO.get(yj_property_name, None)
        value_map = property_info.values if property_info is not None else None

        val_type = ion_type(yj_value)

        if val_type is IonStruct:
            if "$307" in yj_value:
                raw_value = yj_value.pop("$307")
                yj_unit = yj_value.pop("$306")
                if yj_unit not in YJ_LENGTH_UNITS:
                    self.log.error("Style %s property %s has unknown unit: %s" % (style_name, yj_property_name, yj_unit))

                if (FIX_MINIMUM_BORDER_WEIGHT and
                            yj_property_name in {"$96", "$95",
                            "$97", "$94"} and
                            yj_unit == "$318" and raw_value > 0 and raw_value < 0.5):

                    raw_value = 1.0
                    yj_unit = "$319"

                value = value_str(raw_value, YJ_LENGTH_UNITS.get(yj_unit, yj_unit))

            elif "$19" in yj_value:
                value = self.fix_color_value(yj_value.pop("$19"))

            elif "$499" in yj_value:

                values = []
                for sub_property in ["$499", "$500", "$501",
                        "$502", "$498"]:
                    if sub_property in yj_value:
                        values.append(self.property_value(sub_property, yj_value.pop(sub_property), style_name))

                if yj_value.pop("$336", False):
                    values.append("inset")

                value = " ".join(values)

            elif "$58" in yj_value:

                values = []
                for sub_property in ["$58", "$61", "$60", "$59"]:
                    if sub_property in yj_value:
                        val = self.property_value(sub_property, yj_value.pop(sub_property), style_name)
                        if val != "0" and not val.endswith("%"):
                            self.log.error("Style %s has unexpected %s value: %s" % (style_name, yj_property_name, val))
                        values.append(val.replace("%", ""))
                    else:

                        self.log.error("Style %s is missing sub-property %s for %s" % (style_name, sub_property, yj_property_name))

                value = " ".join(values)

            else:
                self.log.error("Style %s property %s has unknown dict value content: %s" % (
                                style_name, yj_property_name, repr(yj_value)))
                yj_value = {}
                value = "?"

            self.check_empty(yj_value, "Style %s property %s value" % (style_name, yj_property_name))

        elif val_type is IonString:
            value = yj_value

            if yj_property_name == "$11":
                value = self.fix_font_family_list(value)

        elif val_type is IonSymbol:
            if yj_property_name in {"$479", "$175"}:
                value = "url(\"%s\")" % urllib.quote(urlrelpath(self.process_external_resource(yj_value), ref_from=self.STYLES_CSS_FILEPATH))
            else:
                if value_map is not None:
                    if yj_value in value_map:
                        value = value_map[yj_value]
                    else:
                        self.log.warning("unknown property value for %s in style %s: %s" % (yj_property_name, style_name, yj_value))
                        value = unicode(yj_value)
                else:
                    self.log.warning("unexpected symbolic property value for %s in style %s: %s" % (yj_property_name, style_name, yj_value))
                    value = unicode(yj_value)

                if yj_property_name == "$11":
                    value = self.fix_font_family_list(value)

        elif val_type in [IonInt, IonFloat, IonDecimal]:
            value = value_str(yj_value, "")
            if yj_property_name in {"$83", "$86", "$85",
                    "$87", "$84", "$116",
                    "$105", "$75", "$21", "$19",
                    "$24", "$498"}:

                value = self.fix_color_value(value)

            elif value != "0" and yj_property_name not in {"$13", "$148",
                    "$149", "$645", "$647",
                    "$648", "$640",
                    "$641", "$642",
                    "$639", "$70", "$72",
                    "$126", "$125", "$42"} and not svg:

                value += "px"

        elif val_type is IonBool:
            if value_map is not None:
                if yj_value in value_map:
                    value = value_map[yj_value]
                else:
                    self.log.warning("unknown property value for %s in style %s: %s" % (yj_property_name, style_name, yj_value))
                    value = unicode(yj_value)
            else:
                self.log.warning("unexpected boolean property value for %s in style %s: %s" % (yj_property_name, style_name, yj_value))
                value = unicode(yj_value)

        elif val_type is IonList and yj_property_name == "$650":
            value = self.process_polygon(yj_value)

        elif val_type is IonList and yj_property_name == "$646" and len(yj_value) > 0:
            values = []
            for collision in yj_value:
                if collision in COLLISIONS:
                    values.append(COLLISIONS[collision])
                else:
                    self.log.error("Unexpected yj.collision value: %s" % unicode(collision))

            value = " ".join(sorted(values))

        elif val_type is IonList and yj_property_name == "$98":
            value = self.process_transform(yj_value)

        else:
            self.log.error("Style %s property %s has unknown value format (%s): %s" % (
                            style_name, yj_property_name, val_type.__name__, repr(yj_value)))
            value = "?"

        if (yj_property_name in {"$640", "$641",
                "$642", "$639"} and
                value not in ["100", "-100"]):
            self.log.error("Style %s property %s has disallowed value: %s" % (style_name, yj_property_name, value))

        if yj_property_name in {"$32", "$33"} and value == "0em":
            value = "normal"

        return value

    def fixup_styles_and_classes(self):
        if STYLE_TEST: return

        self.css_rules = {}

        heritable_default_properties = self.Style(HERITABLE_DEFAULT_PROPERTIES)
        if self.language:

            heritable_default_properties.update(self.Style({"-kfx-attrib-xml-lang": self.language}), replace=True)

        self.non_heritable_default_properties = self.Style(NON_HERITABLE_DEFAULT_PROPERTIES)

        for book_part in self.book_parts:
            self.simplify_styles(book_part, book_part.html.find("body"), heritable_default_properties)

        style_counts = collections.defaultdict(lambda: 0)

        for book_part in self.book_parts:
            body = book_part.html.find("body")
            for e in body.iter("*"):
                class_name = e.get("class")
                if class_name and (class_name not in AMAZON_SPECIAL_CLASSES):
                    selector = class_selector(class_name)
                    if selector not in self.missing_special_classes:
                        self.log.error("Unexpected class found: %s" % class_name)
                        self.missing_special_classes.add(selector)

                if "style" in e.attrib:

                    style = self.get_style(e)

                    style_attribs = style.partition(name_prefix="-kfx-attrib-", remove_prefix=True)
                    if style_attribs:
                        for name,value in style_attribs.items():
                            if name.startswith("xml-") or name.startswith("epub-"):
                                name = re.subn("-", ":", name, count=1)[0]

                                if name == "epub:type" and not self.generate_epub3:
                                    continue

                            if name in ["colspan", "rowspan", "valign"] and e.tag not in ["tbody", "tr", "td"]:
                                self.log.error("Unexpected class_attribute in %s: %s" % (e.tag, name))

                            self.set_attrib(e, name, value)

                        self.set_style(e, style)

                    if (CVT_DIRECTION_PROPERTY_TO_MARKUP or self.generate_epub3) and ("direction" in style or "unicode-bidi" in style):
                        unicode_bidi = style.get("unicode-bidi", "normal")

                        has_block = False
                        has_content = e.text
                        for ex in e.findall(".//*"):
                            if ex.tag in {"aside", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ol", "table", "td", "ul"}:
                                has_block = True
                            if ex.text or ex.tail or ex.tag in {"img", "li", "math", "object", "svg", "video"}:
                                has_content = True

                        if not has_content:

                            style.pop("direction", None)
                            style.pop("unicode-bidi", None)
                            self.set_style(e, style)

                        elif unicode_bidi in ["embed", "normal"] or has_block:
                            if "direction" in style:
                                e.set("dir", style.pop("direction"))

                            style.pop("unicode-bidi", None)
                            self.set_style(e, style)

                        elif unicode_bidi in ["isolate", "bidi-override", "isolate-override"]:

                            bdx = lxml.html.Element("bdo" if "override" in unicode_bidi else "bdi")
                            if "direction" in style:
                                bdx.set("dir", style.pop("direction"))

                            if e.tag != "img":
                                bdx.text = e.text
                                e.text = None

                                while len(e) > 0:
                                    ec = e[0]
                                    e.remove(ec)
                                    bdx.append(ec)

                                e.insert(0, bdx)

                            style.pop("unicode-bidi", None)
                            self.set_style(e, style)

                        else:
                            self.log.error("Cannot produce EPUB3 equivalent for: unicode-bidi:%s direction:%s" % (
                                    unicode_bidi, style.get("direction", "?")))

                    kfx_style_name = style.pop(self.KFX_STYLE_NAME, "")
                    if kfx_style_name and not style:
                        self.set_style(e, style)

                if "style" in e.attrib:
                    style_counts[e.get("style")] += 1

        sorted_style_data = []
        known_class_name_count = collections.defaultdict(lambda: 0)

        for style_str,count in sorted(style_counts.items(), key=lambda sc: -sc[1]):
            style = self.Style(style_str)
            class_name = style.pop(self.KFX_STYLE_NAME, "class")
            known_class_name_count[class_name] += 1
            sorted_style_data.append((style_str, style, class_name))

        classes = {}
        style_class_names = {}
        used_class_name_count = collections.defaultdict(lambda: 0)

        for style_str,style,class_name in sorted_style_data:
            if known_class_name_count[class_name] > 1 or class_name == "class":
                unique = used_class_name_count[class_name]
                used_class_name_count[class_name] += 1
                class_name = "%s-%d" % (class_name, unique)

            if class_name in classes:
                self.log.error("Class name is not unique: %s" % class_name)
                class_name = make_unique_name(class_name, classes, sep="-")

            for prop_name_prefix,selector_suffix in [
                        ("-kfx-firstline-", "::first-line"),
                        ("-kfx-link-", ":link"),
                        ("-kfx-visited-", ":visited")]:

                selector_style = style.partition(name_prefix=prop_name_prefix, remove_prefix=True)
                if selector_style:
                    self.css_rules[class_selector(class_name) + selector_suffix] = selector_style

            classes[class_name] = style
            style_class_names[style_str] = class_name

        for book_part in self.book_parts:
            body = book_part.html.find("body")
            for e in body.iter("*"):
                style_str = e.get("style", "")
                if style_str in style_class_names:
                    if "class" in e.attrib:
                        self.log.error("Element %s already has class %s when setting new class from styles" % (
                                e.tag, e.get("class")))
                    else:
                        self.set_attrib(e, "class", style_class_names[style_str])
                        self.set_attrib(e, "style", "")
                elif style_str:
                    self.log.warning("Style has no class name: %s" % style_str)

        for class_name, class_style in classes.items():
            media_query = class_style.pop("-kfx-media-query")
            target = self.media_queries[media_query] if media_query else self.css_rules
            target[class_selector(class_name)] = class_style

        for class_style in self.css_rules.values() + self.font_faces:
            self.inventory_style(class_style)

        for mq_classes in self.media_queries.values():
            for class_style in mq_classes.values():
                self.inventory_style(class_style)

    def inventory_style(self, style):
        reported = set()
        for key,value in style.items():
            simple_value = " ".join(zero_quantity(v) for v in value.split())
            if ((simple_value not in KNOWN_STYLES.get(key, set())) and ("*" not in KNOWN_STYLES.get(key, set())) and
                    (key, value) not in reported):
                self.log.warning("Unexpected style definition: %s: %s" % (key, value))
                reported.add((key, value))

    def simplify_styles(self, book_part, elem, parent_properties, default_ordered_list_value=None):
        parent_properties = parent_properties.copy()

        for name in parent_properties.keys():
            if name not in HERITABLE_PROPERTIES:
                parent_properties.pop(name)

        sty = parent_properties.copy().update(self.get_style(elem), replace=True)
        orig_sty = sty.copy()

        sides = []
        for s in ["top", "bottom", "left", "right"]:
            if sty.pop("-kfx-user-margin-%s-percentage" % s, "100") == "-100":
                sides.append(s)

        page_align = sty["-amzn-page-align"] = (",".join(sides) if len(sides) < 4 else "all") if len(sides) > 0 else "none"

        for name, val in sty.items():
            quantity,unit = split_value(val)
            sty[name] = val

            if unit == "lh":
                if name == "line-height":
                    if USE_NORMAL_LINE_HEIGHT and quantity == 1 and len(self.font_faces) == 0:

                        sty[name] = "normal"
                    else:
                        quantity = quantity * LINE_HEIGHT_SCALE_FACTOR

                        if (MINIMUM_LINE_HEIGHT is not None) and (quantity < MINIMUM_LINE_HEIGHT):
                            quantity = MINIMUM_LINE_HEIGHT

                        sty[name] = value_str(quantity, "") # unit-less is like em, but scales properly when inherited
                else:
                    sty[name] = value_str(quantity * LINE_HEIGHT_SCALE_FACTOR, "em")

                quantity,unit = split_value(sty[name])

            if unit == "rem" and (self.GENERATE_EPUB2_COMPATIBLE or not self.generate_epub3):

                if name == "font-size":
                    base_font_size = parent_properties["font-size"]
                else:
                    base_font_size = orig_sty["font-size"]

                base_font_size_quantity,base_font_size_unit = split_value(base_font_size)

                if base_font_size_unit == "rem":
                    quantity = quantity / base_font_size_quantity
                    unit = "em"
                elif base_font_size_unit == "em":
                    unit = "em"
                else:
                    self.log.error("Cannot convert %s:%s with incorrect base font size units %s" % (name, val, base_font_size))

                if name == "line-height" and (MINIMUM_LINE_HEIGHT is not None) and (quantity < MINIMUM_LINE_HEIGHT):
                    quantity = MINIMUM_LINE_HEIGHT

                sty[name] = value_str(quantity, unit)

            if unit == "vh" or unit == "vw":

                if page_align != "none" and name in ["height", "width"]:
                    if name[0] != unit[1]:
                        if not ("height" in sty and "width" in sty):

                            if elem.tag == "img":
                                img_filename = get_url_filename(urlabspath(elem.get("src"), ref_from=book_part.filename))
                                img_height = self.oebps_files[img_filename].height
                                img_width = self.oebps_files[img_filename].width
                                orig_prop = name
                                sty.pop(orig_prop)

                                if name == "width":
                                    quantity = (quantity * img_height) / img_width
                                    name = "height"
                                else:
                                    quantity = (quantity * img_width) / img_height
                                    name = "width"

                                if quantity > 99.0 and quantity < 101.0:
                                    quantity = 100.0
                                else:
                                    self.log.warning("converted %s:%s for img %dw x %dh to %s:%f%%" % (
                                            orig_prop, val, img_width, img_height, name, quantity))

                            else:
                                self.log.error("viewport-based units with wrong property on non-image: %s:%s" % (name, val))
                        else:
                            self.log.error("viewport-based units with wrong property: %s:%s" % (name, val))

                    sty[name] = value_str(quantity, "%")
                    quantity,unit = split_value(sty[name])
                else:
                    self.log.error("viewport-based units with wrong property or without page-align: %s:%s" % (name, val))

        if ("outline-width" in sty) and (sty.get("outline-style", "none") == "none"):
            sty.pop("outline-width")

        if elem.tag == "ol":
            if "start" in elem.attrib:
                default_ordered_list_value = int(elem.get("start"))
                if default_ordered_list_value == 1:
                    self.set_attrib(elem, "start", "")
            else:
                default_ordered_list_value = 1

        elif elem.tag == "ul":
            if "start" in elem.attrib:
                self.set_attrib(elem, "start", "")

            default_ordered_list_value = False

        elif elem.tag == "li":
            if "value" in elem.attrib:
                ordered_list_value = int(elem.get("value"))
                if (default_ordered_list_value is False) or (ordered_list_value == default_ordered_list_value):
                    self.set_attrib(elem, "value", "")

            default_ordered_list_value = None

        else:
            default_ordered_list_value = None

        if "background-image" in sty and "-amzn-max-crop-percentage" in sty:
            if sty["-amzn-max-crop-percentage"] == "0 0 0 0":
                sty.pop("-amzn-max-crop-percentage")
                sty["background-size"] = "contain"
            elif sty["-amzn-max-crop-percentage"] == "0 100 100 0":
                sty.pop("-amzn-max-crop-percentage")
                sty["background-size"] = "cover"

        if "-kfx-baseline-shift" in sty:
            if "vertical-align" in sty:

                if elem.tag in ["a", "aside", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "span", "td"]:
                    new_span = lxml.html.Element("span")
                    self.add_style(new_span, {"vertical-align": sty.pop("-kfx-baseline-shift")})

                    new_span.text = elem.text
                    elem.text = ""

                    while len(elem) > 0:
                        e = elem[0]
                        elem.remove(e)
                        new_span.append(e)

                    elem.append(new_span)
                else:

                    self.log.error("Failed to move baseline-shift property from %s element" % elem.tag)
            else:
                sty["vertical-align"] = sty.pop("-kfx-baseline-shift")

        new_parent_sty = sty.copy()

        for name in ["font-size", "-kfx-user-margin-bottom-percentage", "-kfx-user-margin-left-percentage",
                    "-kfx-user-margin-right-percentage", "-kfx-user-margin-top-percentage"]:
            new_parent_sty[name] = orig_sty[name]

        for child in elem.findall("*"):
            self.simplify_styles(book_part, child, new_parent_sty, default_ordered_list_value)

            if (child.tag == "li") and (default_ordered_list_value not in [None, False]):
                default_ordered_list_value += 1

        font_size_changed = orig_sty["font-size"] != parent_properties["font-size"]
        for name, val in parent_properties.items():
            unit = split_value(val)[1]
            if unit == "%" or (unit == "em" and font_size_changed):
                parent_properties.pop(name)

        parent_properties.update(self.non_heritable_default_properties)
        new_sty = self.Style({})

        if sty["font-size"] == "1em":
            sty.pop("font-size")

        for name, val in sty.items():
            if val != parent_properties.get(name, ""):
                new_sty[name] = val

        self.set_style(elem, new_sty)

    def fix_font_family_list(self, value):

        return self.join_font_family_value(self.split_font_family_value(value))

    def split_font_family_value(self, value):

        return [self.fix_font_name(name) for name in re.split(''',(?=(?:[^'"]|'[^']*'|"[^"]*")*$)''', value)]

    def fix_font_name(self, name, add=False, generic=False):
        name = unquote_font_name(name.strip())

        name = re.sub(r"-(oblique|italic|bold|regular)", r" \1", name, flags=re.IGNORECASE)
        name = MISSPELLED_FONT_NAMES.get(name.lower(), name)

        if "-"in name and name != "sans-serif":

            prefix,sep,name = name.partition("-")
            prefix = prefix.strip().lower()
            name = name.strip()
        else:
            prefix = ""

        if add:

            self.font_name_replacements[name.lower()] = name

            if not generic:
                self.font_names.add(name)

        else:

            name = self.font_name_replacements.get(name.lower(), capitalize_font_name(name))

            if name not in self.font_names and name not in GENERIC_FONT_NAMES:
                self.missing_font_names.add(name)

        return name

    def join_font_family_value(self, value_list):

        return ",".join([quote_font_name(font_name) for font_name in value_list])

    def fix_color_value(self, value, opacity=None):
        if isunicode(value) and not re.match(r"^[0-9]+$", value):
            return value

        color = int(value)

        alpha_int = color >> 24
        alpha = None if alpha_int == 255 else (alpha_int / 254.0)

        if opacity is not None:
            if alpha not in {None, 0.0}:
                self.log.error("Unexpected combination of alpha (%d) and opacity (%0.2f) for color %08x" % (alpha_int, opacity, value))

            alpha = None if opacity == 1.0 else opacity

        if alpha is None:
            hex_color = "#%06x" % (color & 0x00ffffff)
            if hex_color in COLOR_NAME:
                return COLOR_NAME[hex_color]

            return "#000" if hex_color == "#000000" else ("#fff" if hex_color == "#ffffff" else hex_color)

        red = (color & 0x00ff0000) >> 16
        green = (color & 0x0000ff00) >> 8
        blue = (color & 0x000000ff)

        return "rgba(%d,%d,%d,%0.2f)" % (red, green, blue, alpha)

    def get_style(self, elem, remove=False):
        return self.Style(elem.attrib.pop("style", "") if remove else elem.get("style", ""))

    def set_style(self, elem, new_style):
        if type(new_style) is not Style:
            raise Exception("set_style: new=%s (%s)" % (unicode(new_style), type_name(new_style)))

        self.set_attrib(elem, "style", unicode(new_style))

    def add_style(self, elem, new_style, replace=None):

        if type(new_style) is not Style and type(new_style) is not dict:
            raise Exception("add_style: new=%s (%s)" % (unicode(new_style), type_name(new_style)))

        if new_style:
            orig_style_str = elem.get("style", "")

            if orig_style_str:
                new_style = self.Style(orig_style_str).update(new_style, replace)
            elif type(new_style) is not Style:
                new_style = self.Style(new_style)

            self.set_style(elem, new_style)

    def create_css_files(self):
        for css_file in sorted(list(self.css_files)):
            if css_file == self.RESET_CSS_FILEPATH:
                self.oebps_files[self.RESET_CSS_FILEPATH] = OutputFile(RESET_CSS_DATA.encode("utf-8"), "text/css")
                self.manifest.append(ManifestEntry(self.RESET_CSS_FILEPATH))

            elif css_file == self.STYLES_CSS_FILEPATH:
                css_lines = ["@charset \"UTF-8\";"]

                if self.font_faces:
                    css_lines.extend(["@font-face {%s}" % unicode(ff) for ff in sorted(self.font_faces)])

                if self.css_rules:
                    css_lines.extend(["%s {%s}" % (cn, self.css_rules[cn]) for cn in sorted(
                                self.css_rules.keys(), key=natural_sort_key)])

                for mq,css_rules in sorted(self.media_queries.items()):
                    css_lines.append("@media %s {" % mq)
                    css_lines.extend(["    %s {%s}" % (cn, css_rules[cn]) for cn in sorted(css_rules.keys(), key=natural_sort_key)])
                    css_lines.append("}")

                self.oebps_files[self.STYLES_CSS_FILEPATH] = OutputFile("\n".join(css_lines).encode("utf-8"), "text/css")
                self.manifest.append(ManifestEntry(self.STYLES_CSS_FILEPATH))

class Style(object):
    def __init__(self, src, log, sstr=None):
        self.log = log
        self.style_str = self.properties = None

        if type(src) is lxml.html.Element:
            src = src.get("style", "")

        if isinstance(src, str):
            src = src.decode("ascii")

        if isinstance(src, unicode):
            src = self.get_properties(src)

        if isinstance(src, dict):
            self.properties = dict(src)
            self.style_str = sstr
        else:
            raise Exception("cannot create style from %s: %s" % (type(src).__name__, unicode(src)))

    def get_properties(self, style_str):

        if style_str == "None":
            raise Exception("Unexpected 'None' encountered in style")

        if style_str not in style_cache:
            style_cache[style_str] = properties = {}

            for property in re.split(r"((?:[^;\(]|\([^\)]*\))+)", style_str)[1::2]:
                property = property.strip()
                if property:
                    name,sep,value = property.partition(":")
                    name = name.strip()
                    value = value.strip()

                    if sep != ":":
                        self.log.error("Malformed property %s in style: %s" % (name, style_str))
                    else:
                        if name in properties and properties[name] != value:
                            self.log.error("Conflicting property %s values in style: %s" % (name, style_str))

                        properties[name] = value

        return dict(style_cache[style_str])

    def get_style_str(self):
        if self.style_str is None:
            self.style_str = " ".join(["%s: %s;" % s for s in sorted(self.properties.items())])

        return self.style_str

    def keys(self):
        return self.properties.keys()

    def items(self):
        return self.properties.items()

    def get(self, key, default=None):
        return self.properties.get(key, default)

    def __len__(self):
        return len(self.properties)

    def __unicode__(self):
        return self.get_style_str()

    def __str__(self):
        return self.get_style_str().encode("utf8")

    def __eq__(self, other):
        if not isinstance(other, Style):
            raise Exception("Style __eq__: comparing with %s" % type_name(other))

        if self.style_str is not None and other.style_str is not None:
            return self.style_str == other.style_str

        return self.properties == other.properties

    def __ne__(self, other):
        return not self.__eq__(other)

    def __cmp__(self, other):
        if not isinstance(other, Style):
            raise Exception("Style __cmp__: comparing with %s" % type_name(other))

        return cmp(unicode(self), unicode(other))

    def __hash__(self):
        return hash(self.get_style_str())

    def __getitem__(self, key):
        return self.properties[key]

    def __contains__(self, key):
        return key in self.properties

    def __setitem__(self, key, value):
        self.properties[key] = value
        self.style_str = None

    def pop(self, key, default=None):
        value = self.properties.pop(key, default)
        self.style_str = None
        return value

    def clear(self):
        self.properties = {}
        self.style_str = None
        return self

    def copy(self):
        return Style(self.properties, self.log, self.style_str)

    def update(self, other, replace=None):

        if type(other) is Style:
            other = other.properties

        for name,value in other.items():
            if (name in CONFLICTING_PROPERTIES) and not CONFLICTING_PROPERTIES[name].isdisjoint(set(self.properties.keys())):
                self.log.error("Setting conflicting property: %s with %s" % (name, list_symbols(self.properties.keys())))

            if name in self.properties and self.properties[name] != value:
                if replace is Exception:
                    raise Exception("Setting conflicting property value: %s = %s >> %s" % (name, self.properties[name], value))

                if replace is None:
                    self.log.error("Setting conflicting property value: %s = %s >> %s" % (name, self.properties[name], value))
                elif not replace:
                    continue

            self.properties[name] = value
            self.style_str = None

        return self

    def partition(self, property_names=None, name_prefix=None, remove_prefix=False, add_prefix=False, keep=False, keep_all=False):

        match_props = {}
        other_props = {}

        for name, value in self.properties.items():
            if name_prefix is not None:
                if add_prefix:
                    name = "%s-%s" % (name_prefix, name)
                    match = True
                else:
                    match = name.startswith(name_prefix)

                if match and remove_prefix:
                    name = name[len(name_prefix):]
            else:
                match = (name in property_names)

            if match:
                match_props[name] = value
            else:
                other_props[name] = value

        if keep:
            self.properties = match_props
            self.style_str = None

        if keep or keep_all:
            return Style(other_props, self.log)

        self.properties = other_props
        self.style_str = None
        return Style(match_props, self.log)

    def remove_default_properties(self, default_style):
        defaults = default_style.properties

        for name, value in self.properties.items():
            if value == defaults.get(name, ""):
                self.properties.pop(name)
                self.style_str = None

        return self

def value_str(quantity, unit=""):
    if quantity is None:
        return unit

    if type(quantity) is float:
        q_str = "%g" % quantity
        if "e" in q_str:
            q_str = "%.4f" % quantity

    elif type(quantity) is decimal.Decimal and abs(quantity) < 1e-10:
        q_str = "0"
    else:
        q_str = unicode(quantity)

    if "." in q_str:
        q_str = q_str.rstrip("0").rstrip(".")

    if q_str == "0":
        return q_str

    return q_str + unit

def zero_quantity(val):

    if re.match(r"^#[0-9a-f]+$", val) or re.match(r"^rgba\([0-9]+,[0-9]+,[0-9]+,[0-9.]+\)$", val) or val in COLOR_NAMES:
        return "#0"

    num_match = re.match(r"^([+-]?[0-9]+\.?[0-9]*)(|em|ex|ch|rem|vw|vh|vmin|vmax|%|cm|mm|in|px|pt|pc)$", val)
    if num_match:
        return "0"

    return val

def multiply_value(val, factor):
    quantity,unit = split_value(val)
    return value_str(quantity * factor, unit)

def split_value(val):

    num_match = re.match(r"^([+-]?[0-9]+\.?[0-9]*)", val)
    if not num_match:
        return (None, val)

    num = num_match.group(1)
    unit = val[len(num):]

    return (decimal.Decimal(num), unit)

def quote_font_name(value):
    if re.match(r"^[a-zA-Z][a-zA-Z0-9-]*$", value):
        return value

    if "'" not in value:
        return "'" + value + "'"

    return "\"" + value.replace("\"", "\\\"") + "\""

def unquote_font_name(value):
    if (value.startswith("'") or value.startswith("\"") or value.endswith("'") or value.endswith("\"")):
        if value[0] == value[-1] and len(value) > 1:
            return value[1:-1].replace("\\\"", "\"").replace("\\'", "'").strip()

        raise ValueError("Incorrectly quoted font name: %s" % value)

    return value

def capitalize_font_name(name):
    return " ".join([(word.capitalize() if len(word) > 2 else word.upper()) for word in name.split()])

def class_selector(class_name):
    return "." + class_name

