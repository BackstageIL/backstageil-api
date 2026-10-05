import os

# Importing app.main builds the module-level app from the developer's local .env. Tests must
# never report to the real Sentry project; an environment variable wins over .env.
os.environ["SENTRY_DSN"] = ""
