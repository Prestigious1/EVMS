from whitenoise.storage import CompressedManifestStaticFilesStorage

class EVMSStaticFilesStorage(CompressedManifestStaticFilesStorage):
    manifest_strict = False
