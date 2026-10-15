# Copied parser subset

`models.py` and `parser.py` are byte-for-byte copies of the pinned acquired files recorded in PROVENANCE.json. Only the containing Python namespace and packaging initializer are new. Relative `.models` imports retain the original dependency closure. Authentication, cookie import and network client modules are not imported by this subset. Tests check exact source and runtime file hashes.
