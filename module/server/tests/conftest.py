# DeepSeek-13 1.7 (F-16): isolate test account-lease files from the
# production %TEMP%\oas-account-leases directory so lifecycle tests never
# contend with the real Core's account lease (AccountLeaseError).
import os
import tempfile

_LEASE_DIR = tempfile.mkdtemp(prefix='oas-test-leases-')
os.environ.setdefault('OAS_LEASE_DIR', _LEASE_DIR)
