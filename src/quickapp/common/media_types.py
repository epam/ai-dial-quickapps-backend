from enum import StrEnum


class MediaTypes(StrEnum):
    """
    A media type (also known as a Multipurpose Internet Mail Extensions or MIME type) indicates the nature
    and format of a document, file, or assortment of bytes.

    https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types
    https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types
    """

    # ~~~~~ Text types ~~~~~
    JSON = "application/json"
    XML = "application/xml"
    HTML = "application/html"
    CSV = "application/csv"
    TEXT_JSON = "text/json"
    TEXT_XML = "text/xml"
    TEXT_HTML = "text/html"
    TEXT_CSV = "text/csv"
    MARKDOWN = "text/markdown"
    PLAIN_TEXT = "text/plain"
    CSS = "text/css"
    JAVASCRIPT = "text/javascript"
    PDF = "application/pdf"
    XML_OLD = "text/xml"

    # ~~~~~ Image types ~~~~~
    APNG = "image/apng"
    AVIF = "image/avif"
    BMP = "image/bmp"
    GIF = "image/gif"
    ICO = "image/vnd.microsoft.icon"  # .ico
    JPEG = "image/jpeg"
    PNG = "image/png"
    SVG = "image/svg+xml"
    TIFF = "image/tiff"
    WEBP = "image/webp"
    X_ICON = "image/x-icon"

    # ~~~~~~~ Other ~~~~~~~
    DOC = "application/msword"  # .doc
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"  # .docx
    PDB = "chemical/x-pdb"
    PLOTLY = "application/vnd.plotly.v1+json"
    PPT = "application/vnd.ms-powerpoint"  # .ppt
    PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"  # .pptx
    TTYD_TABLE = "application/dial-ttyd-table"
    UNKNOWN_BINARY = "application/octet-stream"
    XLS = "application/vnd.ms-excel"  # .xls
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"  # .xlsx
