from django.conf import settings

DEBUG = getattr(settings, 'DEBUG', False)
USE_TZ = getattr(settings, 'USE_TZ', True)

_stream_settings = getattr(settings, 'TWITTER_STREAM_SETTINGS', {})

# If true, the embedded retweeted_status tweets will be captured
CAPTURE_EMBEDDED = _stream_settings.get('CAPTURE_EMBEDDED', False)

# The number of seconds in between checks for filter term changes and tweet inserts
POLL_INTERVAL = _stream_settings.get('POLL_INTERVAL', 10)

# The default keys to use for streaming
DEFAULT_KEYS_NAME = _stream_settings.get('DEFAULT_KEYS_NAME', None)

# Put the stream in a loop to prevent random termination
PREVENT_EXIT = _stream_settings.get('PREVENT_EXIT', False)

# Record stats like memory usage in the database
MONITOR_PERFORMANCE = _stream_settings.get('MONITOR_PERFORMANCE', True)

# The number of tweets to insert into the database at once
INSERT_BATCH_SIZE = _stream_settings.get('INSERT_BATCH_SIZE', 1000)

# South migrations
SOUTH_MIGRATION_MODULES = { 'twitter-stream': 'django_twitter_stream.twitter_stream.south_migrations', }
