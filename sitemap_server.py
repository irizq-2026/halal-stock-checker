"""
Lightweight Tornado route addition to serve sitemap.xml
at the root path alongside the main Streamlit app.
This does not affect any existing Streamlit functionality.
"""
import os
from pathlib import Path
from streamlit.web.server import Server
import tornado.web

SITEMAP_PATH = Path(__file__).parent / "sitemap.xml"


class SitemapHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Content-Type", "application/xml")
        if SITEMAP_PATH.exists():
            self.write(SITEMAP_PATH.read_text())
        else:
            self.set_status(404)
            self.write("sitemap.xml not found")


def register_sitemap_route():
    """
    Hooks into Streamlit's Tornado server to add a
    /sitemap.xml route. Called once at app startup.
    """
    try:
        server = Server.get_current()
        if server is not None:
            app = server._app
            app.add_handlers(
                r".*",
                [(r"/sitemap\.xml", SitemapHandler)]
            )
    except Exception as e:
        print(f"[sitemap] Could not register route: {e}")
