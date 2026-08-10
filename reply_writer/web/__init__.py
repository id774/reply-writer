#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# reply_writer/web/__init__.py: Location of the web assets
#
#  Description:
#  Flask needs absolute paths to the templates and the static files, so
#  that the application runs from any working directory. This module
#  resolves both from the location of the package itself.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/reply-writer
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only
#
#  Version History:
#  v1.0 2026-08-10
#       Initial release.
#
########################################################################

import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(PACKAGE_DIR, "templates")
STATIC_DIR = os.path.join(PACKAGE_DIR, "static")
