# -*- coding: utf-8 -*-
"""
Created on Wed Feb  1 17:39:36 2023

@author: dgrishchuk
"""

# https://www.taheramlaki.com/blog/articles/python-reading-large-xml-file/?fbclid=IwAR038EvIKG61VPsXm743Tevhr1ELEEhiTxyEw73nWQZI2Zz-nv8U1BavXzQ


import xml.sax


class CustomContentHandler(xml.sax.handler.ContentHandler):

    def __init__(self):
        self._page = None
        self._tags_stack = None
        self.read_stack = []

    def startElement(self, name, attrs):
        if name == "page":
            self._page = {"title": "", "text": ""}
            self._tags_stack = []

        if self._page is not None:
            self._tags_stack.append(name)

    def endElement(self, name):
        if self._page is not None:
            if self._tags_stack[-1] == "page":
                self.read_stack.append((self._page['title'], self._page['text']))
                self._page = None
                self._tags_stack = None
            else:
                del self._tags_stack[-1]

    def characters(self, content):
        if self._page is not None:
            if self._tags_stack[-1] == "title":
                self._page['title'] += content
            elif self._tags_stack[-1] == "text":
                self._page['text'] += content


handler = CustomContentHandler()
xml.sax.parse("./wikiToyData.xml", handler)
print(handler.read_stack)


# %%

import xml.etree.ElementTree as ET
from multiprocessing import Manager

class ETParser:
    def __init__(self, file_path, queue):
        self._file_path = file_path
        self._page = None
        self._tags_stack = None
        self._queue = queue

    def parse(self):
        for event, element in ET.iterparse(self._file_path, events=('start', 'end')):
            tag_name = element.tag.rsplit("}", 1)[-1].strip()

            if event == "start":
                if tag_name == "page":
                    self._page = {"title": "", "text": ""}
                    self._tags_stack = []

                if self._page is not None:
                    self._tags_stack.append(tag_name)
            else:  # elif event == "end"
                if self._page is not None:
                    if self._tags_stack[-1] == "title":
                        self._page['title'] += element.text
                    elif self._tags_stack[-1] == "text":
                        self._page['text'] += element.text

                    if self._tags_stack[-1] == "page":
                        self._queue.put((self._page['title'], self._page['text']))
                        self._page = None
                        self._tags_stack = None
                    else:
                        del self._tags_stack[-1]

           # we should clear element object, otherwise memory will be filled quickly
            element.clear()

if __name__ == "__main__":
    manager = Manager()
    queue = manager.Queue()
    parser = ETParser("./wikiToyData.xml", queue)
    parser.parse()

    while not queue.empty():
        print(queue.get())