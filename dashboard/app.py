import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.views import jobs_browser  # noqa: E402
from db.connection import init_db  # noqa: E402

st.set_page_config(page_title="Job Comp Checker", layout="wide")
init_db()

PAGES = {
    "Jobs Browser": jobs_browser.render,
    # "Single Job Match": added once Milestone 3's matching engine lands
    # "Portfolio": added once Milestone 3's matching engine lands
}

page = st.sidebar.radio("View", list(PAGES.keys()))
PAGES[page]()
