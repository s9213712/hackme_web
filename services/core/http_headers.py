import os
from urllib.parse import quote


def build_content_disposition(disposition, filename):
    clean_name = os.path.basename(str(filename or "")).strip() or "download.bin"
    ascii_name = "".join(
        ch
        if ch.isascii() and ch not in {'"', "\\", "\r", "\n"} and 32 <= ord(ch) < 127
        else "_"
        for ch in clean_name
    ).strip(" .")
    if not ascii_name:
        ascii_name = "download.bin"
    ascii_name = ascii_name[:160]
    utf8_name = quote(clean_name, safe="!#$&+-.^_`|~")
    return f'{disposition}; filename="{ascii_name}"; filename*=UTF-8\'\'{utf8_name}'
