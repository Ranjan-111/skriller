# Copied search/reference subset

`link_metadata.py` is unchanged from the pinned acquired file. `search_urls.py` changes one import to `.filter_errors`; that module contains the unchanged `FilterValidationError` class extracted from upstream contracts.py, without importing unrelated browser/workflow contracts. Package initializer is new. LICENSE and NOTICE are retained. PROVENANCE.json records upstream and runtime hashes; tests check both. These modules build URLs and normalize returned references; they never launch a browser or load a session.
