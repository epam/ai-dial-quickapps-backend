import json
from io import StringIO

import pandas as pd
from bs4 import BeautifulSoup


class ResponseFormatter:
    @staticmethod
    def format_json(content: str) -> str:
        return json.dumps(json.loads(content), indent=4)

    @staticmethod
    def format_xml(content: str) -> str:
        from xml.dom.minidom import parseString

        return parseString(content).toprettyxml()

    @staticmethod
    def format_html(content: str) -> str:
        result = BeautifulSoup(content, 'html.parser').prettify()
        if isinstance(result, bytes):
            return result.decode('utf-8')
        return result

    @staticmethod
    def format_csv(content: str) -> str:
        df = pd.read_csv(StringIO(content))
        return df.to_markdown()
