import logging
from logging.config import dictConfig
import time
import signal
from django.core.exceptions import ObjectDoesNotExist

from django.core.management.base import BaseCommand
import sys
import tweepy
import twitter_monitor
from twitter_stream import models
from twitter_stream import utils
from twitter_stream import settings


# Setup logging if not already configured
logger = logging.getLogger(__name__)
if not logger.handlers:
    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "twitter_stream": {
                "level": "DEBUG",
                "class": "logging.StreamHandler",
            },
        },
        "twitter_stream": {
            "handlers": ["twitter_stream"],
            "level": "DEBUG"
        }
    })


class Command(BaseCommand):
    """
    Starts a process that streams data from Twitter.

    Example usage:
    python manage.py stream
    python manage.py stream --poll-interval 25
    python manage.py stream MyCredentialsName
    """

    def add_arguments(self, parser):
        super(Command, self).add_arguments(parser)
        parser.add_argument(
            '--poll-interval',
            action='store',
            dest='poll_interval',
            default=settings.POLL_INTERVAL,
            help='Seconds between term updates and tweet inserts.'
        ),
        parser.add_argument(
            '--prevent-exit',
            action='store_true',
            dest='prevent_exit',
            default=False,
            help='Put the stream in a loop to prevent random termination. Use this if you are not running inside a process management system like supervisord.'
        ),
        parser.add_argument(
            '--to-file',
            action='store',
            dest='to_file',
            default=None,
            help='Write tweets to the given JSON file instead of the database.'
        ),
        parser.add_argument(
            '--from-file',
            action='store',
            dest='from_file',
            default=None,
            help='Read tweets from a given file, one JSON tweet per line.'
        ),
        parser.add_argument(
            '--from-file-long',
            action='store',
            dest='from_file_long',
            default=None,
            help='Read tweets from a given file, where JSON tweets are pretty-printed.'
        ),
        parser.add_argument(
            '--rate-limit',
            action='store',
            dest='rate_limit',
            default=None,
            type=float,
            help='Rate to read in tweets, used ONLY if streaming from a file.'
        ),
        parser.add_argument(
            '--limit',
            action='store',
            dest='limit',
            default=None,
            type=int,
            help='Limit the number of tweets, used ONLY if streaming from a file.'
        )
    args = '<keys_name>'
    help = "Starts a streaming connection to Twitter"

    def handle(self, keys_name=settings.DEFAULT_KEYS_NAME, *args, **options):

        # The suggested time between hearbeats
        poll_interval = float(options.get('poll_interval', settings.POLL_INTERVAL))
        prevent_exit = options.get('prevent_exit', settings.PREVENT_EXIT)
        to_file = options.get('to_file', None)
        from_file = options.get('from_file', None)
        from_file_long = options.get('from_file_long', None)
        rate_limit = options.get('rate_limit', 50)
        limit = options.get('limit', None)

        if from_file and from_file_long:
            logger.error("Cannot use both --from-file and --from-file-long")
            exit(1)

        # First expire any old stream process records that have failed
        # to report in for a while
        timeout_seconds = 3 * poll_interval
        models.StreamProcess.expire_timed_out()

        # Create the stream process for tracking ourselves
        stream_process = models.StreamProcess.create(
            timeout_seconds=timeout_seconds
        )

        listener = utils.QueueStreamListener(to_file=to_file)

        if from_file:
            checker = utils.FakeTermChecker(queue_listener=listener,
                                            stream_process=stream_process)
        else:
            checker = utils.FeelsTermChecker(queue_listener=listener,
                                             stream_process=stream_process)

        def stop(signum, frame):
            """
            Register stream's death and exit.
            """

            if stream_process:
                stream_process.status = models.StreamProcess.STREAM_STATUS_STOPPED
                stream_process.heartbeat()

            # Let the tweet listener know it should be quitting asap
            listener.set_terminate()

            logger.error("Terminating")

            raise SystemExit()

        # Installs signal handlers for handling SIGINT and SIGTERM
        # gracefully.
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)

        keys = None
        if not from_file:
            # Only need keys if we are connecting to twitter
            while not keys:
                try:
                    keys = models.ApiKey.get_keys(keys_name)
                except ObjectDoesNotExist:
                    if keys_name:
                        logger.error("Keys for '%s' do not exist in the database. Waiting...", keys_name)
                    else:
                        logger.warn("No keys in the database. Waiting...")

                time.sleep(5)
                stream_process.status = models.StreamProcess.STREAM_STATUS_WAITING
                stream_process.heartbeat()

        try:
            if keys:
                logger.info("Connecting to Twitter with keys for %s/%s", keys.user_name, keys.app_name)
                stream_process.keys = keys
                stream_process.save()

                # Only need auth if we have keys (i.e. connecting to twitter)
                auth = tweepy.OAuthHandler(keys.api_key, keys.api_secret)
                auth.set_access_token(keys.access_token, keys.access_token_secret)

                # Start and maintain the streaming connection...
                stream = twitter_monitor.DynamicTwitterStream(auth, listener, checker)

            elif from_file or from_file_long:

                read_pretty = False
                if from_file_long:
                    from_file = from_file
                    read_pretty = True

                if from_file == '-':
                    from_file = sys.stdin
                    logger.info("Reading tweets from stdin")
                else:
                    if read_pretty:
                        logger.info("Reading tweets from JSON file %s (pretty-printed)", from_file)
                    else:
                        logger.info("Reading tweets from JSON file %s", from_file)

                stream = utils.FakeTwitterStream(from_file, pretty=read_pretty,
                                                 listener=listener, term_checker=checker,
                                                 limit=limit, rate_limit=rate_limit)
            else:
                raise Exception("No api keys and we're not streaming from a file.")

            if to_file:
                logger.info("Saving tweets to %s", to_file)

            if prevent_exit:
                while checker.ok():
                    try:
                        stream.start_polling(poll_interval)
                    except Exception as e:
                        checker.error(e)
                        time.sleep(1)  # to avoid craziness
            else:
                stream.start_polling(poll_interval)

            logger.error("Stopping because of excess errors")
            stream_process.status = models.StreamProcess.STREAM_STATUS_STOPPED
            stream_process.heartbeat()

        except Exception as e:
            logger.error(e, exc_info=True)

        finally:
            stop(None, None)
