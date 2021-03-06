# -*- coding: utf-8 -*-


from SimpleHTTPServer import SimpleHTTPRequestHandler


import cgi
import os
from os.path import abspath, exists, isfile, isdir, join, splitext
from archive import get_doc_archive
from whoosh.index import open_dir
from whoosh.lang.porter import stem
from whoosh.qparser import MultifieldParser
from whoosh.scoring import WeightingModel, BaseScorer, MultiWeighting, BM25F
from ds import INDEX_SCHEMA


#-------------------------------------#
#------------- Constants -------------#
#-------------------------------------#

DAEMONIZED  = True
DOC_ARC_EXT = 'dar'
HOME_FOLDER = ''
CHUNK_SIZE  = 32768
EXTENSIONS  = {
    '.html': 'text/html',
    '.htm' : 'text/html',
    '.js'  : 'application/x-javascript',
    '.css' : 'text/css',
    '.gif' : 'image/gif',
    '.png' : 'image/png',
    '.tif' : 'image/tiff',
    '.jpg' : 'image/jpeg',
    '.bmp' : 'image/bmp',
    '.pdf' : 'application/pdf',
    '.dvi' : 'application/x-dvi',
    '.eps' : 'application/postscript',
    '.doc' : 'application/msword',
    '.chm' : 'application/mshelp',
    '.hlp' : 'application/mshelp',
    '.swf' : 'application/x-shockwave-flash',
    '.ps'  : 'application/postscript',
}
SEARCH_RESULT = u'<div class="search_result"><a href="%s" target="_">%s</a><br>%s</div>'
SEARCH_FIELDS = [u'path', u'title', u'content', u'h1', u'h2', u'h3', u'h4', u'h5']


class TwoModel(WeightingModel):
    use_final = True
    def scorer(self, searcher, fieldname, text, qf=1):
        return TwoModel.TwoScorer(searcher, fieldname, text)
    def final(self, searcher, docnum, score):
        print '--->', searcher.stored_fields(docnum)['title']
        return score
    class TwoScorer(BaseScorer):
        def __init__(self, searcher, fieldname, text):
            self.__searcher = searcher
            self.__fieldname = fieldname
            self.__text = text
        def score(self, matcher):
            # print '@ TwoScorer', self.__fieldname, self.__text
            print '--->', self.__searcher.stored_fields(matcher.id())['title']
            return matcher.weight() * 10


class BoostWeighting(WeightingModel):
    use_final = True


    def __init__(self, booster):
        self.__booster = booster


    def scorer(self, searcher, fieldname, text, qf=1):
        # print '@ scorer()'
        return BoostWeighting.BoostScorer(searcher, fieldname, text, self.__booster)


    def final(self, searcher, docnum, score):
        # print '@ final()', score
        return score


    class BoostScorer(BaseScorer):
        def __init__(self, searcher, fieldname, text, booster):
            self.__searcher = searcher
            self.__fieldname = fieldname
            self.text = text
            self.__booster = booster


        def score(self, matcher):
            # print '@ score()', matcher.weight() * self.__booster
            return matcher.weight() * self.__booster


class DocServlet(SimpleHTTPRequestHandler):
    def __init__(self, request, client_address, server):
        SimpleHTTPRequestHandler.__init__(self, request, client_address, server)


    def do_redirect(self, url):
        self.send_response(301, 'Moved Permanently')
        self.send_header('Location', url)
        self.end_headers()


    def do_access_denied(self):
        self.send_response(403)
        self.end_headers()
        self.wfile.write('<h1>Access Denied!</h1>')


    def do_not_found(self):
        self.send_response(404)
        self.end_headers()
        self.wfile.write('<h1>Requested resource is not found.</h1>')


    def do_search(self, params):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')

        indices_dir = HOME_FOLDER + '/.indices'
        if not os.path.exists(indices_dir):
            self.wfile.write('<div class="search_result">Index folder %s does not exist.</div>' % indices_dir)
            self.end_headers()
            return

        n = 10
        page = 1
        if 'n' in params:
            n = int(params['n'])
            if n < 10:
                n = 10
            if n > 100:
                n = 100
        if 'p' in params:
            page = int(params['p'])
        if 'q' in params:
            keywords = unicode(' '.join([stem(param.strip()).decode('utf-8') for param in params['q'].lower().split()]))
            query = MultifieldParser(SEARCH_FIELDS, schema=INDEX_SCHEMA).parse(keywords)
            # print query
            weighting = MultiWeighting(BM25F(),
                title=BoostWeighting(10.0), path=BoostWeighting(8.0),
                h1=BoostWeighting(8.0), h2=BoostWeighting(6.0), h3=BoostWeighting(3.0),
                h4=BoostWeighting(2.0), h5=BoostWeighting(1.2),
            )
            searcher = open_dir(indices_dir).searcher(weighting = weighting)
            # print 'n=', n, 'page=', page
            results = searcher.search(query, limit=None)
            self.send_header('Search-Query', keywords)
            self.send_header('Search-Size', len(results))
            pages = len(results) // n
            if len(results) % n > 0:
                pages += 1
            if page < 1:
                page = 1
            elif page > pages:
                page = pages
            self.send_header('Search-Page', page)
            self.send_header('Search-Pages', pages)
            if page > 1:
                self.send_header('Search-Prev', page - 1)
            if page < pages:
                self.send_header('Search-Next', page + 1)
            self.send_header('Search-Limit', n)
            self.end_headers()

            for result in results[(page-1)*n : page*n]:
                # print result.rank, result.score, result.docnum
                response = SEARCH_RESULT % (result['url'], result['title'], result['content'][:200])
                self.wfile.write(response.encode('utf-8'))
        else:
            self.end_headers()
            self.wfile.write('<div class="search_result">No query parameter.</div>')


    def log_message(self, format, *args):
        if DAEMONIZED:
            """
                Overwrite the default message logging because if daemonized
                it somehow breaks when logging to sys.stderr.
            """
            pass
        else:
            SimpleHTTPRequestHandler.log_message(self, format, *args)


    def do_GET(self):
        pos_param = self.path.find('?')
        path_info = self.path
        params = {}
        if pos_param > -1:
            path_info = self.path[:pos_param]
            params = dict(cgi.parse_qsl(self.path[pos_param+1:]))
        fullpath = abspath(HOME_FOLDER + path_info)
        if self.path.startswith('/s'):
            self.do_search(params)
            return

        # prevent accssing files beyond home folder
        if not fullpath.startswith(HOME_FOLDER):
            self.do_access_denied()
            return

        if self.path.endswith('/'):
            self.do_redirect(join(self.path, 'index.html'))
            return

        # check if file/folder exists
        if os.access(fullpath, os.F_OK) and exists(fullpath):
            # check if file/folder readable
            if os.access(fullpath, os.R_OK):
                # check if it's a folder
                if isdir(fullpath):
                    self.do_redirect(join(self.path, 'index.html'))
                    return
                elif isfile(fullpath):
                    statinfo = os.stat(fullpath)

                    mname, ext = splitext(fullpath)
                    ext = ext.lower()

                    if ext in EXTENSIONS:
                        mime_type = EXTENSIONS[ext]
                    else:
                        mime_type = 'application/octet-stream'

                    self.send_response(200)
                    self.send_header('Content-Type', mime_type)
                    self.send_header('Content-Length', str(statinfo.st_size))
                    self.end_headers()

                    try:
                        fh = open(fullpath, 'rb')
                        while True:
                            chunk = fh.read(CHUNK_SIZE)
                            if len(chunk)>0:
                                self.wfile.write(chunk)
                            else:
                                break
                    finally:
                        fh.close()
                    return
                else:
                    self.do_not_found()
                    return
            else:
                # not readable
                self.do_access_denied()
                return

        # check if it's a doc archive request
        self.path = path_info # ignore query parameters
        paths = self.path.split('/')
        fullpath = abspath(HOME_FOLDER)
        for i, path in enumerate(paths):
            if path==None or len(path)==0: continue

            fullpath = join(fullpath, path)
            doc_archive = get_doc_archive(fullpath + '.' + DOC_ARC_EXT)
            if doc_archive:
                if i==len(paths)-1:
                    if doc_archive.index_file:
                        self.do_redirect(join(self.path, doc_archive.index_file))
                        return
                    else:
                        self.do_redirect(join(self.path, 'index.html'))
                        return

                arch_path = '/'.join(paths[i+1:])
                if doc_archive.contains(arch_path):
                    page = doc_archive.get_page(arch_path)
                    if page:
                        self.send_response(200)
                        mname, ext = splitext(arch_path)
                        ext = ext.lower()

                        if ext in EXTENSIONS:
                            mime_type = EXTENSIONS[ext]
                        else:
                            mime_type = 'application/octet-stream'

                        self.send_header('Content-Type', mime_type)
                        self.send_header('Content-Length', str(page.length))
                        self.end_headers()

                        for chunk in page:
                            self.wfile.write(chunk)

                        return

                break

        # otherwise, it's an invalid request
        self.do_not_found()
        return

