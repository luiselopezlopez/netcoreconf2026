import os

from demo_web.server import check_configuration, configure_tracing, create_app

check_configuration()
provider = configure_tracing()
app = create_app(cloud_host=os.environ["WEBSITE_HOSTNAME"])
