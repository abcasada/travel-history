"""Write the API's OpenAPI schema (input for the frontend's generated client):
./dev manage export_openapi > frontend/src/api/openapi.json"""

import json

from django.core.management.base import BaseCommand

from config.api import api


class Command(BaseCommand):
    help = "Print the OpenAPI schema as JSON."

    def handle(self, *_args, **_options):
        self.stdout.write(json.dumps(api.get_openapi_schema(), indent=2, sort_keys=True))
