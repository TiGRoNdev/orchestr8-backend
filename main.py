# SPDX-License-Identifier: LGPL-2.1-or-later


import os
import gunicorn.app.base
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import router


app = FastAPI(
    title="Orchestr8",
    description="Orchestr8 backend service",
    version="0.0.1"
)

app.include_router(router)


app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StandaloneApplication(gunicorn.app.base.BaseApplication):

    def __init__(self, app, options=None):
        self.options = options or {}
        self.application = app
        super().__init__()

    def load_config(self):
        config = {key: value for key, value in self.options.items()
                  if key in self.cfg.settings and value is not None}
        for key, value in config.items():
            self.cfg.set(key.lower(), value)

    def load(self):
        return self.application


if __name__ == "__main__":
    options = {
        'bind': '%s:%s' % ('0.0.0.0', f'{os.environ["APP_PORT"]}'),
        'pidfile': '/tmp/gunicorn.pid',
        'keyfile': os.environ["KEY_FILE"],
        'certfile': os.environ["CERT_FILE"],
        'ssl_version': 'TLS',
        'workers': 6,
        'timeout': 600,
        'worker_class': "uvicorn.workers.UvicornH11Worker",
        'max_requests': 1000, # Restart gunicorn worker processes every 1000-1100 requests
        'max_requests_jitter': 100,
        'backlog': 8192,
        'keepalive': 20,
        'accesslog': '-',
        'logconfig_dict': {
            "version": 1,
            "disable_existing_loggers": False,
            "root": {"level": "INFO", "handlers": ["console"]},
            "loggers": {
                "gunicorn.error": {
                    "level": "INFO",
                    "handlers": ["error_console"],
                    "propagate": True,
                    "qualname": "gunicorn.error"
                },
                "gunicorn.access": {
                    "level": "INFO",
                    "handlers": ["console"],
                    "propagate": True,
                    "qualname": "gunicorn.access"
                },
                "root": {
                    "level": "INFO",
                    "handlers": ["console"],
                    "propagate": True,
                    "qualname": "root"
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "generic",
                    "stream": "ext://sys.stdout"
                },
                "error_console": {
                    "class": "logging.StreamHandler",
                    "formatter": "generic",
                    "stream": "ext://sys.stderr"
                },
            },
            "formatters": {
                "generic": {
                    "format": "%(asctime)s [%(process)d] [%(levelname)s] %(message)s",
                    "datefmt": "[%Y-%m-%d %H:%M:%S %z]",
                    "class": "logging.Formatter"
                }
            }
        }
    }
    StandaloneApplication(app, options).run()

